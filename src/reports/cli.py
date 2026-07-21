"""CLI entry point for fetching and storing the research-reports library.

Standalone from the news pipeline: never touches HorizonOrchestrator,
ContentAnalyzer, or ContentEnricher. Run on its own schedule (e.g. a
separate cron), independent of `horizon`/`horizon-papers`.
"""

import argparse
import asyncio
import sys

import httpx
from dotenv import load_dotenv
from rich.console import Console

from ..ai.client import create_ai_client
from ..models import Config
from ..storage.db import HorizonDB
from ..storage.manager import ConfigError, StorageManager
from .fetcher import fetch_all_reports

console = Console()


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

    db = HorizonDB()
    count = db.save_reports(reports)
    console.print(f"[green]Saved {count} reports.[/green]")
    return count


def main() -> None:
    """Main CLI entry point."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Horizon Reports Library — fetch and store research reports"
    )
    parser.parse_args()

    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
    except FileNotFoundError:
        console.print("[bold red]❌ Configuration file not found![/bold red]")
        sys.exit(1)
    except ConfigError as e:
        console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
        sys.exit(1)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
