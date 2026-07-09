"""FastAPI application for querying Horizon pipeline results."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse

from ..ai.utils import split_content_and_comments
from ..content_extractor import clean_article_content
from ..storage.db import HorizonDB


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

    ``raw_content`` mirrors the untouched scraped text (for traceability);
    ``clean_content`` is derived from it with scraping boilerplate stripped,
    and is what the frontend should render.

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
    item["raw_content"] = item.get("content")
    main_content, _comments = split_content_and_comments(item.get("content"))
    item["clean_content"] = clean_article_content(main_content, title=item.get("title"))
    return item


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
def get_item(item_id: str) -> dict:
    """Get a single item by ID."""
    item = db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _attach_content(item)


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
