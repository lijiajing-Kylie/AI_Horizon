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
import shutil
import sys
from datetime import datetime
from pathlib import Path
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
from .weekly import AI_SUMMARY_VERSION, WeeklyArxivResult, enrich_featured, run_weekly_arxiv_all
from .keywords import _get_concurrency, extract_paper_keywords
from .latex import latex_to_unicode
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


# 一段完整解读（v3）必须含有的字段。版本号达标但缺其中任一（如某分段生成
# 失败被整体丢弃）视为不完整，同样进入 --enrich-existing 的重生成队列。
_SUMMARY_COMPLETENESS_FIELDS = (
    "core_idea",
    "technical_details",
    "experimental_evidence",
    "limitations",
)


def _ai_summary_stale(raw) -> bool:
    """True when a stored ai_summary is missing, predates the current
    interpretation format/version, or is incomplete (a segment failed).

    Stale if:
    - raw is missing / not a dict (e.g. legacy string, list);
    - it lacks one_sentence_summary (the pre-monolingual bilingual {en, zh}
      format, or an old single-layer summary);
    - it has one_sentence_summary but interpretation_version < AI_SUMMARY_VERSION
      (missing version defaults to 0, so every row written before the version
      bump becomes re-enrichable);
    - it has a current version but is missing any of _SUMMARY_COMPLETENESS_FIELDS
      (a failed segment, e.g. method/evaluation dropping core_idea or
      experimental_evidence; the 4096-token budget bug once produced exactly
      this shape).
    """
    if not isinstance(raw, dict):
        return True
    if "one_sentence_summary" not in raw:
        return True
    if raw.get("interpretation_version", 0) < AI_SUMMARY_VERSION:
        return True
    return any(
        not (isinstance(raw.get(f), str) and raw[f].strip())
        for f in _SUMMARY_COMPLETENESS_FIELDS
    )


async def run(
    config: Config,
    only_source: Optional[str] = None,
    dry_run: bool = False,
    no_translate: bool = False,
    no_enrich: bool = False,
    classify_topics: bool = False,
    translate_existing: bool = False,
    extract_keywords: bool = False,
    clean_latex: bool = False,
    featured_count: Optional[int] = None,
    enrich_existing: bool = False,
    enrich_limit: Optional[int] = None,
    paper_id: Optional[str] = None,
    prune_unfeatured: bool = False,
    confirm: bool = False,
) -> int:
    """Fetch configured paper sources and persist results.

    When *classify_topics* is True, skips the fetch phase entirely and
    backfills topic classifications for all existing papers in the database,
    then exits.

    When *translate_existing* is True, skips the fetch phase entirely and
    translates previously-stored featured (is_featured) papers that lack a
    Chinese translation.

    When *enrich_existing* is True, skips the fetch phase entirely and
    re-runs detail enrichment (ai_summary) for previously-stored featured
    arXiv papers whose ai_summary is missing or predates the current
    interpretation version (see _ai_summary_stale); *enrich_limit* caps the
    number processed per run (for staged backfills). With *paper_id*, only
    that single paper is re-generated (regardless of its current version).

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
    # Backfill mode: re-enrich featured arXiv papers whose ai_summary is
    # missing or predates the current interpretation version (see
    # _ai_summary_stale). --enrich-existing doubles as a one-shot upgrade
    # path whenever the AI 解读 prompt semantics change.
    # ------------------------------------------------------------------
    if enrich_existing:
        if db is None:
            console.print("[yellow]--enrich-existing requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        if paper_id:
            # 单篇重解读：指定 id 时强制重生成该篇，忽略 stale 判定。
            target = [p for p in all_papers if p.get("id") == paper_id]
            if not target:
                console.print(f"[yellow]No paper with id {paper_id!r} found in the database.[/yellow]")
                return 0
            missing = target
        else:
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
    # Backfill mode: strip LaTeX math from stored text fields, then exit.
    # Historically arXiv abstracts (and their AI translations) were stored
    # with raw $...$ math; this rewrites them to readable Unicode.
    # ------------------------------------------------------------------
    if clean_latex:
        if db is None:
            console.print("[yellow]--clean-latex requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        papers_changed = 0
        fields_changed = 0
        for p in all_papers:
            new_title = latex_to_unicode(p.get("title") or "")
            new_abstract = latex_to_unicode(p.get("abstract") or "")
            new_title_zh = latex_to_unicode(p.get("title_zh") or "")
            new_abstract_zh = latex_to_unicode(p.get("abstract_zh") or "")
            changed = {
                field: value
                for field, value in (
                    ("title", new_title),
                    ("abstract", new_abstract),
                    ("title_zh", new_title_zh),
                    ("abstract_zh", new_abstract_zh),
                )
                if value != (p.get(field) or "")
            }
            if not changed:
                continue
            with db.conn:
                db.conn.execute(
                    "UPDATE papers SET title=?, abstract=?, title_zh=?, "
                    "abstract_zh=?, updated_row_at=datetime('now') WHERE id=?",
                    (new_title, new_abstract, new_title_zh, new_abstract_zh, p["id"]),
                )
            papers_changed += 1
            fields_changed += len(changed)
        console.print(
            f"[green]Cleaned LaTeX in {papers_changed} papers "
            f"({fields_changed} fields).[/green]"
        )
        return papers_changed

    # ------------------------------------------------------------------
    # Backfill mode: prune un-featured arXiv papers (打分失败/未入选候选)。
    # 默认只列出待删名单;加 --confirm 才执行删除(先备份,再事务删除)。
    # ------------------------------------------------------------------
    if prune_unfeatured:
        if db is None:
            console.print("[yellow]--prune-unfeatured requires a writable DB (--dry-run not supported).[/yellow]")
            return 0
        result = db.get_papers(per_page=10000)
        all_papers = result["items"]
        doomed = [
            p for p in all_papers
            if not p.get("is_featured") and str(p.get("source", "")).startswith("arxiv")
        ]
        if not doomed:
            console.print("[dim]没有需要清理的非精选 arXiv 论文.[/dim]")
            return 0
        console.print(f"[bold]待清理 {len(doomed)} 篇非精选 arXiv 论文(失败/未入选候选):[/bold]")
        for p in sorted(doomed, key=lambda x: x["id"]):
            reason = p.get("ai_reason") or "(无 reason)"
            console.print(f"  {p['id']} | {p.get('source')} | {reason} | {p['title'][:60]}")
        if not confirm:
            console.print(
                "[yellow]未加 --confirm,仅列出名单,未删除任何数据。"
                "核对无误后加 --confirm 执行删除。[/yellow]"
            )
            return 0
        backup = Path(str(db.db_path) + f".bak_before_prune_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(db.db_path, backup)
        console.print(f"[dim]已备份数据库到 {backup}[/dim]")
        ids = [p["id"] for p in doomed]
        placeholders = ", ".join("?" for _ in ids)
        with db.conn:
            db.conn.execute(
                f"DELETE FROM paper_topics WHERE paper_id IN ({placeholders})", ids
            )
            db.conn.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", ids)
        console.print(
            f"[green]已删除 {len(doomed)} 篇非精选 arXiv 论文及其主题关联.[/green]"
        )
        return len(doomed)

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
                        # 失败不入库:翻译已尝试但未产出中文标题的论文不写入
                        # (中文论文 title_zh=原文,恒非空,不会被误删)。
                        matched_papers = [p for p in matched_papers if p.title_zh is not None]
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
                        f"manual_review/unmatched/translate_failed). {tc} classified.[/green]"
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
        "previously-stored featured arXiv papers whose ai_summary is "
        "missing or predates the current interpretation version, then exit "
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
        "--paper-id",
        type=str,
        default=None,
        help="With --enrich-existing: re-generate the interpretation for a "
        "single paper id (e.g. arxiv:2508.12345), regardless of current "
        "version. Ignored without --enrich-existing.",
    )
    parser.add_argument(
        "--extract-keywords",
        action="store_true",
        help="Backfill AI-extracted keywords for existing papers that lack "
        "them, then exit (no fetch).",
    )
    parser.add_argument(
        "--clean-latex",
        action="store_true",
        help="Backfill: strip LaTeX math from stored title/abstract/"
        "title_zh/abstract_zh into readable Unicode, then exit (no fetch).",
    )
    parser.add_argument(
        "--prune-unfeatured",
        action="store_true",
        help="List (and with --confirm, delete) un-featured arXiv papers "
        "from the database, then exit (no fetch).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="With --prune-unfeatured: actually delete (backup + delete) "
        "the listed papers. Without it, --prune-unfeatured only lists.",
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
                     clean_latex=args.clean_latex,
                     featured_count=args.featured_count,
                     enrich_existing=args.enrich_existing,
                     enrich_limit=args.enrich_limit,
                     paper_id=args.paper_id,
                     prune_unfeatured=args.prune_unfeatured,
                     confirm=args.confirm))


if __name__ == "__main__":
    main()
