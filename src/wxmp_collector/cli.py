"""horizon-wxmp-collector CLI:常驻采集 / once / status / reset-news / prune。

用法:
    horizon-wxmp-collector                        # 常驻(每号随机 4-8h 间隔)
    horizon-wxmp-collector once                   # 单轮全量后退出(手动/CI 补数据)
    horizon-wxmp-collector status                 # 每号 next_run_at/上次同步/中间表计数
    horizon-wxmp-collector reset-news --run-date 2026-08-16   # 清某天新闻消费标记
    horizon-wxmp-collector prune --retention-days 60          # 清理已消费且过期的行
    horizon-wxmp-collector backfill-img-proxy                 # 存量图片代理地址改写为 weserv

可迁移:打包发给别人,uv sync + 扫码登录 + 一条命令即可采集,不依赖 crontab/
systemd/GitHub Actions。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..logging_config import silence_http_loggers
from ..scrapers.wxmp import LEGACY_IMG_PROXY_PREFIX, WESERV_IMG_PROXY_BASE
from ..storage.db import HorizonDB, _dt_iso
from ..storage.manager import ConfigError, StorageManager
from ..we_read.errors import WeReadAuthError
from ..we_read.state import WeReadSyncState
from .daemon import run_daemon

logger = logging.getLogger(__name__)
console = Console()


def _build_parser() -> argparse.ArgumentParser:
    # 公共参数(分钟为单位的间隔 / 保留期 / 窗口 / 库路径):顶层与子命令都挂,
    # 这样 `--interval-min 120 once` 与 `once --interval-min 120` 都能解析。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--interval-min", type=int, default=240,
                        help="单号最小抓取间隔(分钟),默认 240(4h)")
    common.add_argument("--interval-max", type=int, default=480,
                        help="单号最大抓取间隔(分钟),默认 480(8h)")
    common.add_argument("--max-age-days", type=int, default=None,
                        help="可选:只入库最近 N 天发布的文章(默认不限)")
    common.add_argument("--retention-days", type=int, default=60,
                        help="中间表清理保留期(天),默认 60")
    common.add_argument("--db", default="data/horizon.db",
                        help="SQLite 库路径,默认 data/horizon.db")

    parser = argparse.ArgumentParser(
        prog="horizon-wxmp-collector",
        description="微信抓取独立采集 daemon(常驻;按公众号随机 4-8h 间隔落中间表)",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("once", parents=[common],
                   help="单轮抓取全部公众号后退出(手动补抓/CI)")
    sub.add_parser("status", parents=[common],
                   help="查看每号下次计划/上次同步/中间表计数")

    reset = sub.add_parser("reset-news", parents=[common],
                           help="清掉某天日报的新闻消费标记(崩溃后重跑恢复)")
    reset.add_argument("--run-date", required=True,
                       help="要清除消费标记的 run_date(YYYY-MM-DD)")

    sub.add_parser("prune", parents=[common],
                   help="清理已过保留期且被两条管道都消费过的中间表行")
    sub.add_parser("backfill-img-proxy", parents=[common],
                   help="存量 display_html 里的旧 /api/img-proxy 图片地址改写为 weserv 代理")
    return parser


def _load_config():
    storage = StorageManager(data_dir="data")
    return storage.load_config()


async def _run_simple(args) -> None:
    """reset-news / prune / backfill-img-proxy 不需要完整 config,直接操作库。"""
    db = HorizonDB(args.db)
    if args.command == "reset-news":
        n = db.reset_wxmp_articles_news_consumption(args.run_date)
        console.print(f"[green]已清掉 {n} 篇文章的 {args.run_date} 新闻消费标记[/green]")
    elif args.command == "prune":
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
        n = db.prune_wxmp_articles(_dt_iso(cutoff))
        console.print(f"[green]清理 {n} 条已消费且过期的中间表文章(保留 {args.retention_days} 天)[/green]")
    elif args.command == "backfill-img-proxy":
        counts = db.rewrite_wechat_img_proxy(LEGACY_IMG_PROXY_PREFIX, WESERV_IMG_PROXY_BASE)
        detail = " / ".join(f"{t} {n} 行" for t, n in counts.items())
        console.print(f"[green]图片代理地址已改写为 weserv:{detail}(共 {sum(counts.values())} 行)[/green]")


async def _cmd_status(args, config) -> None:
    state = WeReadSyncState()
    db = HorizonDB(args.db)
    feeds = [f for f in config.sources.wxmp.feeds if f.enabled and f.weread_mp_id]
    counts: dict[str, int] = {}
    for r in db.conn.execute(
        "SELECT weread_mp_id, COUNT(*) AS cnt FROM wxmp_articles GROUP BY weread_mp_id"
    ).fetchall():
        counts[r["weread_mp_id"]] = r["cnt"]

    console.print("[bold]微信抓取 collector 状态[/bold]")
    if not feeds:
        console.print("[yellow]无启用的公众号(weread_mp_id)。先 `horizon-wxmp subscribe` 订阅。[/yellow]")
        return
    now = int(time.time())
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("公众号")
    table.add_column("上次同步", style="dim")
    table.add_column("下次计划")
    table.add_column("中间表", justify="right")
    for f in feeds:
        mp = f.weread_mp_id
        last = state.feed_last_sync(mp)
        nxt = state.feed_next_run(mp)
        last_s = (
            datetime.fromtimestamp(last, tz=timezone.utc).strftime("%m-%d %H:%M")
            if last else "-"
        )
        nxt_s = (
            datetime.fromtimestamp(nxt, tz=timezone.utc).strftime("%m-%d %H:%M")
            if nxt else "-"
        )
        due = "⏰" if (nxt is not None and nxt <= now) else ""
        table.add_row(f.name, last_s, f"{nxt_s} {due}", str(counts.get(mp, 0)))
    console.print(table)


async def _cmd_daemon(args, config) -> None:
    if not config.sources.wxmp or not config.sources.wxmp.enabled:
        console.print("[yellow]sources.wxmp 未启用或不存在,collector 无事可做。[/yellow]")
        return
    feeds = [f for f in config.sources.wxmp.feeds if f.enabled and f.weread_mp_id]
    if not feeds:
        console.print("[yellow]没有启用的公众号(weread_mp_id)。先 `horizon-wxmp subscribe` 订阅。[/yellow]")
        return
    once = args.command == "once"
    console.print(
        f"[dim]微信抓取 collector {'once(单轮)' if once else '常驻'}: "
        f"{len(feeds)} 个公众号,间隔 {args.interval_min}-{args.interval_max} 分钟"
        f"(登录失效自动等待扫码恢复)[/dim]"
    )
    try:
        await run_daemon(
            config,
            interval=(args.interval_min * 60, args.interval_max * 60),
            max_age_days=args.max_age_days,
            retention_days=args.retention_days,
            once=once,
            db_path=args.db,
        )
    except WeReadAuthError:
        # 仅当等待重登超过 auth_max_wait_sec(默认不限)仍未恢复时触发。
        # 退出码 3 区别于普通崩溃(exit 1),供部署层识别「需人工重登」。
        console.print(
            "[bold red]微信读书登录失效且等待重登超时,collector 已停止。\n"
            "运行 `uv run horizon-wxmp login` 重新扫码后再启动。[/bold red]"
        )
        raise SystemExit(3) from None


def main() -> None:
    silence_http_loggers()
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command in ("reset-news", "prune", "backfill-img-proxy"):
            asyncio.run(_run_simple(args))
            return

        config = _load_config()
        if args.command == "status":
            asyncio.run(_cmd_status(args, config))
        else:  # None(常驻)或 once
            asyncio.run(_cmd_daemon(args, config))
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  collector 已停止[/yellow]")
        sys.exit(0)
    except Exception as e:  # noqa: BLE001 — CLI 顶层兜底
        console.print(f"[bold red]❌ collector 异常退出: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
