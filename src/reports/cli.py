"""CLI entry point for fetching and storing the research-reports library.

Standalone from the news pipeline: never touches HorizonOrchestrator,
ContentAnalyzer, or ContentEnricher. Run on its own schedule (e.g. a
separate cron), independent of ``horizon``/``horizon-papers``.

Sub-commands
------------
(no subcommand)  — fetch from configured sources and persist (original behaviour)
backfill-pdfs    — download PDFs for reports already in the database
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console

from ..ai.client import create_ai_client
from ..models import Config
from ..storage.db import HorizonDB
from ..storage.manager import ConfigError, StorageManager
from .fetcher import fetch_all_reports
from .models import Report
from .pdf_downloader import download_report_pdfs

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)
console = Console()


# ────────────────────────────────────────────────────────────
# Fetch (default subcommand)
# ────────────────────────────────────────────────────────────


async def run(config: Config) -> int:
    """Fetch configured report sources and persist results. Returns count saved."""
    if not config.reports or not config.reports.enabled:
        console.print("[yellow]Reports library not enabled in config; nothing to do.[/yellow]")
        return 0

    # Create AI client if filtering is enabled
    ai_client = None
    if config.reports.ai_filter_enabled:
        ai_client = create_ai_client(config.ai)
        console.print("[dim]AI filter enabled — non-tech reports will be skipped.[/dim]")

    async with httpx.AsyncClient() as client:
        reports = await fetch_all_reports(config.reports, client, ai_client=ai_client)

    # Fallback: uncategorized reports → "其他"
    for r in reports:
        if not r.categories:
            r.categories = ["其他"]

    db = HorizonDB()
    count = db.save_reports(reports)

    # ── PDF download summary ──
    total_pdfs = 0
    local_pdfs = 0
    for r in reports:
        for entry in r.pdf_urls:
            total_pdfs += 1
            if entry.get("local_path"):
                local_pdfs += 1
    if total_pdfs:
        console.print(
            f"[green]Saved {count} reports.[/green] "
            f"[dim]PDFs: {local_pdfs}/{total_pdfs} 已下载到本地[/dim]"
        )
        if local_pdfs < total_pdfs:
            console.print(
                "[dim]（有 PDF 下载失败，前端会自动回退到远程 URL）[/dim]"
            )
    else:
        console.print(f"[green]Saved {count} reports.[/green] [dim]（本次没有 PDF 链接）[/dim]")

    return count


# ────────────────────────────────────────────────────────────
# Backfill PDFs subcommand
# ────────────────────────────────────────────────────────────


async def backfill_pdfs(
    config: Config,
    source: str | None = None,
    limit: int = 0,
) -> int:
    """Download PDFs for existing reports that lack local copies.

    Two strategies are attempted in order:

    1. **HTTP download** — for ``pdf_urls`` entries that look like real PDF
       links (``.pdf`` suffix, no ``type="reader"`` marker), tries a direct
       ``httpx`` GET via ``download_report_pdfs()``.

    2. **Playwright download** — for entries that are web-reader pages
       (``type="reader"`` or non-``.pdf`` URLs), opens the URL in a headless
       browser and attempts to click a download button.  Currently supports
       ``fxbaogao`` reader pages.
    """
    if not config.reports or not config.reports.enabled:
        console.print("[yellow]Reports library not enabled; nothing to do.[/yellow]")
        return 0

    db = HorizonDB()
    result = db.get_reports(
        source=source or None,
        per_page=9999,
        sort="fetched_at",
        order="desc",
    )
    reports_dicts: list[dict] = result["items"]
    console.print(f"[dim]Found {len(reports_dicts)} reports in the database.[/dim]")

    # ── Categorise reports ──────────────────────────────────────────────
    http_reports: list[dict] = []    # has real PDF-looking URLs
    playwright_reports: list[dict] = []  # has only reader / non-PDF URLs

    for r in reports_dicts:
        pdfs: list[dict] = r.get("pdf_urls") or []
        has_local = False
        has_pdf_url = False
        has_reader = False
        for entry in pdfs:
            if entry.get("local_path"):
                has_local = True
                continue
            url = entry.get("url") or ""
            if entry.get("type") == "reader":
                has_reader = True
            elif __import__("re").search(r'\.pdf([?#]|$)', url):
                has_pdf_url = True
            else:
                has_reader = True  # non-.pdf URL ≈ reader
        if has_local:
            continue  # all PDFs already local
        if has_pdf_url:
            http_reports.append(r)
        elif has_reader:
            playwright_reports.append(r)

    if limit > 0:
        http_reports = http_reports[:limit]
        remaining = limit - len(http_reports)
        if remaining > 0:
            playwright_reports = playwright_reports[:remaining]
        else:
            playwright_reports = []

    total = len(http_reports) + len(playwright_reports)
    if not total:
        console.print("[green]All existing reports already have local PDFs.[/green]")
        return 0

    if http_reports:
        console.print(f"[dim]{len(http_reports)} reports with real PDF links[/dim]")
    if playwright_reports:
        console.print(
            f"[dim]{len(playwright_reports)} reports with reader links "
            f"({'(Playwright required)' if not _PLAYWRIGHT_AVAILABLE else 'will try Playwright'})[/dim]"
        )

    # ── Strategy 1: HTTP download ──────────────────────────────────────
    processed = 0
    if http_reports:
        async with httpx.AsyncClient() as client:
            for i, report_dict in enumerate(http_reports):
                report = Report(**report_dict)
                try:
                    updated = await download_report_pdfs(report, config.reports, client)
                except Exception as exc:
                    logger.warning("HTTP backfill failed for %s: %s", report.id, exc)
                    continue
                has_new = any("local_path" in e for e in (updated.pdf_urls or []))
                if has_new:
                    db.save_reports([updated])
                    processed += 1
                if (i + 1) % 25 == 0:
                    console.print(
                        f"[dim]… HTTP {i+1}/{len(http_reports)} ({processed} new PDFs)[/dim]"
                    )
                await asyncio.sleep(0.1)

    # ── Strategy 2: Playwright download ─────────────────────────────────
    if playwright_reports and _PLAYWRIGHT_AVAILABLE:
        console.print("[dim]Starting Playwright browser for reader-page download…[/dim]")
        _CHROME_PATH = (
            "/Users/kylie/Library/Caches/ms-playwright/chromium-1223/"
            "chrome-mac-arm64/Google Chrome for Testing.app/"
            "Contents/MacOS/Google Chrome for Testing"
        )
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            executable_path=_CHROME_PATH,
        )

        try:
            for i, report_dict in enumerate(playwright_reports):
                report_id = report_dict["id"]
                source_name = report_dict.get("source", "")
                native_id = report_dict.get("native_id", "")
                pdf_urls: list[dict] = report_dict.get("pdf_urls") or []

                # Pick the first reader URL.
                reader_url = next(
                    (e["url"] for e in pdf_urls if e.get("type") == "reader"),
                    pdf_urls[0]["url"] if pdf_urls else None,
                )
                if not reader_url:
                    continue

                # ── Open reader page and try to download ──
                page = await browser.new_page()
                try:
                    await page.goto(reader_url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(3000)

                    # Look for download buttons.
                    dl_entry = await _click_download_button(page, source_name, native_id)
                    if dl_entry:
                        # Remove old reader entry and add the downloaded one.
                        remaining = [e for e in pdf_urls if e.get("url") != reader_url]
                        remaining.append(dl_entry)
                        report_dict["pdf_urls"] = remaining
                        db.save_reports([Report(**report_dict)])
                        processed += 1
                        console.print(
                            f"  [green]✓[/green] {native_id}: PDF downloaded via Playwright"
                        )
                    else:
                        logger.debug("No download button found for %s", reader_url)
                except Exception as exc:
                    logger.warning("Playwright backfill failed for %s: %s", reader_url, exc)
                finally:
                    await page.close()

                await asyncio.sleep(0.5)

        finally:
            await browser.close()
            await pw.stop()

    elif playwright_reports and not _PLAYWRIGHT_AVAILABLE:
        console.print(
            "[yellow]Playwright not available. "
            "Install with: uv sync --extra twitter[/yellow]"
        )

    if processed:
        console.print(f"[green]Downloaded PDFs for {processed} reports total.[/green]")
    else:
        console.print("[yellow]No new PDFs were downloaded.[/yellow]")
    return processed


# ────────────────────────────────────────────────────────────
# Playwright helper for backfill
# ────────────────────────────────────────────────────────────


async def _click_download_button(page, source: str, native_id: str) -> Optional[dict]:
    """Try various selectors to find and click a download button on *page*.

    Returns a ``{name, url, type, local_path}`` dict on success, ``None``
    if no button is found.
    """
    from .pdf import sanitize_filename

    output_dir = Path("data/reports_pdfs") / source / native_id
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(native_id)
    output_path = output_dir / f"{safe_name}.pdf"

    if output_path.exists():
        return {
            "name": native_id,
            "url": page.url,
            "type": "pdf",
            "local_path": f"/api/reports/pdfs/{source}/{native_id}/{safe_name}.pdf",
        }

    selectors = [
        'button:has-text("下载报告")',
        'button:has-text("下载")',
        'button:has-text("免费下载")',
        'a:has-text("下载报告")',
        'a:has-text("下载")',
        '[class*="download"] button',
        '[class*="down"] a',
    ]

    for selector in selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2000):
                async with page.expect_download(timeout=30000) as dl_info:
                    await btn.click()
                download = await dl_info.value
                await download.save_as(str(output_path))
                logger.info("Backfill: downloaded PDF via %r -> %s", selector, output_path)
                return {
                    "name": native_id,
                    "url": page.url,
                    "type": "pdf",
                    "local_path": f"/api/reports/pdfs/{source}/{native_id}/{safe_name}.pdf",
                }
        except Exception:
            continue

    return None


# ────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Horizon Reports Library — fetch and store research reports",
    )
    parser.add_argument(
        "--source",
        help="Only fetch from this source (e.g. 'aliyunreports', 'fxbaogao')",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("help", add_help=False, help="Show this help message")

    backfill = sub.add_parser(
        "backfill-pdfs",
        help="Download PDFs for reports already in the database",
    )
    backfill.add_argument(
        "--source",
        help="Only backfill PDFs for this source (e.g. 'aliresearch', 'fxbaogao')",
    )
    backfill.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of reports to process (0 = unlimited)",
    )
    return parser


def main() -> None:
    """Main CLI entry point."""
    load_dotenv()

    parser = _build_parser()
    args = parser.parse_args()

    # Short-circuit on explicit help.
    if args.command == "help":
        parser.print_help()
        return

    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
    except FileNotFoundError:
        console.print("[bold red]❌ Configuration file not found![/bold red]")
        sys.exit(1)
    except ConfigError as e:
        console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
        sys.exit(1)

    if args.command == "backfill-pdfs":
        asyncio.run(backfill_pdfs(config, source=args.source, limit=args.limit))
    else:
        if args.source and config.reports and config.reports.sources:
            config.reports.sources = [type(config.reports.sources[0])(name=args.source)]
        asyncio.run(run(config))


if __name__ == "__main__":
    main()
