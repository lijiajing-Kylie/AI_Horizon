"""FastAPI application for querying Horizon pipeline results."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse

from ..ai.content_selection import build_analysis_input, build_enrichment_input
from ..ai.utils import split_content_and_comments
from ..content_extractor import clean_article_content
from ..models import ContentItem
from ..storage.db import HorizonDB

# Other Horizon entry points (main.py, wizard.py, webhook_cli.py, the MCP
# adapter) each call load_dotenv() themselves; the API server historically
# didn't need to since it never read secrets — it does now, for
# HORIZON_API_ENV below, so it needs the same call.
load_dotenv()


# ── dev-environment gate for the scrape-diagnostics panel ────────────────
#
# Horizon has no other dev/prod distinction anywhere in the backend today
# (horizon-api's entry point hardcodes reload=True regardless of
# environment). HORIZON_API_ENV is a new, narrowly-scoped env var that only
# controls whether /api/items/{id}?include_debug=true is allowed to attach
# the debug block — it has no effect on scraping, scoring, or any other
# pipeline behavior. Defaults to "production" (fail-closed): an unset or
# misconfigured deployment never leaks diagnostics.


def _debug_env_enabled() -> bool:
    return os.environ.get("HORIZON_API_ENV", "production").strip().lower() in (
        "development", "dev", "local",
    )


# ── content object builder ──────────────────────────────────────────────


def _build_content(item: dict) -> dict:
    """Extract a clean bilingual content block from item metadata.

    Returns a dict with ``original_language``, ``default_language``,
    ``is_ai_translated``, and a ``content`` sub-dict keyed by language.
    """
    meta: dict = item.get("metadata") or {}

    original = meta.get("original_language", "unknown")
    available = meta.get("available_languages", [])
    if not available:
        # Infer from metadata fields
        if meta.get("title_zh"):
            available.append("zh")
        if meta.get("title_en"):
            available.append("en")
        if not available:
            available.append("en")

    content: dict[str, dict] = {}
    for lang in available:
        content[lang] = {
            "title": meta.get(f"title_{lang}") or item.get("title", ""),
            "summary": (
                meta.get(f"detailed_summary_{lang}")
                or item.get("ai_summary", "")
            ),
            "reason": (
                meta.get(f"reason_{lang}")
                or item.get("ai_reason", "")
            ),
            "community_discussion": (
                meta.get(f"community_discussion_{lang}")
                or meta.get("community_discussion", "")
            ),
        }

    return {
        "original_language": original,
        "default_language": meta.get("default_display_language", "zh"),
        "is_ai_translated": meta.get("is_ai_translated", False),
        "content": content,
        "enrichment_sources": meta.get("enrichment_sources", []),
        "discussion_url": meta.get("discussion_url"),
        "source_provenance": meta.get("source_provenance"),
        "source_attribution": meta.get("source_attribution"),
    }


def _attach_content(item: dict) -> dict:
    """Attach the ``content`` block plus raw/clean article text (mutates and returns).

    ``raw_content`` is the DB's own ``raw_content`` column — trafilatura's
    verbatim extraction output, populated only when extraction succeeded.
    Rows written before that column existed have it as ``NULL``; the
    fallback to ``content`` (the legacy ambiguous field) keeps those old
    rows serving the same text as before this column existed.
    ``clean_content`` is derived from ``raw_content`` with scraping
    boilerplate stripped, and is what the frontend should render.

    ``raw_html``/``display_html`` (structured article HTML) pass through
    unchanged from the DB row — they're already present on ``item`` here,
    computed once at extraction time rather than per-request like
    ``clean_content``. The frontend should prefer ``display_html`` and only
    fall back to ``clean_content`` when it's empty (e.g. extraction failed
    or found no structured content).

    Some scrapers (Hacker News, Reddit, Twitter) append a ``--- Top
    Comments ---`` section to ``content`` for AI scoring/enrichment context.
    That section is dropped before computing ``clean_content`` — it's
    community discussion, not article body, and must never be what the
    detail page renders as "正文" (a link post with no article text but
    fetched comments would otherwise show the comments as if they were the
    article).
    """
    item["content_block"] = _build_content(item)
    item["raw_content"] = item.get("raw_content") or item.get("content")
    main_content, _comments = split_content_and_comments(item.get("raw_content"))
    item["clean_content"] = clean_article_content(main_content, title=item.get("title"))
    return item


# ── scrape-diagnostics block (dev-only) ───────────────────────────────────
#
# Read-only: every value below is either already persisted on the DB row
# (or folded into metadata_json by storage/db.py's save_items) or the
# output of a pure function applied to that same persisted data. Nothing
# here re-fetches the item's URL or calls the AI, and nothing here mutates
# the DB.


def _reconstruct_content_item(item: dict) -> ContentItem:
    """Rehydrate a ``ContentItem`` from a DB row dict.

    ``resolve_content``/``build_analysis_input``/``build_enrichment_input``
    (in ``src/ai/content_selection.py``) are written against the
    ``ContentItem`` model, reading attributes like ``.raw_content`` and
    ``.rss_summary``. The API layer only ever sees the flattened dict shape
    ``HorizonDB`` returns — where extraction-provenance fields have no
    dedicated columns and live inside ``metadata`` instead (see
    ``storage/db.py:save_items``). This rebuilds the shape those functions
    expect, so the diagnostics endpoint reuses the exact same
    content-selection logic the real pipeline runs, instead of a second
    hand-written copy of it.
    """
    meta: dict = dict(item.get("metadata") or {})
    return ContentItem(
        id=item["id"],
        source_type=item["source_type"],
        title=item.get("title") or "",
        url=item["url"],
        content=item.get("content"),
        raw_content=item.get("raw_content"),
        rss_summary=meta.get("rss_summary"),
        content_source=meta.get("content_source"),
        extraction_status=meta.get("extraction_status"),
        extraction_error=meta.get("extraction_error"),
        http_status=meta.get("http_status"),
        final_url=meta.get("final_url"),
        text_length=meta.get("text_length"),
        extractor_version=meta.get("extractor_version"),
        author=item.get("author"),
        published_at=item["published_at"],
        metadata=meta,
        ai_relevant=item.get("ai_relevant"),
        ai_score=item.get("ai_score"),
        ai_reason=item.get("ai_reason"),
        ai_summary=item.get("ai_summary"),
        ai_tags=item.get("ai_tags") or [],
    )


def _infer_translation_status(item: dict, meta: dict) -> tuple[str, Optional[str]]:
    """Infer the article-body HTML translation outcome.

    No dedicated status field is persisted for this stage — the pipeline
    (``ai/enricher.py:_translate_html``) only ever writes the resulting
    ``display_html_zh`` (or leaves it unset on failure), so this walks the
    same decision path the enricher does and reconstructs which branch it
    must have taken. Branches marked "推断值" below can't be distinguished
    from stored data alone (e.g. an AI/parse failure looks identical to a
    guard-rail rejection, and a dropped item looks identical to "never
    reached enrichment" only because ``selected`` happens to correlate with
    that today) — the returned reason string says so explicitly rather than
    presenting a guess as a recorded fact.
    """
    display_html = item.get("display_html")
    display_html_zh = item.get("display_html_zh")
    original_language = meta.get("original_language", "unknown")

    if not display_html or not display_html.strip():
        return "empty_input", "display_html 为空，没有可翻译的正文"

    if not item.get("selected", False):
        return (
            "not_attempted",
            "推断值：该条目未被选入最终简报（selected=false），从未进入 enrichment/翻译阶段；"
            "管道本身没有为此单独记录状态",
        )

    if original_language == "zh":
        return (
            "skipped_already_chinese",
            "原文已是中文，enricher._translate_html 直接复用 display_html，未实际调用翻译",
        )

    if not display_html_zh or not display_html_zh.strip():
        return (
            "failed",
            "推断值：翻译已尝试但未产出结果（AI 调用失败/JSON 解析失败/过清洗保护/图片数量校验未通过均可能导致），"
            "具体失败原因未持久化，translate_display_html() 失败时只写运行时 debug 日志，不落库",
        )

    if display_html_zh.strip() == display_html.strip():
        return (
            "fallback_to_original",
            "display_html_zh 与 display_html 内容完全相同，但原文非中文——"
            "当前管道代码路径不会主动产生这个状态，多半是历史数据或手工改库导致",
        )

    return "success", None


def _build_debug_block(item: dict) -> dict:
    """Assemble the scrape/AI-input diagnostics block for one item (dev-only)."""
    meta: dict = item.get("metadata") or {}

    raw_html = item.get("raw_html")
    raw_content = item.get("raw_content")
    clean_content = item.get("clean_content")
    display_html = item.get("display_html")
    display_html_zh = item.get("display_html_zh")

    provenance = meta.get("source_provenance") or {}
    source_name = provenance.get("primary_source_name") or item.get("author") or item.get("source_type")

    try:
        content_item = _reconstruct_content_item(item)
        analysis_input = build_analysis_input(content_item)
        enrichment_input = build_enrichment_input(content_item)
        analysis_block = {
            "input": analysis_input.text,
            "input_length": analysis_input.sent_length,
            "content_source": analysis_input.content_source,
            "original_length": analysis_input.original_length,
            "sent_length": analysis_input.sent_length,
            "truncation_limit": analysis_input.truncation_limit,
            "source_note": analysis_input.source_note,
        }
        enrichment_block = {
            "input": enrichment_input.text,
            "input_length": enrichment_input.sent_length,
            "content_source": enrichment_input.content_source,
            "original_length": enrichment_input.original_length,
            "sent_length": enrichment_input.sent_length,
            "truncation_limit": enrichment_input.truncation_limit,
            "source_note": enrichment_input.source_note,
        }
    except Exception as exc:
        # Never let a diagnostics-only computation break the item response.
        placeholder = {
            "input": None, "input_length": 0, "content_source": None,
            "original_length": 0, "sent_length": 0, "truncation_limit": None,
            "source_note": f"无法重建 AI 输入预览：{exc}",
        }
        analysis_block = dict(placeholder)
        enrichment_block = dict(placeholder)

    translation_status, translation_skipped_reason = _infer_translation_status(item, meta)

    return {
        "source": {
            "original_title": item.get("title"),
            "original_url": item.get("url"),
            "rss_summary": meta.get("rss_summary"),
            "source_name": source_name,
            "published_at": item.get("published_at"),
        },
        "fetch": {
            "http_status": meta.get("http_status"),
            # Not persisted anywhere in the current pipeline — capturing it
            # would require touching content_extractor.py/orchestrator.py,
            # out of scope for this read-only diagnostics addition.
            "content_type": None,
            "final_url": meta.get("final_url"),
            "extraction_status": meta.get("extraction_status"),
            "extraction_error": meta.get("extraction_error"),
            "content_source": meta.get("content_source"),
            "text_length": meta.get("text_length"),
            "extracted_at": meta.get("extracted_at"),
            "extractor_version": meta.get("extractor_version"),
        },
        "raw_html": raw_html,
        "raw_html_length": len(raw_html or ""),
        "raw_content": raw_content,
        "raw_content_length": len(raw_content or ""),
        "clean_content": clean_content,
        "clean_content_length": len(clean_content or ""),
        "display_html": display_html,
        "display_html_length": len(display_html or ""),
        "display_html_zh": display_html_zh,
        "display_html_zh_length": len(display_html_zh or ""),
        "analysis": analysis_block,
        "enrichment": enrichment_block,
        "translation": {
            "status": translation_status,
            "source": "display_html",
            "input": display_html,
            "input_length": len(display_html or ""),
            "output": display_html_zh,
            "output_length": len(display_html_zh or ""),
            # translate_display_html() never persists a failure reason —
            # only a runtime logger.debug() call, which this can't recover.
            "error": None,
            "skipped_reason": translation_skipped_reason,
        },
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the Horizon API."""
    yield
    db.close()


app = FastAPI(
    title="Horizon API",
    description="REST API for AI-curated news aggregation data",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

db = HorizonDB()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@app.get("/api/items")
def list_items(
    run_date: Optional[str] = Query(None, description="Filter by run date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Filter by source category"),
    tag: Optional[str] = Query(None, description="Filter by AI tag"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    search: Optional[str] = Query(None, description="Full-text search"),
    min_score: Optional[float] = Query(None, ge=0, le=10, description="Minimum AI score"),
    sort: str = Query("ai_score", description="Sort field"),
    order: str = Query("desc", description="Sort direction (asc/desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict:
    """Paginated list of scored content items with optional filters."""
    return db.get_items(
        run_date=run_date,
        category=category,
        tag=tag,
        source_type=source_type,
        search=search,
        min_score=min_score,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )


@app.get("/api/items/{item_id}")
def get_item(
    item_id: str,
    include_debug: bool = Query(
        False,
        description=(
            "Attach a full scrape/AI-input diagnostics block. Dev-only: "
            "ignored (debug omitted entirely) unless the server is running "
            "with HORIZON_API_ENV=development."
        ),
    ),
) -> dict:
    """Get a single item by ID."""
    item = db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    item = _attach_content(item)
    if include_debug and _debug_env_enabled():
        item["debug"] = _build_debug_block(item)
    return item


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@app.get("/api/tags")
def list_tags(
    run_date: Optional[str] = Query(None, description="Filter by run date"),
    min_count: int = Query(1, ge=1, description="Minimum occurrence count"),
) -> list[dict]:
    """List all AI-generated tags with occurrence counts."""
    return db.get_tags(run_date=run_date, min_count=min_count)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@app.get("/api/categories")
def category_counts(
    run_date: Optional[str] = Query(None, description="Filter by run date"),
) -> list[dict]:
    """Get item counts grouped by source category."""
    return db.get_category_counts(run_date=run_date)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@app.get("/api/topics")
def list_topics() -> dict:
    """Get all active topics grouped by group_name.

    Each topic includes a ``count`` of associated news items.
    """
    return db.get_topics(grouped=True)


@app.get("/api/topics/{slug}")
def get_topic(slug: str) -> dict:
    """Get a single topic by slug."""
    topic = db.get_topic_by_slug(slug)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.get("/api/topics/{slug}/news")
def topic_news(
    slug: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    sort: str = Query("ai_score", description="Sort field"),
    order: str = Query("desc", description="Sort direction (asc/desc)"),
) -> dict:
    """Get paginated news items for a specific topic by slug."""
    result = db.get_topic_news(
        slug=slug, page=page, per_page=per_page, sort=sort, order=order
    )
    if result["topic"] is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return result


# ---------------------------------------------------------------------------
# Daily runs
# ---------------------------------------------------------------------------

@app.get("/api/runs")
def list_runs(limit: int = Query(30, ge=1, le=100)) -> list[dict]:
    """List recent daily pipeline runs."""
    return db.get_runs(limit=limit)


@app.get("/api/daily")
def list_daily(limit: int = Query(30, ge=1, le=100)) -> dict:
    """List available daily reports."""
    runs = db.get_runs(limit=limit)
    return {
        "reports": [
            {
                "date": r["date"],
                "total_fetched": r["total_fetched"],
                "total_selected": r["total_selected"],
                "languages": r["languages"],
            }
            for r in runs
        ]
    }


@app.get("/api/runs/dates")
def run_dates(limit: int = Query(30, ge=1, le=365)) -> list[str]:
    """List dates that have pipeline data."""
    return db.get_run_dates(limit=limit)


@app.get("/api/daily/{date}")
def daily_detail(date: str) -> dict:
    """Get all items and stats for a specific date."""
    # `date` is a path param typed `str`, so FastAPI never hands us a
    # datetime.date here — but normalize defensively in case this is ever
    # called with one (e.g. from other Python code), since sqlite3 can't
    # bind date/datetime objects directly.
    run_date = date.isoformat() if hasattr(date, "isoformat") else str(date)

    result = db.get_items(run_date=run_date, per_page=200)
    stats = db.get_stats(run_date=run_date)
    tags = db.get_tags(run_date=run_date)
    topics = db.get_topics(grouped=True)
    return {
        "date": run_date,
        "stats": stats,
        "tags": tags,
        "topics": topics,
        "items": [_attach_content(it) for it in result["items"]],
        "total": result["total"],
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def get_stats(
    run_date: Optional[str] = Query(None, description="Filter by run date"),
) -> dict:
    """Get aggregate statistics."""
    return db.get_stats(run_date=run_date)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
def search_items(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    """Full-text search across items."""
    return db.search(q, limit=limit)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    """Health check endpoint."""
    runs = db.get_runs(limit=1)
    return {
        "status": "ok",
        "db_path": str(db.db_path),
        "latest_run": runs[0]["date"] if runs else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Web frontend (server-rendered HTML)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def web_index(
    request: Request,
    date: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """Main page: item cards with tag/category filter and date navigation."""
    result = db.get_items(
        run_date=date,
        tag=tag,
        category=category,
        page=page,
        per_page=30,
    )
    tags = db.get_tags(run_date=date)
    categories = db.get_category_counts(run_date=date)
    dates = db.get_run_dates(limit=30)
    topics_summary = db.get_topics(grouped=True)

    # Compute average score
    scores = [item["ai_score"] for item in result["items"] if item["ai_score"]]
    avg_score = f"{sum(scores) / len(scores):.1f}" if scores else "—"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": result["items"],
            "total": result["total"],
            "page": result["page"],
            "pages": result["pages"],
            "date": date or "",
            "tags": tags,
            "categories": categories,
            "dates": dates,
            "selected_tag": tag or "",
            "selected_category": category or "",
            "avg_score": avg_score,
            "topics": topics_summary.get("groups", []),
        },
    )


@app.get("/topics", response_class=HTMLResponse)
def web_topics(request: Request) -> HTMLResponse:
    """Topic overview page: groups × topic cards with news counts."""
    topics_data = db.get_topics(grouped=True)
    dates = db.get_run_dates(limit=7)
    return templates.TemplateResponse(
        "topics.html",
        {
            "request": request,
            "groups": topics_data.get("groups", []),
            "dates": dates,
        },
    )


@app.get("/topics/{slug}", response_class=HTMLResponse)
def web_topic_news(
    request: Request,
    slug: str,
    page: int = Query(1, ge=1),
    sort: str = Query("ai_score"),
    order: str = Query("desc"),
) -> HTMLResponse:
    """Topic news page: paginated item list for a single topic."""
    result = db.get_topic_news(
        slug=slug, page=page, per_page=30, sort=sort, order=order,
    )
    if result["topic"] is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    dates = db.get_run_dates(limit=7)
    return templates.TemplateResponse(
        "topic_news.html",
        {
            "request": request,
            "topic": result["topic"],
            "items": result["items"],
            "total": result["total"],
            "page": result["page"],
            "pages": result["pages"],
            "sort": sort,
            "order": order,
            "dates": dates,
        },
    )


_DEBUG_FRONTEND = Path(__file__).resolve().parent.parent.parent / "debug-frontend"


@app.get("/debug", response_class=HTMLResponse)
def debug_dashboard() -> FileResponse:
    """Serve the debug frontend dashboard (same-origin — no CORS needed)."""
    return FileResponse(str(_DEBUG_FRONTEND / "index.html"))


def main() -> None:
    """Entry point for `horizon-api` CLI."""
    import uvicorn

    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True)
