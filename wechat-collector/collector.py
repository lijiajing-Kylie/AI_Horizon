"""Standalone WeChat Official Account (公众号) collector — minimal debug driver.

This is a *pure additive* debug tool that drives the bundled ``src.we_mp_rss``
core directly, bypassing Horizon's config / models / orchestrator entirely.
It does NOT import ``src.models``, ``src.storage``, ``src.orchestrator`` or
``src.scrapers.wxmp`` — only the vendored we-mp-rss core + the standard library.

It reuses the same login-token files Horizon uses (``data/wxmp/wx.lic`` +
``key.lic``), so a token obtained here also works for the main pipeline and
vice-versa.  It changes nothing about Horizon's own behavior.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Make the repo root importable so ``import src.we_mp_rss`` works regardless of
# the CWD the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.we_mp_rss  # noqa: E402  (bootstrap first)

# Pseudo-feed (公众号精选文章) — not a real account, cannot derive a fakeid.
_FEATURED_FEED_ID = "MP_WXS_FEATURED_ARTICLES"

_ACCOUNTS_PATH = Path(__file__).resolve().parent / "accounts.json"
_DEFAULT_DATA_DIR = "data/wxmp"


@dataclass
class CollectorConfig:
    """Minimal config injected into the bundled core (no Horizon models).

    Field names match the ``getattr()`` reads in
    ``src/we_mp_rss/core/config.py:build_config_dict`` — keep them in sync if
    the vendored core ever grows new required keys.
    """

    gather_content: bool = False   # False = 不抓正文,不发浏览器
    clean_html: bool = False
    proxy: Optional[str] = None
    max_page: int = 1
    gather_interval: int = 0       # 单次请求,页面间不随机停顿


def load_accounts() -> Dict[str, str]:
    """Load the built-in 公众号名称 → feed_id mapping from accounts.json."""
    with open(_ACCOUNTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def faker_id_from_feed_id(feed_id: str) -> Optional[str]:
    """Derive the WeChat ``fakeid`` from a ``MP_WXS_<base64>`` feed_id.

    Same 3-line rule as ``src/scrapers/wxmp.py`` (kept here to avoid importing
    the Horizon scraper layer): ``faker_id = base64(feed_id minus "MP_WXS_")``.
    """
    if not feed_id or feed_id == _FEATURED_FEED_ID:
        return None
    try:
        b64 = feed_id.removeprefix("MP_WXS_")
        return base64.b64encode(b64.encode()).decode()
    except Exception:
        return None


def resolve_account(name: Optional[str] = None, feed_id: Optional[str] = None) -> Tuple[str, str]:
    """Resolve ``(name, feed_id)`` from either an account name or a raw feed_id.

    ``--feed-id`` short-circuits the lookup; otherwise the positional name is
    looked up in ``accounts.json``.  Unknown names raise a helpful error.
    """
    if feed_id:
        return (name or feed_id, feed_id)
    if not name:
        raise ValueError("请指定公众号名称或 --feed-id（运行 --list 查看内置公众号）")
    accounts = load_accounts()
    if name in accounts:
        return (name, accounts[name])
    raise ValueError(f"未知公众号: {name!r}（运行 --list 查看内置公众号列表）")


def format_publish_time(ts) -> str:
    """Format a unix-seconds publish_time into local ``YYYY-MM-DD HH:MM``."""
    if ts is None or ts == "":
        return ""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ""


def print_articles(articles: List[dict]) -> None:
    """Print one line per article: ``[N] 标题  (发布: ...)  url``."""
    for i, art in enumerate(articles, 1):
        print(
            f"[{i}] {art.get('title', '')}  "
            f"(发布: {format_publish_time(art.get('publish_time', ''))})  "
            f"{art.get('url', '')}"
        )


def fetch_recent(
    name: str,
    feed_id: str,
    limit: int = 5,
    gather_content: bool = False,
    data_dir: str = _DEFAULT_DATA_DIR,
) -> List[dict]:
    """Fetch the most recent ``limit`` articles for one account.

    Returns a list of article dicts (same shape as the vendored core's
    ``wx.articles``).  Returns ``[]`` when not logged in.  Single HTTP call
    (``MaxPage=1``, ``interval=0``) — no browser unless ``gather_content``.
    """
    from src.we_mp_rss.core.wx.base import WxGather
    from src.we_mp_rss.driver.success import CanGetToken

    src.we_mp_rss.init(CollectorConfig(gather_content=gather_content), data_dir)

    if not CanGetToken():
        print("微信未登录或登录态已过期。")
        print("请先运行: uv run python wechat-collector/collector.py login")
        return []

    faker_id = faker_id_from_feed_id(feed_id)
    if not faker_id:
        print(f"无法从 feed_id 推导 faker_id: {feed_id!r}（仅用于测试的伪 feed 会被跳过）")
        return []

    # Same call chain as src/scrapers/wxmp.py:_fetch_feed_sync.
    wx = WxGather().Model("web")
    wx.get_Articles(
        faker_id=faker_id,
        Mps_id=feed_id,
        Mps_title=name,
        MaxPage=1,
        interval=0,
        Gather_Content=gather_content,
    )
    return (getattr(wx, "articles", []) or [])[:limit]


def login(data_dir: str = _DEFAULT_DATA_DIR, timeout: int = 120) -> int:
    """Scan the WeChat QR code to obtain a token (writes data_dir/wx.lic)."""
    from src.we_mp_rss.driver.success import CanGetToken, getLoginInfo
    from src.we_mp_rss.driver.wx_api import WeChat_api

    src.we_mp_rss.init(CollectorConfig(), data_dir)

    if CanGetToken():
        info = getLoginInfo() or {}
        expiry = info.get("expiry", {}) or {}
        print(f"已处于登录状态  到期时间: {expiry.get('expiry_time', '未知')}")
        return 0

    # Clean stale QR/lock files so wx_api's check_lock doesn't misjudge "running".
    for stale in ("wx_qrcode.png", "lock.lock"):
        p = os.path.join(data_dir, stale)
        if os.path.exists(p):
            os.remove(p)

    event = threading.Event()
    result: dict = {}

    def on_success(login_data: dict, account_info: dict) -> None:
        result["login_data"] = login_data
        result["account_info"] = account_info
        event.set()

    def on_notice(message: str = "") -> None:
        if message:
            print(f"… {message}")

    qr = WeChat_api.get_qr_code(on_success, on_notice)
    qr_path = getattr(WeChat_api, "qr_code_path", "")

    if not qr.get("is_exists") or not qr_path or not os.path.exists(qr_path):
        print(f"获取二维码失败: {qr.get('msg')}")
        print(f"若提示“登录脚本正在运行”，删除 {os.path.join(data_dir, 'wx_qrcode.png')} 后重试。")
        return 1

    print("请用微信扫一扫二维码登录（已保存到: %s）" % qr_path)
    try:
        subprocess.Popen(["open", qr_path])  # macOS: 自动打开二维码图片
    except Exception:
        pass

    print(f"等待扫码... (Ctrl+C 取消, 默认 {timeout} 秒超时)")
    try:
        if not event.wait(timeout=timeout):
            print("登录未完成（超时）。若纯 requests 扫码受限，请用 Horizon 的 "
                  "`uv run horizon-wxmp login` 或 Playwright 方式登录。")
            return 1
    except KeyboardInterrupt:
        print("已取消登录。")
        return 1

    login_data = result.get("login_data", {})
    expiry = login_data.get("expiry", {})
    account = result.get("account_info", {})
    wx_name = account.get("wx_app_name") if isinstance(account, dict) else None
    print(f"登录成功! 账号: {wx_name or '未知'}")
    print(f"  到期时间: {expiry.get('expiry_time')}")
    return 0


def status(data_dir: str = _DEFAULT_DATA_DIR) -> int:
    """Print login status (reuses the same token files as Horizon)."""
    from src.we_mp_rss.driver.success import CanGetToken, getLoginInfo

    src.we_mp_rss.init(CollectorConfig(), data_dir)

    if CanGetToken():
        info = getLoginInfo() or {}
        expiry = info.get("expiry", {}) or {}
        print(f"已登录  到期时间: {expiry.get('expiry_time', '未知')}")
        return 0
    print("未登录或 Token 已过期")
    print("运行 uv run python wechat-collector/collector.py login 扫码登录。")
    return 1


def list_accounts() -> None:
    """Print the built-in 公众号 list (name + feed_id + derived fakeid)."""
    accounts = load_accounts()
    for name, feed_id in accounts.items():
        print(f"{name}\t{feed_id}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="独立微信公众号 collector（最小 debug driver，复用内置 we-mp-rss 核心）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="扫码登录微信公众平台（写入 data/wxmp/wx.lic）")
    p_login.add_argument("--timeout", type=int, default=120, help="扫码超时秒数(默认 120)")
    p_login.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help="登录态存放目录")
    p_login.set_defaults(func=lambda a: login(data_dir=a.data_dir, timeout=a.timeout))

    p_status = sub.add_parser("status", help="查看登录状态")
    p_status.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help="登录态存放目录")
    p_status.set_defaults(func=lambda a: status(data_dir=a.data_dir))

    p_fetch = sub.add_parser(
        "fetch", help="抓取单个公众号最近几篇文章（默认不发浏览器）"
    )
    p_fetch.add_argument("name", nargs="?", help="公众号名称（见 accounts.json / --list）")
    p_fetch.add_argument("--feed-id", help="直接以 MP_WXS_ 开头的 feed_id 抓取")
    p_fetch.add_argument("--limit", type=int, default=5, help="返回最近几篇(默认 5)")
    p_fetch.add_argument("--content", action="store_true", help="抓取完整正文（需要 Playwright chromium）")
    p_fetch.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help="登录态存放目录")
    p_fetch.add_argument("--list", action="store_true", help="列出内置公众号")
    p_fetch.set_defaults(func=_cmd_fetch)

    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消。")
        return 1
    except ValueError as e:
        print(e)
        return 2


def _cmd_fetch(args: argparse.Namespace) -> int:
    if args.list:
        list_accounts()
        return 0

    try:
        name, feed_id = resolve_account(args.name, args.feed_id)
    except ValueError as e:
        print(e)
        return 2

    print(f"抓取公众号: {name} ({feed_id})  limit={args.limit}  content={args.content}")
    articles = fetch_recent(
        name,
        feed_id,
        limit=args.limit,
        gather_content=args.content,
        data_dir=args.data_dir,
    )
    if not articles:
        print("未获取到任何文章（可能未登录或公众号近期无发布）。")
        return 1
    print_articles(articles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
