"""arXiv weekly-featured pipeline: fetch → rule-filter → AI pre-screen → enrich.

Standalone orchestration for ``horizon-papers --source arxiv``. Keeps the
papers library independent of the news pipeline: only reuses ``AIClient`` /
``parse_json_response`` / the DuckDuckGo search pattern (same as
``src.ai.enricher``) but has its own prompts and rule filters.

Flow:
    fetch_recent (per-category, window-filtered)
      → apply_rules (withdrawn / short abstract / keyword filters / github /
                     venue-signal priority / truncate to target_candidates)
      → score_papers (AI 0-10 per candidate) → sort desc
      → take featured_count → mark is_featured + featured_date
      → enrich_featured (concepts → web search → bilingual interpretation)
      → preserve prior featured state → save_papers
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import trafilatura
from ddgs import DDGS
from pydantic import BaseModel

from ..ai.client import AIClient
from ..ai.utils import complete_with_retry, parse_json_response
from ..models import ArxivSourceConfig
from .filters import (
    apply_keyword_blacklist,
    apply_keyword_whitelist,
    apply_venue_signals,
    exclude_withdrawn,
    extract_github_url,
    reject_short_abstracts,
    truncate,
)
from .models import Paper
from .progress import run_progress
from .translator import translate_papers
from .prompts import (
    ARXIV_CONCEPT_SYSTEM,
    ARXIV_CONCEPT_USER,
    ARXIV_DETAIL_SYSTEM,
    ARXIV_DETAIL_USER,
    ARXIV_SCORE_SYSTEM,
    ARXIV_SCORE_USER,
)
from .sources.arxiv import fetch_recent as _arxiv_fetch_recent

logger = logging.getLogger(__name__)


class WeeklyArxivResult(BaseModel):
    """Outcome of one arXiv channel group (single ``run_weekly_arxiv`` run, or
    one entry of ``run_weekly_arxiv_all``), surfaced by the CLI."""

    fetched: int                              # papers entering this group after the window filter
    after_filter: int                         # papers surviving rule filters
    scored: int                               # papers with a usable score (read back + newly scored)
    scored_new: int = 0                       # papers actually AI-scored this run (dedup insight)
    featured: List[Paper]                     # the featured set (enriched this run)
    enriched_new: int = 0                     # featured papers successfully detail-enriched this run
    enrich_failed: int = 0                    # featured papers that failed to produce an ai_summary
    translated_new: int = 0                   # featured papers successfully translated this run
    translate_failed: int = 0                 # featured papers whose translation failed
    saved_total: int                          # papers upserted to the DB (0 in dry-run)


async def fetch_recent(
    client: Any,
    categories: List[str],
    max_results_per_category: int,
    window_days: int,
) -> List[Paper]:
    """Fetch the newest papers across *categories*, keeping the last
    ``window_days`` of submissions (arXiv indexing lags by hours)."""
    papers = await _arxiv_fetch_recent(client, categories, max_results_per_category)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    return [p for p in papers if p.published_at >= cutoff]


# Source key under which the AI+Finance group is persisted (distinct tab /
# featured pool from the general "arxiv" source).
FINANCE_SOURCE = "arxiv_fin"


def split_by_finance(
    papers: List[Paper],
    finance_categories: List[str],
) -> tuple[List[Paper], List[Paper]]:
    """Split fetched papers into ``(general, finance)`` by category membership.

    A paper belongs to the AI+Finance group when any of its arXiv categories is
    in *finance_categories* (e.g. ``q-fin.*``); ``general`` is the complement by
    id, so a paper is never in both groups. Empty *finance_categories* puts
    everything in ``general``.
    """
    fin_set = set(finance_categories)
    if not fin_set:
        return papers, []
    finance = [p for p in papers if any(c in fin_set for c in p.categories)]
    fin_ids = {p.id for p in finance}
    general = [p for p in papers if p.id not in fin_ids]
    return general, finance


def _rekey_source(paper: Paper, source: str) -> Paper:
    """Re-namespace a paper under a new source key (mutates and returns it).

    The finance group is stored as ``source=FINANCE_SOURCE`` with id
    ``f"{source}:{native_id}"`` so it gets its own tab / featured pool while
    sharing the same arXiv native id (``Paper`` is not frozen, so mutation is
    the established pattern in this module).
    """
    paper.source = source
    paper.id = f"{source}:{paper.native_id}"
    return paper


def apply_rules(papers: List[Paper], cfg: ArxivSourceConfig) -> List[Paper]:
    """Run the multi-rule filter chain in dependency order."""
    papers = exclude_withdrawn(papers)
    papers = reject_short_abstracts(papers, cfg.min_abstract_chars)
    papers = apply_keyword_whitelist(papers, cfg.keyword_whitelist)
    papers = apply_keyword_blacklist(papers, cfg.keyword_blacklist)
    for p in papers:
        p.github_url = extract_github_url(p.comment, p.abstract)
    # Venue-signal priority first, then truncate to the candidate budget.
    papers = apply_venue_signals(papers)
    return truncate(papers, cfg.target_candidates)


def _get_concurrency(ai_client: AIClient) -> int:
    """Read the configured analysis concurrency, clamped to ≥ 1."""
    config = getattr(ai_client, "config", None)
    return max(getattr(config, "analysis_concurrency", 1) or 1, 1)


async def score_papers(
    ai_client: AIClient,
    papers: List[Paper],
    concurrency: int,
) -> None:
    """AI pre-screen scoring: one lightweight call per paper (0-10 + reason)."""
    if not papers:
        return
    semaphore = asyncio.Semaphore(concurrency)

    async def _score_one(paper: Paper) -> None:
        async with semaphore:
            await _score_paper(ai_client, paper)

    await run_progress("AI 评分", [_score_one(p) for p in papers])


_SCORE_FIELDS = ("innovation", "technical_quality", "impact_potential", "relevance")


def _clamp_score(value: Any) -> Optional[float]:
    """Coerce a score value to a 0-10 float, or None when unparseable."""
    if value is None:
        return None
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return None


async def _score_paper(ai_client: AIClient, paper: Paper) -> None:
    try:
        response = await complete_with_retry(
            ai_client,
            system=ARXIV_SCORE_SYSTEM,
            user=ARXIV_SCORE_USER.format(
                title=paper.title,
                authors=", ".join(paper.authors[:10]),
                categories=", ".join(paper.categories),
                published_at=paper.published_at.date().isoformat(),
                venue=paper.venue or "无",
                abstract=(paper.abstract or "")[:2000],
            ),
            temperature=0.2,
            max_tokens=200,
        )
        result = parse_json_response(response)
        overall = _clamp_score(result.get("overall_score") if result else None)
        if overall is not None:
            paper.ai_relevance_score = overall
            paper.ai_reason = str(result.get("reason") or "").strip()
            paper.ai_score_breakdown = {
                field: _clamp_score(result.get(field)) for field in _SCORE_FIELDS
            }
        else:
            paper.ai_relevance_score = None
            paper.ai_reason = "scoring failed"
            paper.ai_score_breakdown = None
    except Exception:
        logger.warning("Pre-screen scoring failed for %s", paper.id, exc_info=True)
        paper.ai_relevance_score = None
        paper.ai_reason = "scoring failed"
        paper.ai_score_breakdown = None


def _mark_enrich_failure(paper: Paper, step: str, detail: str) -> None:
    """Record a detail-enrichment failure on ``paper.ai_reason``.

    The marker is appended (not overwriting the scoring reason) so the failure
    is visible in the CLI report and the DB row instead of silently vanishing.
    """
    reason = (paper.ai_reason or "").strip()
    marker = f"[enrich {step} failed: {detail}]"
    paper.ai_reason = f"{reason} {marker}".strip() if reason else marker


async def enrich_featured(
    ai_client: AIClient,
    http_client: Any,
    papers: List[Paper],
    concurrency: int,
) -> None:
    """Detail enrichment for an arbitrary paper subset: full-text fetch →
    concepts → web search → structured single-language (Chinese)
    interpretation. Failures keep the paper featured but leave its AI fields
    empty (graceful degrade, mirroring the news enricher); the failure reason
    is recorded on ``paper.ai_reason`` for visibility."""
    if not papers:
        return
    semaphore = asyncio.Semaphore(concurrency)

    async def _enrich_one(paper: Paper) -> None:
        async with semaphore:
            try:
                await _enrich_paper(ai_client, http_client, paper)
            except Exception as exc:
                logger.warning(
                    "Detail enrichment failed for %s", paper.id, exc_info=True,
                )
                _mark_enrich_failure(paper, "detail", str(exc)[:80])

    await run_progress("富化精选论文", [_enrich_one(p) for p in papers])


async def _enrich_paper(
    ai_client: AIClient,
    http_client: Any,
    paper: Paper,
) -> None:
    # Step 0: fetch the paper's full text so the interpretation is grounded in
    # the actual paper, not just its abstract (falls back gracefully).
    full_text = await _fetch_paper_full_text(http_client, paper)

    # Step 1: AI identifies 1-3 concepts worth explaining.
    queries: List[str] = []
    try:
        response = await complete_with_retry(
            ai_client,
            system=ARXIV_CONCEPT_SYSTEM,
            user=ARXIV_CONCEPT_USER.format(
                title=paper.title,
                categories=", ".join(paper.categories),
                abstract=(paper.abstract or "")[:2000],
            ),
        )
        result = parse_json_response(response)
        if result and result.get("queries"):
            queries = [str(q) for q in result["queries"][:3]]
    except Exception:
        queries = []

    # Step 2: search the web for each concept in parallel.
    web_sections: List[str] = []
    if queries:
        results_list = await asyncio.gather(*(_web_search(q) for q in queries))
        for query, results in zip(queries, results_list):
            if results:
                lines = [f"- [{r['title']}]({r['url']}): {r['body']}" for r in results]
                web_sections.append(f"**{query}:**\n" + "\n".join(lines))
    related_context = "\n\n".join(web_sections) if web_sections else "（无检索背景，仅凭论文解读）"

    # Step 3: generate the structured single-language (Chinese) interpretation.
    response = await complete_with_retry(
        ai_client,
        system=ARXIV_DETAIL_SYSTEM,
        user=ARXIV_DETAIL_USER.format(
            title=paper.title,
            authors=", ".join(paper.authors[:10]),
            categories=", ".join(paper.categories),
            published_at=paper.published_at.date().isoformat(),
            venue=paper.venue or "无",
            score=f"{paper.ai_relevance_score:.1f}" if paper.ai_relevance_score is not None else "—",
            reason=paper.ai_reason or "",
            abstract=(paper.abstract or "")[:3000],
            paper_text=full_text or "（无法获取论文全文，仅凭摘要解读）",
            related_context=related_context,
        ),
        # 11 层中文解读 + 关键词 + 创新等级的完整 JSON 常见 6-8k tokens；
        # 2048/4096 会把长论文的输出截断成不完整 JSON（unparseable response）。
        max_tokens=8192,
    )
    result = parse_json_response(response)
    if result is None:
        logger.warning("Could not parse detail enrichment for %s", paper.id)
        _mark_enrich_failure(paper, "detail", "unparseable response")
        return

    if result.get("keywords"):
        paper.keywords = [str(k) for k in result["keywords"][:10]]

    summary: Dict[str, Any] = {}
    for field in (
        "one_sentence_summary", "why_it_matters", "background",
        "previous_problem", "core_idea", "how_it_works",
        "technical_details", "experimental_evidence", "real_world_impact",
        "limitations",
    ):
        val = result.get(field)
        if val:
            summary[field] = str(val).strip()
    # innovation_level 是 {level, reason} 对象，原样保留在 ai_summary 中。
    innovation = result.get("innovation_level")
    if isinstance(innovation, dict) and innovation.get("level"):
        summary["innovation_level"] = innovation
    if summary:
        paper.ai_summary = summary
        # Enrichment succeeded — drop any previously-recorded failure marker
        # (appended after the scoring reason) so the reason stays clean.
        if paper.ai_reason and "[enrich" in paper.ai_reason:
            paper.ai_reason = paper.ai_reason.split("[enrich")[0].strip()


# arXiv 官方 HTML 版（较新论文）与 ar5iv（旧论文 fallback）全文抓取阈值。
_FULLTEXT_MIN_CHARS = 500       # 提取正文低于此长度视为失败
_FULLTEXT_MAX_CHARS = 15_000    # 喂给 AI 前截断，控制 token 成本


async def _fetch_paper_full_text(http_client: Any, paper: Paper) -> str:
    """Fetch the paper's full text from arXiv's HTML rendering.

    Tries the official ``https://arxiv.org/html/{id}`` rendering first, then
    falls back to ``https://ar5iv.labs.arxiv.org/html/{id}`` for older papers.
    Returns at most ``_FULLTEXT_MAX_CHARS`` chars of main-content text, or ""
    when nothing usable could be extracted (e.g. ``http_client`` is None in
    dry-run mode).
    """
    if http_client is None:
        return ""
    arxiv_id = paper.arxiv_id or paper.native_id
    if not arxiv_id:
        return ""
    urls = [
        f"https://arxiv.org/html/{arxiv_id}",
        f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    ]
    for url in urls:
        try:
            response = await http_client.get(url, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            text = trafilatura.extract(response.text)
        except httpx.HTTPStatusError as exc:
            # A 404 on arxiv.org/html/ is expected for papers submitted without
            # an HTML rendering — quietly fall through to the ar5iv mirror.
            # Anything else is a real fetch problem worth a traceback.
            if exc.response.status_code == 404:
                logger.debug("No HTML rendering for %s at %s", arxiv_id, url)
                continue
            logger.warning("Full-text fetch failed for %s", url, exc_info=True)
            continue
        except Exception:
            logger.warning("Full-text fetch failed for %s", url, exc_info=True)
            continue
        if text and len(text.strip()) >= _FULLTEXT_MIN_CHARS:
            return text.strip()[:_FULLTEXT_MAX_CHARS]
    return ""


async def _web_search(query: str, max_results: int = 3) -> list:
    """Search the web via DuckDuckGo (same pattern as ``src.ai.enricher``)."""
    try:
        stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            ddgs = DDGS()
            results = await asyncio.to_thread(ddgs.text, query, max_results=max_results)
        finally:
            sys.stderr.close()
            sys.stderr = stderr
    except Exception:
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
        for r in (results or [])
    ]


def _parse_featured_date(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored ``featured_date`` TEXT into an aware UTC datetime.

    Naive timestamps (no timezone suffix) are assumed UTC and normalized, so
    the value written back via ``_dt_iso`` keeps a consistent ``+00:00`` form
    (frontend string sorting relies on that).
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning("Unparseable featured_date %r ignored", value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _merge_existing_state(db: Any, papers: List[Paper], source: str = "arxiv") -> None:
    """Read back stored arXiv state into fresh candidates before the UPSERT.

    ``save_papers`` is a full-field UPSERT, so any candidate that already
    exists in the DB would have its stored AI/featured/translation fields
    clobbered by the empty fetch defaults. Re-apply stored state — score
    dedup (already-scored papers are not re-scored), already-featured
    preservation (they are not re-selected), and translation preservation.
    *source* scopes the read-back to the paper's own channel (``arxiv`` vs
    ``arxiv_fin``).

    Never overwrites a non-empty fresh value: fresh arXiv metadata wins;
    stored state only backfills fields the fetch leaves empty.
    """
    if db is None or not papers:
        return
    result = db.get_papers(source=source, per_page=10000)
    prior = {p["id"]: p for p in result.get("items", [])}
    for paper in papers:
        stored = prior.get(paper.id)
        if stored is None:
            continue

        # (1) Score dedup: read back an existing score instead of re-scoring.
        if paper.ai_relevance_score is None and stored.get("ai_relevance_score") is not None:
            paper.ai_relevance_score = stored["ai_relevance_score"]
            paper.ai_reason = stored.get("ai_reason")
            if paper.ai_score_breakdown is None and stored.get("ai_score_breakdown") is not None:
                paper.ai_score_breakdown = stored["ai_score_breakdown"]

        # (2) Already-featured: preserve status, date, and AI enrichment.
        if stored.get("is_featured"):
            paper.is_featured = True
            paper.featured_date = _parse_featured_date(stored.get("featured_date")) or paper.featured_date
            if not paper.keywords and stored.get("keywords"):
                paper.keywords = stored["keywords"]
            if paper.ai_summary is None and stored.get("ai_summary") is not None:
                paper.ai_summary = stored["ai_summary"]

        # (3) Translations: backfilled by --translate-existing; keep them so
        # the UPSERT does not clear them.
        if paper.title_zh is None and stored.get("title_zh"):
            paper.title_zh = stored["title_zh"]
        if paper.abstract_zh is None and stored.get("abstract_zh"):
            paper.abstract_zh = stored["abstract_zh"]
        if paper.original_language is None and stored.get("original_language"):
            paper.original_language = stored["original_language"]

        # (4) Metadata fallback: github_url / venue are recomputed fresh by
        # apply_rules; only backfill when the fresh value came out empty.
        if paper.github_url is None and stored.get("github_url"):
            paper.github_url = stored["github_url"]
        if paper.venue is None and stored.get("venue"):
            paper.venue = stored["venue"]


async def _run_group(
    ai_client: AIClient,
    http_client: Any,
    papers: List[Paper],
    cfg: ArxivSourceConfig,
    db: Optional[Any],
    source: str,
    no_translate: bool = False,
) -> WeeklyArxivResult:
    """Run the rule-filter → score → feature → enrich → save flow for one group.

    *papers* are already fetched and window-filtered; the group keeps its own
    keyword filter / featured pool and is persisted under *source*. *db* is
    ``None`` in dry-run mode — nothing is written, no prior featured state is
    consulted. When *no_translate* is False (default), the featured set is AI-
    translated to Chinese (``title_zh``/``abstract_zh``) like the classic/HF
    sources.
    """
    filtered = apply_rules(papers, cfg)
    concurrency = _get_concurrency(ai_client)

    # Read back stored score/featured/translation state (score dedup + no
    # re-featuring). Called after apply_rules so fresh venue/github are
    # computed first and only backfilled when empty.
    if db is not None:
        _merge_existing_state(db, filtered, source)

    # Only AI-score papers that are new (no score yet) and not already featured.
    to_score = [p for p in filtered if p.ai_relevance_score is None and not p.is_featured]
    await score_papers(ai_client, to_score, concurrency)

    scored_pool = sorted(
        (p for p in filtered if p.ai_relevance_score is not None),
        key=lambda p: p.ai_relevance_score,
        reverse=True,
    )
    # Already-featured papers are never re-selected (keeps their original batch).
    eligible = [p for p in scored_pool if not p.is_featured]
    featured = eligible[: cfg.featured_count]

    today = datetime.now(timezone.utc).date()
    for p in featured:
        p.is_featured = True
        p.featured_date = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    # Only enrich the newly featured set.
    await enrich_featured(ai_client, http_client, featured, concurrency)
    enrich_failed = sum(1 for p in featured if p.ai_summary is None)
    enriched_new = len(featured) - enrich_failed

    # Same AI translation as the classic/HF sources: generate title_zh /
    # abstract_zh for the featured set only. Featured is a subset reference of
    # filtered, so translations are persisted with the save below.
    if not no_translate and featured:
        await translate_papers(ai_client, featured, concurrency)
        translated_new = sum(1 for p in featured if p.title_zh)
        translate_failed = len(featured) - translated_new
    else:
        translated_new = 0
        translate_failed = 0

    saved_total = 0
    if db is not None:
        saved_total = db.save_papers(filtered)

    return WeeklyArxivResult(
        fetched=len(papers),
        after_filter=len(filtered),
        scored=len(scored_pool),
        scored_new=len(to_score),
        featured=featured,
        enriched_new=enriched_new,
        enrich_failed=enrich_failed,
        translated_new=translated_new,
        translate_failed=translate_failed,
        saved_total=saved_total,
    )


async def run_weekly_arxiv(
    ai_client: AIClient,
    http_client: Any,
    cfg: ArxivSourceConfig,
    db: Optional[Any],
    no_translate: bool = False,
) -> WeeklyArxivResult:
    """Run the arXiv weekly pipeline for the general AI pool (source="arxiv").

    Backward-compatible single-group entry point; ``run_weekly_arxiv_all`` runs
    both the general and the AI+Finance groups off one shared fetch.
    """
    raw = await fetch_recent(
        http_client, cfg.categories, cfg.max_results_per_category, cfg.window_days,
    )
    return await _run_group(
        ai_client, http_client, raw, cfg, db, "arxiv", no_translate=no_translate,
    )


async def run_weekly_arxiv_all(
    ai_client: AIClient,
    http_client: Any,
    cfg: ArxivSourceConfig,
    db: Optional[Any],
    no_translate: bool = False,
) -> Dict[str, WeeklyArxivResult]:
    """Run the full arXiv weekly pipeline for every configured channel in one fetch.

    Categories are fetched together (``categories + finance_categories``), then
    split by q-fin category membership: the general AI pool (source="arxiv") and
    — when ``cfg.finance_enabled`` — the AI+Finance group (source="arxiv_fin").
    Each group runs the shared ``_run_group`` flow with its own keyword filter
    and featured count. Returns a dict keyed by source. *no_translate* skips the
    AI translation step for both channels.
    """
    categories = list(cfg.categories) + list(cfg.finance_categories)
    raw = await fetch_recent(
        http_client, categories, cfg.max_results_per_category, cfg.window_days,
    )
    # Split only when the finance channel is on — otherwise every fetched
    # paper stays in the general pool (finance_categories would drop papers).
    if cfg.finance_enabled:
        general, finance = split_by_finance(raw, cfg.finance_categories)
    else:
        general, finance = raw, []

    results: Dict[str, WeeklyArxivResult] = {
        "arxiv": await _run_group(
            ai_client, http_client, general, cfg, db, "arxiv",
            no_translate=no_translate,
        ),
    }
    if cfg.finance_enabled and finance:
        fin_cfg = cfg.model_copy(update={
            "keyword_whitelist": cfg.finance_keyword_whitelist,
            "featured_count": cfg.finance_featured_count,
        })
        finance = [_rekey_source(p, FINANCE_SOURCE) for p in finance]
        results[FINANCE_SOURCE] = await _run_group(
            ai_client, http_client, finance, fin_cfg, db, FINANCE_SOURCE,
            no_translate=no_translate,
        )
    return results
