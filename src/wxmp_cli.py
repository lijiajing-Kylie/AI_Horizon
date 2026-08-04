"""CLI for WeChat MP login / status / logout (bundled we-mp-rss core).

Provides Horizon's own entry point for scanning the WeChat QR code and
managing the login token — no external we-mp-rss web UI involved.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

import src.we_mp_rss
from src.storage.manager import ConfigError, StorageManager

console = Console()


def _load_wxmp_config():
    """Load the Horizon config and return the wxmp source config."""
    storage = StorageManager(data_dir=str(Path("data")))
    try:
        config = storage.load_config()
    except FileNotFoundError:
        console.print("[bold red]Configuration file not found![/bold red]")
        console.print(
            "Run [bold cyan]uv run horizon-wizard[/bold cyan] to set up your configuration."
        )
        sys.exit(1)
    except ConfigError as e:
        console.print(f"[bold red]Error loading configuration: {e}[/bold red]")
        sys.exit(1)

    wxmp = config.sources.wxmp
    if not wxmp:
        console.print("[yellow]wxmp source is not configured.[/yellow]")
        sys.exit(1)
    if not wxmp.enabled:
        console.print("[yellow]wxmp source is disabled in config.[/yellow]")
    return wxmp


def _render_qr_terminal(path: str) -> None:
    """Render the QR PNG as ASCII in the terminal (best-effort preview)."""
    try:
        from PIL import Image

        img = Image.open(path).convert("L")
        w, h = img.size
        target_w = 40
        new_w = min(w, target_w)
        new_h = max(1, int(h * (new_w / w)))
        img = img.resize((new_w, new_h))
        px = img.load()
        console.print()
        for y in range(new_h):
            row = "".join("██" if px[x, y] < 128 else "  " for x in range(new_w))
            console.print(row)
        console.print()
    except Exception as e:  # pragma: no cover - rendering is best-effort
        console.print(f"[dim](无法在终端渲染二维码: {e})[/dim]")


def _print_login_diagnostics(api, data_dir: str) -> None:
    """Print a diagnostic summary when the QR login did not complete."""
    from src.we_mp_rss.driver.success import getLoginInfo

    info = getLoginInfo() or {}
    token_ok = bool(info.get("token"))
    expiry = info.get("expiry", {}) or {}
    console.print("[red]登录未完成[/red] 诊断信息：")
    console.print(f"  • token 已保存: {'是' if token_ok else '否'}")
    console.print(
        f"  • wx_api.is_logged_in: {getattr(api, 'is_logged_in', False)}"
    )
    if isinstance(expiry, dict) and expiry.get("expiry_time"):
        console.print(f"  • 到期时间: {expiry.get('expiry_time')}")
    if not token_ok:
        console.print(
            "  • 可能原因: 微信接口对纯 requests 扫码登录有限制,扫码后未取到 token。\n"
            "    备选方案: 使用 Playwright 浏览器登录（见 README）,"
            "或检查网络/代理是否可访问 mp.weixin.qq.com。"
        )


def _cmd_login(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    data_dir = wxmp.data_dir
    src.we_mp_rss.init(wxmp, data_dir)

    from src.we_mp_rss.driver.success import CanGetToken
    from src.we_mp_rss.driver.wx_api import WeChat_api

    if CanGetToken():
        console.print("[yellow]已经处于登录状态。[/yellow]")
        if not args.force:
            console.print("如需重新登录,请运行 [cyan]horizon-wxmp login --force[/cyan]")
            return 0

    # 清理上一次残留的二维码/锁文件,避免 wx_api 的 check_lock 误判"正在运行"
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
            console.print(f"[cyan]… {message}[/cyan]")

    qr = WeChat_api.get_qr_code(on_success, on_notice)
    qr_path = getattr(WeChat_api, "qr_code_path", "")

    if not qr.get("is_exists") or not qr_path or not os.path.exists(qr_path):
        console.print(f"[bold red]获取二维码失败: {qr.get('msg')}[/bold red]")
        console.print(
            "若提示“登录脚本正在运行”，删除 [cyan]data/wxmp/wx_qrcode.png[/cyan] 后重试。"
        )
        return 1

    console.print(
        Panel(
            f"[bold]请用微信扫一扫下方二维码登录[/bold]\n\n二维码图片: {qr_path}\n"
            f"已尝试自动打开图片,若未打开请手动打开该文件扫描。",
            title="微信公众平台扫码登录",
            border_style="blue",
        )
    )
    _render_qr_terminal(qr_path)
    try:
        import subprocess

        subprocess.Popen(["open", qr_path])  # macOS
    except Exception:
        pass

    console.print("\n[cyan]等待扫码... (Ctrl+C 取消, 默认 120 秒超时)[/cyan]")
    try:
        if not event.wait(timeout=args.timeout):
            _print_login_diagnostics(WeChat_api, data_dir)
            return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消登录。[/yellow]")
        return 1

    login_data = result.get("login_data", {})
    expiry = login_data.get("expiry", {})
    account = result.get("account_info", {})
    wx_name = account.get("wx_app_name") if isinstance(account, dict) else None
    console.print(f"[green]登录成功![/green] 账号: {wx_name or '未知'}")
    console.print(f"  到期时间: {expiry.get('expiry_time')}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    data_dir = wxmp.data_dir
    src.we_mp_rss.init(wxmp, data_dir)

    from src.we_mp_rss.driver.success import CanGetToken, getLoginInfo

    if CanGetToken():
        info = getLoginInfo() or {}
        expiry = info.get("expiry", {}) or {}
        console.print(f"[green]已登录[/green]  到期时间: {expiry.get('expiry_time', '未知')}")
        return 0
    console.print("[red]未登录或 Token 已过期[/red]")
    console.print("运行 [cyan]horizon-wxmp login[/cyan] 扫码登录。")
    return 1


def _cmd_logout(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    data_dir = wxmp.data_dir
    src.we_mp_rss.init(wxmp, data_dir)

    from src.we_mp_rss.driver.success import setStatus

    setStatus(False)
    removed = []
    for name in ("wx.lic", "key.lic"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            os.remove(p)
            removed.append(p)
    if removed:
        console.print(f"[green]已登出,已清除: {', '.join(removed)}[/green]")
    else:
        console.print("[yellow]未找到登录态文件(可能本就未登录)。[/yellow]")
    return 0


def main() -> None:
    """CLI entry point for horizon-wxmp."""
    parser = argparse.ArgumentParser(
        description="WeChat MP (公众号) 登录态管理 — 内置 we-mp-rss 核心",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="扫码登录微信公众平台")
    p_login.add_argument("--force", action="store_true", help="忽略已登录状态,强制重新登录")
    p_login.add_argument("--timeout", type=int, default=120, help="扫码超时秒数(默认 120)")
    p_login.set_defaults(func=_cmd_login)

    p_status = sub.add_parser("status", help="查看登录状态")
    p_status.set_defaults(func=_cmd_status)

    p_logout = sub.add_parser("logout", help="清除登录态")
    p_logout.set_defaults(func=_cmd_logout)

    args = parser.parse_args()

    try:
        load_dotenv()
        sys.exit(args.func(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
