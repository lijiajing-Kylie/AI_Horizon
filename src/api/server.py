"""FastAPI application for querying Horizon pipeline results."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from ..storage.db import HorizonDB

app = FastAPI(
    title="Horizon API",
    description="REST API for AI-curated news aggregation data",
    version="0.1.0",
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


@app.on_event("shutdown")
def _shutdown() -> None:
    db.close()


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


@app.get("/api/runs/dates")
def run_dates(limit: int = Query(30, ge=1, le=365)) -> list[str]:
    """List dates that have pipeline data."""
    return db.get_run_dates(limit=limit)


@app.get("/api/daily/{date}")
def daily_detail(date: str) -> dict:
    """Get all items and stats for a specific date."""
    result = db.get_items(run_date=date, per_page=200)
    stats = db.get_stats(run_date=date)
    tags = db.get_tags(run_date=date)
    topics = db.get_topics(grouped=True)
    return {
        "date": date,
        "stats": stats,
        "tags": tags,
        "topics": topics,
        "items": result["items"],
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


def main() -> None:
    """Entry point for `horizon-api` CLI."""
    import uvicorn

    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True)
