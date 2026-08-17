"""CLI for WeChat MP login / status / subscribe / migrate via the WeRead channel.

Provides Horizon's own entry point for scanning the WeRead QR code, managing
the login token, subscribing accounts from share links, and bulk-migrating the
feed list — no external we-mp-rss web UI, no Playwright.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from src.config.pyconfig_editor import (
    ConfigEditError,
    set_wxmp_enabled,
    update_wxmp_feed,
)
from src.storage.manager import ConfigError, StorageManager
from src.we_read import WeReadSyncState, build_client_from_wxmp_config
from src.we_read.errors import WeReadError
from src.we_read.login import WeReadLoginFlow

console = Console()

CONFIG_PATH = Path("data/config.py")


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
    return wxmp


def _require_login(client) -> bool:
    """Print guidance and return False when no WeRead token is stored."""
    if client.store.is_present():
        return True
    console.print("[red]微信读书未登录。[/red] 先运行 [cyan]horizon-wxmp login[/cyan] 扫码。")
    return False


# ── login ────────────────────────────────────────────────────────────────────
def _cmd_login(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    client = build_client_from_wxmp_config(wxmp)

    if client.store.is_present() and not args.force:
        console.print("[yellow]已经处于登录状态。[/yellow]")
        console.print("如需重新登录，请运行 [cyan]horizon-wxmp login --force[/cyan]")
        return 0

    async def _run():
        flow = WeReadLoginFlow(client)
        console.print(
            Panel(
                "[bold]请用手机微信扫一扫下方二维码登录微信读书[/bold]\n\n"
                "二维码图片会自动打开；如未打开，请手动打开 data/auth/weread_qrcode.png 扫描。",
                title="微信读书扫码登录",
                border_style="blue",
            )
        )
        session = await flow.run(timeout=args.timeout, print_fn=console.print)
        return session

    try:
        session = asyncio.run(_run())
    except WeReadError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 1
    console.print(f"[green]登录成功![/green] 账号: {session.username or session.vid}")
    return 0


# ── status ───────────────────────────────────────────────────────────────────
def _cmd_status(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    client = build_client_from_wxmp_config(wxmp)
    store = client.store
    state = WeReadSyncState()

    if not store.is_present():
        console.print("[red]未登录[/red]")
        console.print("运行 [cyan]horizon-wxmp login[/cyan] 扫码登录微信读书。")
        return 1

    valid = asyncio.run(client.validate_token())
    subscribed = sum(1 for f in (wxmp.feeds or []) if f.weread_mp_id)
    username = store.get("username")
    age = store.age_seconds()
    max_age_days = wxmp.weread.token_max_age_days

    console.print(f"{'✓' if valid else '✗'} 登录状态: {'已登录' if valid else 'Token 已失效（请重新 login）'}")
    if username:
        console.print(f"  账号: {username}")
    if age is not None:
        days = age / 86400
        console.print(f"  last_success: {days:.1f} 天前")
        if days > max_age_days:
            console.print(f"[yellow]  提醒: 已超过 {max_age_days} 天未成功调用，建议重新扫码（不强制）[/yellow]")
    console.print(f"  已订阅公众号数量（weread_mp_id）: {subscribed}")
    last_sync = state.last_sync_at()
    if last_sync:
        import datetime as _dt

        console.print(
            f"  最后同步时间: {_dt.datetime.fromtimestamp(last_sync).strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        console.print("  最后同步时间: (尚无)")
    return 0 if valid else 1


# ── logout ───────────────────────────────────────────────────────────────────
def _cmd_logout(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    client = build_client_from_wxmp_config(wxmp)
    client.store.clear()
    state = WeReadSyncState()
    if state.path.exists():
        state.path.unlink()
    console.print("[green]已登出，已清除 data/auth/weread.json 与同步状态。[/green]")
    return 0


# ── subscribe ────────────────────────────────────────────────────────────────
def _cmd_subscribe(args: argparse.Namespace) -> int:
    wxmp = _load_wxmp_config()
    client = build_client_from_wxmp_config(wxmp)
    if not _require_login(client):
        return 1

    async def _run():
        return await client.resolve_share(args.link)

    try:
        infos = asyncio.run(_run())
    except WeReadError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 1
    if not infos:
        console.print(
            "[red]无法解析该分享链接（可能不是公众号文章，或微信读书未收录该公众号）[/red]"
        )
        return 1

    if args.name:
        pick = next((i for i in infos if i.name == args.name), None) or infos[0]
    else:
        pick = infos[0]
    console.print(f"[bold]{pick.name}[/bold]  mpId: {pick.id}")
    if pick.intro:
        console.print(f"  简介: {pick.intro[:60]}{'…' if len(pick.intro) > 60 else ''}")

    if not args.write:
        console.print("[dim]dry-run，加 --write 才写入配置。[/dim]")
        return 0

    try:
        update_wxmp_feed(
            CONFIG_PATH,
            name=pick.name,
            weread_mp_id=pick.id,
            category=args.category,
        )
        if args.enable:
            set_wxmp_enabled(CONFIG_PATH, True)
    except ConfigEditError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 1
    console.print(f"[green]已写入配置: {pick.name} → {pick.id}[/green]")
    return 0


# ── migrate ──────────────────────────────────────────────────────────────────
def _cmd_migrate(args: argparse.Namespace) -> int:
    links_file = Path(args.links_file)
    if not links_file.exists():
        console.print(f"[bold red]清单文件不存在: {links_file}[/bold red]")
        return 1
    links = [ln.strip() for ln in links_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not links:
        console.print("[yellow]清单文件为空。[/yellow]")
        return 1

    wxmp = _load_wxmp_config()
    client = build_client_from_wxmp_config(wxmp)
    if not _require_login(client):
        return 1

    async def _run():
        results = []
        for link in links:
            console.print(f"[dim]解析: {link[:70]}…[/dim]")
            try:
                infos = await client.resolve_share(link)
            except WeReadError as exc:
                results.append({"link": link, "error": str(exc)})
                continue
            if not infos:
                results.append({"link": link, "error": "微信读书未收录/解析失败"})
                continue
            results.append(
                {"name": infos[0].name, "mp_id": infos[0].id, "link": link}
            )
        return results

    try:
        results = asyncio.run(_run())
    except WeReadError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 1

    ok = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    console.print(f"\n解析完成: {len(ok)} 成功, {len(failed)} 失败")
    for r in ok:
        console.print(f"  [green]✓[/green] {r['name']} → {r['mp_id']}")
    for r in failed:
        console.print(f"  [red]✗[/red] {r.get('error')} ({r['link'][:50]})")

    if not args.write:
        console.print("[dim]dry-run，加 --write 才写入配置。[/dim]")
        return 0 if not failed else 2
    if not args.yes:
        resp = input(f"确认写入 {len(ok)} 个公众号到 {CONFIG_PATH}? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            console.print("[yellow]已取消。[/yellow]")
            return 0

    written = 0
    for r in ok:
        try:
            update_wxmp_feed(CONFIG_PATH, name=r["name"], weread_mp_id=r["mp_id"])
            written += 1
        except ConfigEditError as exc:
            console.print(f"[red]写入 {r['name']} 失败: {exc}[/red]")
    if args.enable:
        set_wxmp_enabled(CONFIG_PATH, True)
    console.print(f"[green]已写入 {written}/{len(ok)} 个公众号。[/green]")
    return 0 if written else 2


def main() -> None:
    """CLI entry point for horizon-wxmp."""
    parser = argparse.ArgumentParser(
        description="WeChat MP (公众号) 登录/订阅管理 — 微信读书通道",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="扫码登录微信读书")
    p_login.add_argument("--force", action="store_true", help="忽略已登录状态，强制重新登录")
    p_login.add_argument("--timeout", type=int, default=120, help="扫码超时秒数(默认 120)")
    p_login.set_defaults(func=_cmd_login)

    p_status = sub.add_parser("status", help="查看登录状态/订阅数/最后同步")
    p_status.set_defaults(func=_cmd_status)

    p_logout = sub.add_parser("logout", help="清除登录态")
    p_logout.set_defaults(func=_cmd_logout)

    p_sub = sub.add_parser("subscribe", help="用公众号文章分享链接订阅")
    p_sub.add_argument("link", help="公众号文章分享链接（mp.weixin.qq.com/s/...）")
    p_sub.add_argument("--name", default=None, help="指定公众号名（多结果时精确匹配）")
    p_sub.add_argument("--category", default=None, help="分类标签")
    p_sub.add_argument("--write", action="store_true", help="写入 data/config.py")
    p_sub.add_argument("--enable", action="store_true", help="同时置 wxmp.enabled=True")
    p_sub.set_defaults(func=_cmd_subscribe)

    p_mig = sub.add_parser("migrate", help="批量迁移公众号（每行一个分享链接）")
    p_mig.add_argument("links_file", help="分享链接清单文件，每行一个")
    p_mig.add_argument("--dry-run", dest="write", action="store_false", help="只解析不写入")
    p_mig.add_argument("--write", dest="write", action="store_true", help="写入 data/config.py")
    p_mig.add_argument("--yes", action="store_true", help="跳过确认")
    p_mig.add_argument("--enable", action="store_true", help="同时置 wxmp.enabled=True")
    p_mig.set_defaults(write=False)
    p_mig.set_defaults(func=_cmd_migrate)

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
