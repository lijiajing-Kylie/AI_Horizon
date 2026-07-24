"""CLI entry point for fetching and storing the papers library.

Standalone from the news pipeline: never touches HorizonOrchestrator,
ContentAnalyzer, or ContentEnricher. Run on its own schedule (e.g. a
separate cron per source via ``--source``), independent of ``horizon``.

**Write rules**: only papers with ``match_status == "matched"`` are written
to the main ``papers`` table. ``manual_review`` and ``unmatched`` results
appear in the CLI report only.
"""

import argparse
import asyncio
import sys
from typing import Optional

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..models import Config
from ..storage.db import HorizonDB
from ..storage.manager import ConfigError, StorageManager
from ..ai.client import create_ai_client
from .models import ClassicFetchResult, Paper
from .sources.huggingface import HuggingFaceFetcher
from .sources.openalex import OpenAlexFetcher
from .topics import build_paper_topics, classify_paper_topics
from .translator import translate_papers

console = Console()

_STATUS_ORDER = {"matched": 0, "manual_review": 1, "unmatched": 2}
_ENRICHMENT_EMOJI = {
    "complete": "[green]✓[/green]",
    "partial": "[yellow]◐[/yellow]",
    "rate_limited": "[red]⧗[/red]",
    "failed": "[red]✗[/red]",
    "not_attempted": "[dim]—[/dim]",
}


async def run(
    config: Config,
    only_source: Optional[str] = None,
    month: Optional[str] = None,
    week: Optional[str] = None,
    top_n: Optional[int] = None,
    dry_run: bool = False,
    no_translate: bool = False,
    no_enrich: bool = False,
    classify_topics: bool = False,
    translate_existing: bool = False,
) -> int:
    """Fetch configured paper sources and persist results.

    When *classify_topics* is True, skips the fetch phase entirely and
    backfills topic classifications for all existing papers in the database,
    then exits.

    When *translate_existing* is True, skips the fetch phase entirely and
    translates all previously-stored papers that lack a Chinese translation.
    Otherwise, by default, translates newly-fetched papers before saving
    (use *no_translate* to skip that step). Returns count saved (0 in dry-run)."""
    if not config.papers or not config.papers.enabled:
        console.print("[yellow]Papers library not enabled in config; nothing to do.[/yellow]")
        return 0

    papers_cfg = config.papers
    total_saved = 0
    db = HorizonDB() if not dry_run else None

    # ------------------------------------------------------------------
    # Backfill mode: classify topics for existing papers, then exit.
    # ------------------------------------------------------------------
    if classify_topics:
        if db is None:
            console.print("[yellow]--classify-topics requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        console.print(f"Classifying topics for {len(all_papers)} papers...")
        # Ensure paper topic seeds exist in the topics table
        db.seed_paper_topics(build_paper_topics())
        classified = 0
        for p in all_papers:
            paper = Paper(**p)
            topics_data = classify_paper_topics(paper)
            if topics_data:
                db.save_paper_topics(paper.id, topics_data)
                classified += 1
        console.print(f"[green]Classified {classified}/{len(all_papers)} papers with topics.[/green]")
        return classified

    # ------------------------------------------------------------------
    # Backfill mode: translate existing untranslated papers, then exit.
    # ------------------------------------------------------------------
    if translate_existing:
        if db is None:
            console.print("[yellow]--translate-existing requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        # Only translate papers that don't have a Chinese title yet
        untranslated = [p for p in all_papers if not p.get("title_zh")]
        if not untranslated:
            console.print("[dim]All papers already have Chinese translations.[/dim]")
            return 0
        console.print(f"Translating {len(untranslated)} untranslated papers (of {len(all_papers)} total)...")
        ai_client = create_ai_client(config.ai)
        papers = [Paper(**p) for p in untranslated]
        await translate_papers(ai_client, papers)
        saved = db.save_papers(papers)
        console.print(f"[green]Translated and saved {saved} papers.[/green]")
        return saved

    # ------------------------------------------------------------------
    # Normal fetch → (translate) → save flow.
    # ------------------------------------------------------------------
    async with httpx.AsyncClient(timeout=30.0) as client:
        if papers_cfg.openalex.enabled and only_source in (None, "openalex"):
            result = await OpenAlexFetcher(papers_cfg.openalex).fetch_classic(client)
            _print_openalex_report(result)
            if db is not None:
                matched_papers = [
                    p for p, mr in zip(result.papers, result.match_results)
                    if mr.match_status == "matched"
                ]
                # Only include matched papers that actually have a valid native_id
                matched_papers = [p for p in matched_papers if p.native_id]
                if matched_papers:
                    if not no_translate:
                        ai_client = create_ai_client(config.ai)
                        await translate_papers(ai_client, matched_papers)
                    n = db.save_papers(matched_papers)
                    total_saved += n
                    # Topic classification (rule-based, zero AI cost)
                    db.seed_paper_topics(build_paper_topics())
                    tc = 0
                    for paper in matched_papers:
                        td = classify_paper_topics(paper)
                        if td:
                            db.save_paper_topics(paper.id, td)
                            tc += 1
                    console.print(
                        f"[green]Saved {n} matched papers to database "
                        f"({len(result.papers) - len(matched_papers)} not written: "
                        f"manual_review/unmatched). {tc} classified.[/green]"
                    )

        if papers_cfg.huggingface.enabled and only_source in (None, "huggingface"):
            hf_papers = await HuggingFaceFetcher(papers_cfg.huggingface).fetch(
                client, month=month, week=week, top_n_override=top_n,
                no_enrich=no_enrich,
            )
            console.print(f"\nHugging Face: fetched {len(hf_papers)} papers.")
            if db is not None:
                if hf_papers and not no_translate:
                    ai_client = create_ai_client(config.ai)
                    await translate_papers(ai_client, hf_papers)
                n = db.save_papers(hf_papers)
                total_saved += n
                # Topic classification (rule-based, zero AI cost)
                db.seed_paper_topics(build_paper_topics())
                tc = 0
                for paper in hf_papers:
                    td = classify_paper_topics(paper)
                    if td:
                        db.save_paper_topics(paper.id, td)
                        tc += 1
                console.print(f"  Topics: {tc}/{len(hf_papers)} papers classified.")

    if dry_run:
        console.print("\n[yellow]Dry run — nothing was written to the database.[/yellow]")
    return total_saved


def _print_openalex_report(result: ClassicFetchResult) -> None:
    """Print a detailed report: summary table, per-paper details, and any
    items needing manual review."""

    # ---- summary by match_status vs enrichment_status --------------------
    by_match: dict[str, int] = {"matched": 0, "manual_review": 0, "unmatched": 0}
    by_enrich: dict[str, int] = {}
    by_method: dict[str, int] = {}
    for r in result.match_results:
        by_match[r.match_status] = by_match.get(r.match_status, 0) + 1
        es = r.enrichment_status
        by_enrich[es] = by_enrich.get(es, 0) + 1
        if r.match_method:
            by_method[r.match_method] = by_method.get(r.match_method, 0) + 1

    total = len(result.match_results)

    summary = Table(title=f"Classic papers — match summary ({total} seeds)")
    summary.add_column("metric")
    summary.add_column("value")
    summary.add_row("[bold]matched[/bold]", str(by_match.get("matched", 0)))
    summary.add_row("[yellow]manual_review[/yellow]", str(by_match.get("manual_review", 0)))
    summary.add_row("[red]unmatched[/red]", str(by_match.get("unmatched", 0)))
    for es, cnt in sorted(by_enrich.items()):
        emoji = _ENRICHMENT_EMOJI.get(es, "")
        summary.add_row(f"  enrichment {es} {emoji}", str(cnt))
    console.print(summary)

    # ---- match method breakdown ------------------------------------------
    if by_method:
        method_table = Table(title="Match method breakdown")
        method_table.add_column("method")
        method_table.add_column("count")
        for method, count in sorted(by_method.items(), key=lambda x: -x[1]):
            method_table.add_row(method, str(count))
        console.print(method_table)

    # ---- per-paper detail table ------------------------------------------
    detail = Table(title="Per-seed results")
    detail.add_column("status")
    detail.add_column("category")
    detail.add_column("seed title")
    detail.add_column("method", justify="center")
    detail.add_column("matched title")
    detail.add_column("year", justify="center")
    detail.add_column("enrich")
    detail.add_column("note")

    for r in sorted(
        result.match_results,
        key=lambda r: (_STATUS_ORDER.get(r.match_status, 9), r.category, r.seed_title),
    ):
        ms_style = {
            "matched": "[green]✓[/green]",
            "manual_review": "[yellow]?[/yellow]",
            "unmatched": "[red]✗[/red]",
        }.get(r.match_status, r.match_status)

        method_display = r.match_method or "—"
        enrich_emoji = _ENRICHMENT_EMOJI.get(r.enrichment_status, "")

        detail.add_row(
            ms_style,
            r.category,
            r.seed_title[:60] + ("…" if len(r.seed_title) > 60 else ""),
            method_display,
            (r.matched_title or "—")[:55] + ("…" if (r.matched_title or "") and len(r.matched_title or "") > 55 else ""),
            str(r.matched_year) if r.matched_year else "—",
            f"{enrich_emoji} {r.enrichment_status}",
            r.note[:60] + ("…" if len(r.note) > 60 else ""),
        )
    console.print(detail)

    # ---- manual_review items: show reasons clearly -----------------------
    needs_review = [r for r in result.match_results if r.match_status == "manual_review"]
    if needs_review:
        console.print("\n[yellow bold]Needs manual review:[/yellow bold]")
        review = Table()
        review.add_column("category")
        review.add_column("seed title")
        review.add_column("expected yr")
        review.add_column("matched title")
        review.add_column("matched yr")
        review.add_column("note")
        for r in needs_review:
            review.add_row(
                r.category,
                r.seed_title,
                str(r.expected_year),
                r.matched_title or "—",
                str(r.matched_year) if r.matched_year else "—",
                r.note,
            )
        console.print(review)

    # ---- unmatched items -------------------------------------------------
    unmatched = [r for r in result.match_results if r.match_status == "unmatched"]
    if unmatched:
        console.print("\n[red bold]Unmatched:[/red bold]")
        un_table = Table()
        un_table.add_column("category")
        un_table.add_column("seed title")
        un_table.add_column("expected yr")
        un_table.add_column("note")
        for r in unmatched:
            un_table.add_row(r.category, r.seed_title, str(r.expected_year), r.note)
        console.print(un_table)

    # ---- final summary line ----------------------------------------------
    if by_match.get("matched") == total:
        console.print("\n[green]All seeds matched automatically.[/green]")
    else:
        console.print(
            f"\n[bold]Result:[/bold] {by_match.get('matched', 0)}/{total} matched, "
            f"{by_match.get('manual_review', 0)} manual review, "
            f"{by_match.get('unmatched', 0)} unmatched"
        )


def main() -> None:
    """Main CLI entry point."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Horizon Papers Library — fetch and store papers from configured sources"
    )
    parser.add_argument(
        "--source",
        choices=["openalex", "huggingface"],
        default=None,
        help="Only fetch this source (default: all enabled sources)",
    )
    parser.add_argument(
        "--month",
        default=None,
        help="Fetch specific month (YYYY-MM) — only applies to huggingface source",
    )
    parser.add_argument(
        "--week",
        default=None,
        help="Fetch specific ISO week (YYYY-Www) — only applies to huggingface source",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override top_n from config for this run (only applies to huggingface)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print a report without writing to the database",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Skip AI translation of fetched papers",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip arXiv enrichment (journal_ref, categories) — faster backfill",
    )
    parser.add_argument(
        "--classify-topics",
        action="store_true",
        help="Backfill topic classifications for all existing papers in the "
        "database, then exit (no fetch).",
    )
    parser.add_argument(
        "--translate-existing",
        action="store_true",
        help="Translate all previously-stored papers that lack a Chinese "
        "translation, then exit (no fetch).",
    )
    args = parser.parse_args()

    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
    except FileNotFoundError:
        console.print("[bold red]❌ Configuration file not found![/bold red]")
        sys.exit(1)
    except ConfigError as e:
        console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
        sys.exit(1)

    asyncio.run(run(config, only_source=args.source,
                     month=args.month, week=args.week, top_n=args.top_n,
                     dry_run=args.dry_run,
                     no_translate=args.no_translate,
                     no_enrich=args.no_enrich,
                     classify_topics=args.classify_topics,
                     translate_existing=args.translate_existing))


if __name__ == "__main__":
    main()
