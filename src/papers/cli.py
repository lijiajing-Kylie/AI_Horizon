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
from typing import Dict, Optional

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..logging_config import silence_http_loggers
from ..models import Config
from ..storage.db import HorizonDB
from ..storage.manager import ConfigError, StorageManager
from ..ai.client import create_ai_client
from .weekly import WeeklyArxivResult, enrich_featured, run_weekly_arxiv_all
from .keywords import _get_concurrency, extract_paper_keywords
from .models import ClassicFetchResult, Paper
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


def _ai_summary_stale(raw) -> bool:
    """True when a stored ai_summary is missing or predates the current
    11-layer monolingual format (which always has one_sentence_summary)."""
    if not raw:
        return True
    return not (isinstance(raw, dict) and "one_sentence_summary" in raw)


async def run(
    config: Config,
    only_source: Optional[str] = None,
    dry_run: bool = False,
    no_translate: bool = False,
    no_enrich: bool = False,
    classify_topics: bool = False,
    translate_existing: bool = False,
    extract_keywords: bool = False,
    featured_count: Optional[int] = None,
    enrich_existing: bool = False,
    enrich_limit: Optional[int] = None,
) -> int:
    """Fetch configured paper sources and persist results.

    When *classify_topics* is True, skips the fetch phase entirely and
    backfills topic classifications for all existing papers in the database,
    then exits.

    When *translate_existing* is True, skips the fetch phase entirely and
    translates previously-stored featured (is_featured) papers that lack a
    Chinese translation.

    When *enrich_existing* is True, skips the fetch phase entirely and
    re-runs detail enrichment (ai_summary) for previously-
    stored featured arXiv papers that lack an ai_summary; *enrich_limit*
    caps the number processed per run (for staged backfills).

    When *extract_keywords* is True, skips the fetch phase entirely and
    AI-extracts keywords for all previously-stored papers that lack them.
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
        # Only translate featured (入选) papers that lack a Chinese title —
        # non-featured arXiv papers stay English by design.
        untranslated = [
            p for p in all_papers
            if p.get("is_featured") and not p.get("title_zh")
        ]
        if not untranslated:
            console.print("[dim]All featured papers already have Chinese translations.[/dim]")
            return 0
        console.print(f"Translating {len(untranslated)} untranslated featured papers (of {len(all_papers)} total)...")
        ai_client = create_ai_client(config.ai)
        papers = [Paper(**p) for p in untranslated]
        await translate_papers(ai_client, papers)
        saved = db.save_papers(papers)
        console.print(f"[green]Translated and saved {saved} papers.[/green]")
        return saved

    # ------------------------------------------------------------------
    # Backfill mode: re-enrich featured arXiv papers lacking a *current*
    # (11-layer monolingual) ai_summary. Papers whose stored summary predates
    # the new format (background/problem/contribution/...) are re-generated
    # too, so --enrich-existing doubles as a one-shot format upgrade.
    # ------------------------------------------------------------------
    if enrich_existing:
        if db is None:
            console.print("[yellow]--enrich-existing requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        missing = [
            p for p in all_papers
            if p.get("source") in ("arxiv", "arxiv_fin")
            and p.get("is_featured")
            and _ai_summary_stale(p.get("ai_summary"))
        ]
        if enrich_limit is not None:
            missing = missing[:enrich_limit]
        if not missing:
            console.print("[dim]All featured arXiv papers already have current AI summaries.[/dim]")
            return 0
        console.print(f"Re-enriching {len(missing)} featured papers (of {len(all_papers)} total)...")
        ai_client = create_ai_client(config.ai)
        papers = [Paper(**p) for p in missing]
        concurrency = _get_concurrency(ai_client)
        async with httpx.AsyncClient(timeout=30.0) as client:
            await enrich_featured(ai_client, client, papers, concurrency)
        saved = db.save_papers(papers)
        failed = sum(1 for p in papers if p.ai_summary is None)
        console.print(f"[green]Enriched and saved {saved} papers (failed {failed}).[/green]")
        return saved

    # ------------------------------------------------------------------
    # Backfill mode: extract AI keywords for existing papers, then exit.
    # ------------------------------------------------------------------
    if extract_keywords:
        if db is None:
            console.print("[yellow]--extract-keywords requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        missing = [p for p in all_papers if not p.get("keywords")]
        if not missing:
            console.print("[dim]All papers already have keywords.[/dim]")
            return 0
        console.print(f"Extracting keywords for {len(missing)} papers (of {len(all_papers)} total)...")
        ai_client = create_ai_client(config.ai)
        papers = [Paper(**p) for p in missing]
        await extract_paper_keywords(ai_client, papers, _get_concurrency(ai_client))
        saved = db.save_papers(papers)
        console.print(f"[green]Extracted and saved keywords for {saved} papers.[/green]")
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
                    if not no_translate or papers_cfg.extract_keywords:
                        ai_client = create_ai_client(config.ai)
                        if not no_translate:
                            await translate_papers(ai_client, matched_papers)
                        if papers_cfg.extract_keywords:
                            await extract_paper_keywords(
                                ai_client, matched_papers, _get_concurrency(ai_client),
                            )
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

        if papers_cfg.arxiv.enabled and only_source in (None, "arxiv"):
            arxiv_cfg = papers_cfg.arxiv
            if featured_count is not None:
                arxiv_cfg = arxiv_cfg.model_copy(update={"featured_count": featured_count})
            ai_client = create_ai_client(config.ai)
            results = await run_weekly_arxiv_all(
                ai_client=ai_client,
                http_client=client,
                cfg=arxiv_cfg,
                db=db,
                no_translate=no_translate,
            )
            _print_arxiv_report(results)
            total_saved += sum(r.saved_total for r in results.values())

    if dry_run:
        console.print("\n[yellow]Dry run — nothing was written to the database.[/yellow]")
    return total_saved


def _print_arxiv_report(results: Dict[str, WeeklyArxivResult]) -> None:
    """Print the arXiv weekly pipeline summary per channel and its featured set."""
    labels = {"arxiv": "arXiv 每周精选", "arxiv_fin": "AI+金融"}
    for source, result in results.items():
        label = labels.get(source, source)
        console.print(
            f"\n{label}: fetched {result.fetched}, "
            f"after rule-filter {result.after_filter}, "
            f"scored {result.scored} (new {result.scored_new}), "
            f"featured {len(result.featured)}, "
            f"enriched {result.enriched_new} (failed {result.enrich_failed}), "
            f"translated {result.translated_new} (failed {result.translate_failed}), "
            f"saved {result.saved_total}."
        )
        # Surface unusually high failure rates so silent AI outages are noticed.
        for metric, ok, failed in (
            ("enrich", result.enriched_new, result.enrich_failed),
            ("translate", result.translated_new, result.translate_failed),
        ):
            total = ok + failed
            if total and failed / total > 0.2:
                console.print(
                    f"[bold red]{label} {metric} 失败率偏高：{failed}/{total}，"
                    f"请检查 AI 限流/超时[/bold red]"
                )
        if result.featured:
            table = Table(title=label)
            table.add_column("score", justify="right")
            table.add_column("breakdown", justify="center")
            table.add_column("venue")
            table.add_column("title")
            for p in result.featured:
                score = f"{p.ai_relevance_score:.1f}" if p.ai_relevance_score is not None else "—"
                breakdown = ""
                if p.ai_score_breakdown:
                    parts = []
                    for key, zh in (("innovation", "创"), ("technical_quality", "质"),
                                    ("impact_potential", "影"), ("relevance", "关")):
                        val = p.ai_score_breakdown.get(key)
                        if val is not None:
                            parts.append(f"{zh}{val:.1f}")
                    breakdown = " ".join(parts)
                table.add_row(score, breakdown, p.venue or "—", p.title[:80])
            console.print(table)


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
    silence_http_loggers()
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Horizon Papers Library — fetch and store papers from configured sources"
    )
    parser.add_argument(
        "--source",
        choices=["openalex", "arxiv"],
        default=None,
        help="Only fetch this source (default: all enabled sources)",
    )
    parser.add_argument(
        "--featured-count",
        type=int,
        default=None,
        help="Override featured_count from config for this run (only applies to arxiv)",
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
        help="Translate previously-stored featured papers that lack a Chinese "
        "translation, then exit (no fetch).",
    )
    parser.add_argument(
        "--enrich-existing",
        action="store_true",
        help="Re-run detail enrichment (ai_summary) for "
        "previously-stored featured arXiv papers that lack a current "
        "ai_summary (missing or old pre-monolingual format), then exit "
        "(no fetch).",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=None,
        help="Cap the number of papers processed by --enrich-existing "
        "(for staged backfills).",
    )
    parser.add_argument(
        "--extract-keywords",
        action="store_true",
        help="Backfill AI-extracted keywords for existing papers that lack "
        "them, then exit (no fetch).",
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
                     dry_run=args.dry_run,
                     no_translate=args.no_translate,
                     no_enrich=args.no_enrich,
                     classify_topics=args.classify_topics,
                     translate_existing=args.translate_existing,
                     extract_keywords=args.extract_keywords,
                     featured_count=args.featured_count,
                     enrich_existing=args.enrich_existing,
                     enrich_limit=args.enrich_limit))


if __name__ == "__main__":
    main()
