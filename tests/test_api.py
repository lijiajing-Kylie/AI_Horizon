"""Integration tests for the Horizon FastAPI server."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.models import ContentItem, SourceType
from src.storage.db import HorizonDB
from src.api.server import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Ensure src/api/templates/ is on the Jinja2 search path when running tests
# from the repo root. The server resolves templates relative to __file__,
# so they work as long as we import the real app.
#
# If templates are missing, HTML-page tests skip gracefully.


def _make_item(
    id: str = "hn:top:1",
    source_type: SourceType = SourceType.HACKERNEWS,
    title: str = "Test Article",
    url: str = "https://example.com/article-1",
    ai_score: float | None = 8.5,
    ai_tags: list[str] | None = None,
    ai_summary: str | None = "A summary.",
    category: str | None = None,
    ai_relevant: bool | None = True,
) -> ContentItem:
    metadata: dict = {}
    if category:
        metadata["category"] = category
    return ContentItem(
        id=id,
        source_type=source_type,
        title=title,
        url=url,
        content="Sample content.",
        author="test-author",
        published_at=datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 6, 10, 5, 0, tzinfo=timezone.utc),
        ai_relevant=ai_relevant,
        ai_score=ai_score,
        ai_reason="Important.",
        ai_summary=ai_summary,
        ai_tags=ai_tags or ["AI", "tech"],
        metadata=metadata,
    )


def _seed_items(db: HorizonDB, run_date: str = "2026-07-06") -> list[ContentItem]:
    items = [
        _make_item(
            id="hn:top:1",
            source_type=SourceType.HACKERNEWS,
            title="HN Article Alpha",
            url="https://example.com/alpha",
            ai_score=9.0,
            ai_tags=["AI", "startups"],
            ai_summary="Alpha summary with unique keyword zeta.",
            category="tech",
        ),
        _make_item(
            id="reddit:ml:2",
            source_type=SourceType.REDDIT,
            title="Reddit ML Post",
            url="https://example.com/ml",
            ai_score=7.5,
            ai_tags=["ML", "research"],
            ai_summary="Reddit summary text.",
            category="research",
        ),
        _make_item(
            id="rss:blog:3",
            source_type=SourceType.RSS,
            title="RSS Blog Update",
            url="https://example.com/blog",
            ai_score=6.0,
            ai_tags=["tech", "open source"],
            ai_summary="RSS blog summary.",
            category="tech",
        ),
    ]
    db.save_items(items, run_date=run_date, total_fetched=15)
    return items


def _seed_topics(db: HorizonDB) -> None:
    db.seed_topics([
        {
            "name": "AI",
            "slug": "ai",
            "group_name": "Technology",
            "description": "Artificial Intelligence topics",
            "keywords": ["AI", "ML"],
            "aliases": [],
            "sort_order": 1,
            "is_active": 1,
        },
        {
            "name": "Startups",
            "slug": "startups",
            "group_name": "Technology",
            "description": "Startup ecosystem",
            "keywords": ["startup"],
            "aliases": [],
            "sort_order": 2,
            "is_active": 1,
        },
    ])


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a TestClient wired to a temp-file HorizonDB with seed data.

    We do NOT use ``with TestClient(app)`` because the lifespan shutdown
    handler runs ``db.close()`` in a different thread, which SQLite rejects
    unless ``check_same_thread=False`` is set. Instead we create a plain
    TestClient and manage the DB lifecycle ourselves.
    """
    db = HorizonDB(db_path=str(tmp_path / "test.db"))

    # Seed items + topics + a topic association
    _seed_items(db)
    _seed_topics(db)
    db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.95, "reason": "Obvious"}])

    # Override the module-level db instance
    import src.api.server as server_module

    monkeypatch.setattr(server_module, "db", db)

    c = TestClient(app)
    yield c
    db.close()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db_path"]  # Should be a non-empty string
        assert data["latest_run"] == "2026-07-06"
        assert "timestamp" in data

    def test_health_empty_db(self, tmp_path, monkeypatch):
        """Health check works even with no runs."""
        db = HorizonDB(db_path=str(tmp_path / "empty.db"))
        import src.api.server as server_module
        monkeypatch.setattr(server_module, "db", db)

        c = TestClient(app)
        r = c.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["latest_run"] is None
        db.close()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class TestItems:
    def test_list_items(self, client):
        r = client.get("/api/items")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["pages"] == 1
        # Default sort: ai_score DESC
        assert data["items"][0]["ai_score"] == 9.0

    def test_list_items_pagination(self, client):
        r = client.get("/api/items?per_page=1&page=2")
        assert r.status_code == 200
        data = r.json()
        assert data["per_page"] == 1
        assert data["page"] == 2
        assert len(data["items"]) == 1

    def test_list_items_filter_source_type(self, client):
        r = client.get("/api/items?source_type=hackernews")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["source_type"] == "hackernews"

    def test_list_items_filter_min_score(self, client):
        r = client.get("/api/items?min_score=8")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == "hn:top:1"

    def test_list_items_filter_category(self, client):
        r = client.get("/api/items?category=tech")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

    def test_list_items_filter_tag(self, client):
        r = client.get("/api/items?tag=ML")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == "reddit:ml:2"

    def test_list_items_search(self, client):
        r = client.get("/api/items?search=keyword+zeta")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1

    def test_list_items_sort_asc(self, client):
        r = client.get("/api/items?sort=ai_score&order=asc")
        assert r.status_code == 200
        items = r.json()["items"]
        assert items[0]["ai_score"] == 6.0

    def test_list_items_sort_published(self, client):
        r = client.get("/api/items?sort=published_at&order=desc")
        assert r.status_code == 200
        assert r.json()["total"] == 3

    def test_list_items_invalid_page_clamped(self, client):
        """query(ge=1) defaults min, but FastAPI still validates the input."""
        r = client.get("/api/items?page=0")
        assert r.status_code == 422  # pydantic validation error

    def test_get_item_found(self, client):
        r = client.get("/api/items/hn:top:1")
        assert r.status_code == 200
        item = r.json()
        assert item["id"] == "hn:top:1"
        assert item["title"] == "HN Article Alpha"
        assert "topics" in item
        assert len(item["topics"]) == 1
        assert item["topics"][0]["slug"] == "ai"

    def test_get_item_not_found(self, client):
        r = client.get("/api/items/nonexistent-id")
        assert r.status_code == 404
        assert r.json()["detail"] == "Item not found"


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


class TestTags:
    def test_list_tags(self, client):
        r = client.get("/api/tags")
        assert r.status_code == 200
        tags = r.json()
        assert isinstance(tags, list)
        assert len(tags) >= 1
        for tag in tags:
            assert "tag" in tag
            assert "count" in tag

    def test_list_tags_date_filtered(self, client):
        r = client.get("/api/tags?run_date=2026-07-06")
        assert r.status_code == 200
        tags = r.json()
        assert len(tags) >= 1

    def test_list_tags_min_count(self, client):
        r = client.get("/api/tags?min_count=100")
        assert r.status_code == 200
        tags = r.json()
        assert tags == []


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class TestCategories:
    def test_category_counts(self, client):
        r = client.get("/api/categories")
        assert r.status_code == 200
        categories = r.json()
        assert isinstance(categories, list)
        count_map = {c["category"]: c["count"] for c in categories}
        assert count_map["tech"] == 2
        assert count_map["research"] == 1

    def test_category_counts_date_filtered(self, client):
        r = client.get("/api/categories?run_date=2026-07-06")
        assert r.status_code == 200
        assert len(r.json()) == 2  # tech, research


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TestTopics:
    def test_list_topics(self, client):
        r = client.get("/api/topics")
        assert r.status_code == 200
        data = r.json()
        assert "groups" in data
        groups = data["groups"]
        assert len(groups) == 1  # Only "Technology" group
        assert groups[0]["group_name"] == "Technology"
        assert len(groups[0]["topics"]) == 2
        # AI topic has count=1 (from the seeded association)
        ai_topic = next(t for t in groups[0]["topics"] if t["slug"] == "ai")
        assert ai_topic["count"] == 1

    def test_get_topic_found(self, client):
        r = client.get("/api/topics/ai")
        assert r.status_code == 200
        topic = r.json()
        assert topic["slug"] == "ai"
        assert topic["name"] == "AI"

    def test_get_topic_not_found(self, client):
        r = client.get("/api/topics/nonexistent")
        assert r.status_code == 404
        assert r.json()["detail"] == "Topic not found"

    def test_topic_news(self, client):
        r = client.get("/api/topics/ai/news")
        assert r.status_code == 200
        data = r.json()
        assert data["topic"]["slug"] == "ai"
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "hn:top:1"

    def test_topic_news_not_found(self, client):
        r = client.get("/api/topics/nonexistent/news")
        assert r.status_code == 404
        assert r.json()["detail"] == "Topic not found"

    def test_topic_news_pagination(self, client):
        # Associate a second item with the "ai" topic so we have 2 items
        import src.api.server as server_module
        db = server_module.db
        db.save_news_topics("rss:blog:3", [{"slug": "ai", "confidence": 0.5}])

        r = client.get("/api/topics/ai/news?per_page=1&page=2")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        assert data["pages"] == 2
        assert len(data["items"]) <= 1


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class TestRuns:
    def test_list_runs(self, client):
        r = client.get("/api/runs")
        assert r.status_code == 200
        runs = r.json()
        assert isinstance(runs, list)
        assert len(runs) >= 1
        assert runs[0]["date"] == "2026-07-06"
        assert "total_fetched" in runs[0]
        assert "languages" in runs[0]

    def test_run_dates(self, client):
        r = client.get("/api/runs/dates")
        assert r.status_code == 200
        dates = r.json()
        assert isinstance(dates, list)
        assert "2026-07-06" in dates


# ---------------------------------------------------------------------------
# Daily detail
# ---------------------------------------------------------------------------


class TestDailyDetail:
    def test_daily_detail(self, client):
        r = client.get("/api/daily/2026-07-06")
        assert r.status_code == 200
        data = r.json()
        assert data["date"] == "2026-07-06"
        assert "stats" in data
        assert "tags" in data
        assert "topics" in data
        assert "items" in data
        assert data["total"] == 3

    def test_daily_detail_no_data(self, client):
        r = client.get("/api/daily/2099-01-01")
        assert r.status_code == 200
        data = r.json()
        assert data["date"] == "2099-01-01"
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats["total_items"] == 3
        assert stats["avg_score"] is not None
        assert stats["max_score"] == 9.0
        assert stats["source_types"] >= 1


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search(self, client):
        r = client.get("/api/search?q=Alpha")
        assert r.status_code == 200
        results = r.json()
        assert isinstance(results, list)
        assert len(results) >= 1
        assert any("Alpha" in item["title"] for item in results)

    def test_search_missing_query(self, client):
        r = client.get("/api/search")
        assert r.status_code == 422

    def test_search_no_results(self, client):
        r = client.get("/api/search?q=zzz_nonexistent_term_xyz")
        assert r.status_code == 200
        results = r.json()
        assert results == []


# ---------------------------------------------------------------------------
# HTML pages (web frontend)
# ---------------------------------------------------------------------------


class TestWebIndex:
    def test_web_index(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # Should contain seed data rendered into the template
        assert "HN Article Alpha" in r.text

    def test_web_index_filtered(self, client):
        r = client.get("/?category=tech")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestWebTopics:
    def test_web_topics(self, client):
        r = client.get("/topics")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # Should contain topic names
        assert "AI" in r.text

    def test_web_topic_news_found(self, client):
        r = client.get("/topics/ai")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "AI" in r.text

    def test_web_topic_news_not_found(self, client):
        r = client.get("/topics/nonexistent")
        assert r.status_code == 404


class TestDebugDashboard:
    def test_debug_dashboard(self, client):
        r = client.get("/debug")
        # The debug frontend exists, but if the path is wrong we get 404
        # FileResponse returns 200 if the file exists
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
