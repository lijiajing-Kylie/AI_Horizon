"""A/B 实验：appmsgpublish（当前 web 模式） vs free_publish（新版多端点）。

纯增量诊断脚本，**不修改** Horizon 主流程，也不修改 wechat-collector/collector.py。
复用同一个登录态（data/wxmp/wx.lic + key.lic），直接驱动内置 src.we_mp_rss 核心。

做的事情：
  1. 对 free_publish / publish / appmsgpublish / appmsg 四个端点各发 1 次列表请求，
     输出  endpoint / HTTP状态 / 微信 base_resp.ret / 文章数量（诊断表）。
  2. 直接实例化 MpsFreePublish 跑真实抓取（自动探测可用端点 → 翻页采集），
     输出 GitHubDaily 最近 N 篇。

用法（repo 根目录）:
    uv run python wechat-collector/ab_test_free_publish.py
    uv run python wechat-collector/ab_test_free_publish.py --limit 5
    uv run python wechat-collector/ab_test_free_publish.py --feed-id MP_WXS_3073282833

退出码: 0 = free_publish 链路抓到 >=1 篇；1 = 未登录 / 所有端点均失败。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

# Make repo root importable (same trick as collector.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.we_mp_rss  # noqa: E402  (bootstrap first)

_FEATURED_FEED_ID = "MP_WXS_FEATURED_ARTICLES"
_DEFAULT_DATA_DIR = "data/wxmp"

# 默认实验对象：GitHubDaily（data/config.py 中的 feed_id）
_DEFAULT_FEED_ID = "MP_WXS_3019715205"
_DEFAULT_NAME = "GitHubDaily"


class _ProbeConfig:
    """和 CollectorConfig 同款的最小配置（gather_content=False，不发浏览器）。"""

    gather_content: bool = False
    clean_html: bool = False
    proxy: Optional[str] = None
    max_page: int = 1
    gather_interval: int = 0


def faker_id_from_feed_id(feed_id: str) -> Optional[str]:
    if not feed_id or feed_id == _FEATURED_FEED_ID:
        return None
    try:
        return base64.b64encode(feed_id.removeprefix("MP_WXS_").encode()).decode()
    except Exception:
        return None


def _count_articles(fetcher, msg: dict, endpoint: dict) -> int:
    """用 MpsFreePublish 自己的解析器统计该端点响应中的文章数。"""
    try:
        parser = endpoint.get("item_parser", "")
        list_key = endpoint.get("list_key")
        return len(fetcher._parse_response(msg, list_key, parser))
    except Exception:
        return -1


def probe_endpoints(fetcher, faker_id: str, pause: float = 1.5) -> List[dict]:
    """对四个端点各发一次列表请求，返回诊断行。

    请求方式与 MpsFreePublish.get_Articles 内部探测完全一致
    （session + fix_header + verify=False），只是把响应记录下来而非静默跳过。
    """
    rows = []
    _raw_base: dict = {}  # name -> 微信完整 base_resp（原始响应证据）
    for ep in fetcher.ENDPOINTS:
        name = ep["name"]
        url = ep["url"]
        params = {**ep["params"], "begin": 0, "fakeid": faker_id, "token": fetcher.token}
        try:
            headers = fetcher.fix_header(url)
            resp = fetcher.session.get(
                url, headers=headers, params=params, verify=False, timeout=15
            )
            status = resp.status_code
            try:
                msg = resp.json()
                base = msg.get("base_resp", {}) if isinstance(msg, dict) else {}
                ret = base.get("ret", -1)
                err = base.get("err_msg", "")
                n = _count_articles(fetcher, msg, ep) if status == 200 else -1
                # 保存完整 base_resp，便于确认微信原始响应（freq control 细节）
                _raw_base[name] = base
            except Exception:
                # 非 JSON（如 HTML 验证页）→ 记为 non-json
                ret, err, n = "non-json", resp.text[:80], -1
            rows.append(
                {"endpoint": name, "status": status, "ret": ret, "err": err, "count": n}
            )
            print(
                f"[probe] {name:<16} HTTP {status:<4} ret={ret:<6} "
                f"err={err[:50] if err else '-'}  文章数={n}"
            )
        except Exception as exc:
            rows.append(
                {"endpoint": name, "status": "ERR", "ret": "-", "err": str(exc)[:60], "count": -1}
            )
            print(f"[probe] {name:<16} 请求异常: {exc}")
        time.sleep(pause)  # 探测本身也要留间隔，避免把频控当结论

    # 打印微信原始响应（base_resp 全文）作为证据
    if _raw_base:
        print("\n[raw] 微信 base_resp 原始响应：")
        for name, base in _raw_base.items():
            print(f"  {name:<16} -> {json.dumps(base, ensure_ascii=False)}")
    return rows


def run(name: str, feed_id: str, limit: int, data_dir: str) -> int:
    from src.we_mp_rss.core.wx.base import WxGather
    from src.we_mp_rss.core.wx.model.free_publish import MpsFreePublish
    from src.we_mp_rss.driver.success import CanGetToken

    src.we_mp_rss.init(_ProbeConfig(), data_dir)

    if not CanGetToken():
        print("微信未登录或登录态已过期。")
        print("请先运行: uv run python wechat-collector/collector.py login")
        return 1

    faker_id = faker_id_from_feed_id(feed_id)
    if not faker_id:
        print(f"无法从 feed_id 推导 faker_id: {feed_id!r}")
        return 1

    print(f"登录态有效。目标公众号: {name} ({feed_id})  fakeid={faker_id}\n")

    # 直接实例化 MpsFreePublish（不经过 Model('web') 工厂）
    fp = MpsFreePublish()

    print("═══ 端点探测（各 1 次请求） ═══")
    rows = probe_endpoints(fp, faker_id)

    print("\n═══ 真实抓取：MpsFreePublish.get_Articles() ═══")
    # get_Articles 内部会重新探测并选择第一个可用端点，然后翻页采集
    fp.get_Articles(
        faker_id=faker_id,
        Mps_id=feed_id,
        Mps_title=name,
        CallBack=lambda art: True,
        MaxPage=1,
        interval=2,
        Gather_Content=False,
    )
    articles = (getattr(fp, "articles", []) or [])[:limit]

    if not articles:
        print("FAIL: free_publish 链路未抓到任何文章。")
        for r in rows:
            print(f"  - {r['endpoint']}: HTTP {r['status']} ret={r['ret']} count={r['count']}")
        return 1

    print(f"成功抓到 {len(articles)} 篇（不足 {limit} 篇属正常）：")
    for i, art in enumerate(articles, 1):
        from datetime import datetime

        ts = art.get("publish_time", "")
        t = ""
        if ts:
            try:
                t = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError, OSError):
                pass
        print(f"  [{i}] {art.get('title', '')}  (发布: {t})  {art.get('url', '')}")

    print("\n结论: free_publish 链路可用 → 下一步把 vendor 的 gather.model 恢复为 "
          "free_publish / auto 路由（而非固定 web）。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A/B: appmsgpublish(web) vs free_publish 多端点。默认抓 GitHubDaily 最近5篇。",
    )
    parser.add_argument("name", nargs="?", default=_DEFAULT_NAME, help="公众号名称")
    parser.add_argument("--feed-id", default=_DEFAULT_FEED_ID, help="MP_WXS_ 开头的 feed_id")
    parser.add_argument("--limit", type=int, default=5, help="返回最近几篇(默认 5)")
    parser.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help="登录态存放目录")
    args = parser.parse_args()
    return run(args.name, args.feed_id, args.limit, args.data_dir)


if __name__ == "__main__":
    sys.exit(main())
