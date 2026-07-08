"""Tests for the HorizonDB SQLite persistence layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.models import ContentItem, SourceType
from src.storage.db import HorizonDB, _row_to_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    id: str = "hn:top:1",
    source_type: SourceType = SourceType.HACKERNEWS,
    title: str = "Test Article",
    url: str = "https://example.com/article-1",
    ai_score: float | None = 8.5,
    ai_tags: list[str] | None = None,
    run_date: str = "2026-07-06",
    category: str | None = None,
    content: str | None = "Sample content text.",
    ai_summary: str | None = "A summary of the article.",
    ai_reason: str | None = "Important news.",
    ai_relevant: bool | None = True,
    published_at: datetime | None = None,
) -> ContentItem:
    """Build a minimal, valid ContentItem for testing."""
    metadata: dict = {}
    if category:
        metadata["category"] = category

    return ContentItem(
        id=id,
        source_type=source_type,
        title=title,
        url=url,
        content=content,
        author="test-author",
        published_at=published_at or datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 6, 10, 5, 0, tzinfo=timezone.utc),
        ai_relevant=ai_relevant,
        ai_score=ai_score,
        ai_reason=ai_reason,
        ai_summary=ai_summary,
        ai_tags=ai_tags or ["AI", "tech"],
        metadata=metadata,
    )


def _seed_items(db: HorizonDB, run_date: str = "2026-07-06", seed: str = "") -> list[ContentItem]:
    """Insert a handful of items for read-path tests.

    Pass a unique ``seed`` string when seeding multiple dates into the same
    database to avoid primary-key collisions on item IDs.
    """
    suffix = f"-{seed}" if seed else ""
    items = [
        _make_item(
            id=f"hn:top:1{suffix}",
            source_type=SourceType.HACKERNEWS,
            title="HN Article Alpha",
            url=f"https://example.com/alpha{suffix}",
            ai_score=9.0,
            ai_tags=["AI", "startups"],
            run_date=run_date,
            category="tech",
            ai_summary="Alpha summary with unique searchword.",
            content="Sample content text.",
        ),
        _make_item(
            id=f"reddit:ml:2{suffix}",
            source_type=SourceType.REDDIT,
            title="Reddit ML Post",
            url=f"https://example.com/ml{suffix}",
            ai_score=7.5,
            ai_tags=["ML", "research"],
            run_date=run_date,
            category="research",
            ai_summary="Reddit summary text.",
            content="Sample content text.",
        ),
        _make_item(
            id=f"rss:blog:3{suffix}",
            source_type=SourceType.RSS,
            title="RSS Blog Update",
            url=f"https://example.com/blog{suffix}",
            ai_score=6.0,
            ai_tags=["tech", "open source"],
            run_date=run_date,
            category="tech",
            ai_summary="RSS blog summary.",
            content="Sample content text.",
        ),
        _make_item(
            id=f"hn:top:4{suffix}",
            source_type=SourceType.HACKERNEWS,
            title="HN Low Score",
            url=f"https://example.com/low{suffix}",
            ai_score=5.0,
            ai_tags=["misc"],
            run_date=run_date,
            category="other",
            ai_summary="Low score item.",
            ai_relevant=False,
            content="Sample content text.",
        ),
    ]
    db.save_items(items, run_date=run_date, total_fetched=20)
    return items


def _seed_topics(db: HorizonDB) -> list[dict]:
    """Insert topic seed data."""
    topics = [
        {
            "name": "AI",
            "slug": "ai",
            "group_name": "Technology",
            "description": "Artificial Intelligence topics",
            "keywords": ["AI", "ML", "LLM"],
            "aliases": ["artificial-intelligence"],
            "sort_order": 1,
            "is_active": 1,
        },
        {
            "name": "Startups",
            "slug": "startups",
            "group_name": "Technology",
            "description": "Startup ecosystem news",
            "keywords": ["startup", "VC"],
            "aliases": [],
            "sort_order": 2,
            "is_active": 1,
        },
        {
            "name": "Research",
            "slug": "research",
            "group_name": "Academic",
            "description": "Academic research",
            "keywords": ["paper", "research"],
            "aliases": [],
            "sort_order": 1,
            "is_active": 1,
        },
    ]
    db.seed_topics(topics)
    return topics


# ---------------------------------------------------------------------------
# save_items / get_items
# ---------------------------------------------------------------------------


class TestSaveAndGetItems:
    def test_basic_round_trip(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        items = _seed_items(db)
        result = db.get_items()

        assert result["total"] == 4
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["pages"] == 1
        assert len(result["items"]) == 4
        # Default sort is ai_score DESC
        scores = [it["ai_score"] for it in result["items"]]
        assert scores == [9.0, 7.5, 6.0, 5.0]
        db.close()

    def test_filter_by_date(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-06")
        _seed_items(db, run_date="2026-07-07", seed="d2")

        r1 = db.get_items(run_date="2026-07-06")
        r2 = db.get_items(run_date="2026-07-07")
        assert r1["total"] == 4
        assert r2["total"] == 4
        db.close()

    def test_filter_by_source_type(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(source_type="hackernews")
        assert result["total"] == 2
        assert all(it["source_type"] == "hackernews" for it in result["items"])
        db.close()

    def test_filter_by_category(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(category="tech")
        assert result["total"] == 2
        db.close()

    def test_filter_by_tag(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(tag="AI")
        assert result["total"] == 1
        assert result["items"][0]["id"] == "hn:top:1"
        db.close()

    def test_filter_by_min_score(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(min_score=8.0)
        assert result["total"] == 1
        assert result["items"][0]["id"] == "hn:top:1"
        db.close()

    def test_combined_filters(self, tmp_path):
        """min_score + source_type together."""
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(source_type="hackernews", min_score=6.0)
        assert result["total"] == 1  # Only the 9.0 one qualifies
        assert result["items"][0]["id"] == "hn:top:1"
        db.close()

    def test_search_fts(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        result = db.get_items(search="searchword")
        assert result["total"] >= 1
        assert any("searchword" in it["ai_summary"] for it in result["items"])
        db.close()

    def test_sort_and_order(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)

        # Ascending order
        r = db.get_items(sort="ai_score", order="asc")
        assert r["items"][0]["ai_score"] == 5.0

        # Sort by published_at
        r = db.get_items(sort="published_at", order="desc")
        assert r["total"] == 4

        # Invalid sort field falls back to ai_score
        r = db.get_items(sort="invalid_column", order="asc")
        assert r["total"] == 4
        db.close()

    def test_pagination(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        r1 = db.get_items(per_page=2, page=1)
        assert len(r1["items"]) == 2
        assert r1["total"] == 4
        assert r1["pages"] == 2

        r2 = db.get_items(per_page=2, page=2)
        assert len(r2["items"]) == 2

        # Page beyond range
        r3 = db.get_items(per_page=2, page=3)
        assert len(r3["items"]) == 0
        db.close()

    def test_items_have_topics_key(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)

        item = _make_item(
            id="rss:blog:3",
            source_type=SourceType.RSS,
            title="Blog Post",
            url="https://example.com/blog",
            ai_score=6.0,
        )
        db.save_news_topics("rss:blog:3", [{"slug": "ai", "confidence": 0.9, "reason": "Obvious match"}])

        result = db.get_items()
        rss_item = next(it for it in result["items"] if it["id"] == "rss:blog:3")
        assert "topics" in rss_item
        assert len(rss_item["topics"]) == 1
        assert rss_item["topics"][0]["slug"] == "ai"
        db.close()


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


class TestGetItem:
    def test_found(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        item = db.get_item("hn:top:1")
        assert item is not None
        assert item["id"] == "hn:top:1"
        assert item["title"] == "HN Article Alpha"
        assert item["ai_score"] == 9.0
        assert item["source_type"] == "hackernews"
        assert "topics" in item
        db.close()

    def test_not_found(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        assert db.get_item("nonexistent") is None
        db.close()

    def test_includes_topics(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [
            {"slug": "ai", "confidence": 0.95, "reason": "AI news"},
            {"slug": "startups", "confidence": 0.7, "reason": "Startup coverage"},
        ])

        item = db.get_item("hn:top:1")
        assert len(item["topics"]) == 2
        slugs = {t["slug"] for t in item["topics"]}
        assert slugs == {"ai", "startups"}
        db.close()


# ---------------------------------------------------------------------------
# get_tags
# ---------------------------------------------------------------------------


class TestGetTags:
    def test_tag_counts(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        tags = db.get_tags()
        # "tech" appears in 1 item (rss:blog:3), "AI" in 1, "startups" in 1, etc.
        tag_map = {t["tag"]: t["count"] for t in tags}
        assert tag_map["tech"] == 1
        assert tag_map["AI"] == 1
        assert tag_map["startups"] == 1
        assert tag_map["ML"] == 1
        db.close()

    def test_min_count_filter(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        # Each tag appears at most once in the seed data, so min_count=1 returns all,
        # min_count=2 returns none
        tags_all = db.get_tags(min_count=1)
        tags_none = db.get_tags(min_count=2)
        assert len(tags_all) == 7  # AI, startups, ML, research, tech, "open source", misc
        assert len(tags_none) == 0
        db.close()

    def test_date_filtered_tags(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-06")
        _seed_items(db, run_date="2026-07-07", seed="d2")

        tags_06 = db.get_tags(run_date="2026-07-06")
        tags_all = db.get_tags()
        assert len(tags_06) > 0
        assert len(tags_all) >= len(tags_06)
        db.close()


# ---------------------------------------------------------------------------
# get_runs / get_run_dates
# ---------------------------------------------------------------------------


class TestRuns:
    def test_get_runs(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-06")
        runs = db.get_runs()
        assert len(runs) == 1
        assert runs[0]["date"] == "2026-07-06"
        assert runs[0]["total_fetched"] == 20
        assert runs[0]["total_selected"] == 4
        assert isinstance(runs[0]["languages"], list)
        db.close()

    def test_get_runs_limit(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-01", seed="d1")
        _seed_items(db, run_date="2026-07-02", seed="d2")
        _seed_items(db, run_date="2026-07-03", seed="d3")
        assert len(db.get_runs(limit=2)) == 2
        assert len(db.get_runs(limit=10)) == 3
        db.close()

    def test_get_run_dates(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-01", seed="d1")
        _seed_items(db, run_date="2026-07-06", seed="d2")
        dates = db.get_run_dates()
        assert dates == ["2026-07-06", "2026-07-01"]  # newest first
        db.close()


# ---------------------------------------------------------------------------
# get_category_counts
# ---------------------------------------------------------------------------


class TestCategoryCounts:
    def test_category_counts(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        counts = db.get_category_counts()
        count_map = {c["category"]: c["count"] for c in counts}
        assert count_map["tech"] == 2
        assert count_map["research"] == 1
        assert count_map["other"] == 1
        db.close()

    def test_category_counts_date_filtered(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-06")
        _seed_items(db, run_date="2026-07-07", seed="d2")
        counts = db.get_category_counts(run_date="2026-07-06")
        assert len(counts) == 3
        db.close()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        stats = db.get_stats()
        assert stats["total_items"] == 4
        assert stats["avg_score"] == round((9.0 + 7.5 + 6.0 + 5.0) / 4, 2)
        assert stats["max_score"] == 9.0
        assert stats["source_types"] == 3  # hackernews, reddit, rss
        db.close()

    def test_stats_empty_db(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        stats = db.get_stats()
        assert stats["total_items"] == 0
        assert stats["avg_score"] is None
        assert stats["max_score"] is None
        assert stats["source_types"] == 0
        db.close()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_fts_search(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        results = db.search("Alpha")
        assert len(results) >= 1
        assert any("Alpha" in it["title"] for it in results)
        db.close()

    def test_search_includes_topics(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.9}])

        results = db.search("Alpha")
        assert len(results) >= 1
        item = next(it for it in results if it["id"] == "hn:top:1")
        assert "topics" in item
        db.close()

    def test_search_no_match(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        results = db.search("zzz_nonexistent_term_xyz")
        assert len(results) == 0
        db.close()


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TestTopics:
    def test_seed_topics_upsert(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_topics(db)
        # Verify all 3 topics were seeded
        assert len(db.get_topics(grouped=False)["topics"]) == 3

        # Re-seed with an update to one topic
        count2 = db.seed_topics([
            {
                "name": "AI Updated",
                "slug": "ai",
                "group_name": "Technology",
                "description": "Updated description",
                "keywords": ["AI", "ML"],
                "aliases": [],
                "sort_order": 1,
                "is_active": 1,
            },
        ])
        assert count2 == 1
        topic = db.get_topic_by_slug("ai")
        assert topic["name"] == "AI Updated"
        assert topic["description"] == "Updated description"
        db.close()

    def test_get_topics_grouped(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.9}])

        result = db.get_topics(grouped=True)
        groups = result["groups"]
        group_names = {g["group_name"] for g in groups}
        assert "Technology" in group_names
        assert "Academic" in group_names

        tech_group = next(g for g in groups if g["group_name"] == "Technology")
        assert len(tech_group["topics"]) == 2
        # AI topic should have a count of 1
        ai_topic = next(t for t in tech_group["topics"] if t["slug"] == "ai")
        assert ai_topic["count"] == 1
        assert ai_topic["name"] == "AI"
        db.close()

    def test_get_topics_ungrouped(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_topics(db)
        result = db.get_topics(grouped=False)
        assert "topics" in result
        assert len(result["topics"]) == 3
        db.close()

    def test_get_topic_by_slug_found(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_topics(db)
        topic = db.get_topic_by_slug("ai")
        assert topic is not None
        assert topic["name"] == "AI"
        assert topic["slug"] == "ai"
        assert topic["group_name"] == "Technology"
        assert "keywords" in topic
        assert "aliases" in topic
        db.close()

    def test_get_topic_by_slug_not_found(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_topics(db)
        assert db.get_topic_by_slug("nonexistent-slug") is None
        db.close()

    def test_inactive_topic_not_returned(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        db.seed_topics([
            {
                "name": "Hidden",
                "slug": "hidden",
                "group_name": "Internal",
                "description": "",
                "keywords": [],
                "aliases": [],
                "sort_order": 0,
                "is_active": 0,
            },
        ])
        assert db.get_topic_by_slug("hidden") is None
        assert len(db.get_topics(grouped=False)["topics"]) == 0
        db.close()


# ---------------------------------------------------------------------------
# News-Topics associations
# ---------------------------------------------------------------------------


class TestNewsTopics:
    def test_save_and_get(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)

        count = db.save_news_topics("hn:top:1", [
            {"slug": "ai", "confidence": 0.95, "reason": "Clearly about AI"},
            {"slug": "startups", "confidence": 0.7, "reason": "Startup angle"},
        ])
        assert count == 2

        topics = db.get_news_topics("hn:top:1")
        assert len(topics) == 2
        assert topics[0]["slug"] == "ai"
        assert topics[0]["confidence"] == 0.95
        assert topics[0]["reason"] == "Clearly about AI"
        db.close()

    def test_re_save_is_idempotent(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.8}])
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.99}])
        topics = db.get_news_topics("hn:top:1")
        assert len(topics) == 1
        assert topics[0]["confidence"] == 0.99
        db.close()

    def test_unknown_slug_prints_warning(self, tmp_path, capsys):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)

        count = db.save_news_topics("hn:top:1", [
            {"slug": "nonexistent-topic", "confidence": 0.5},
            {"slug": "ai", "confidence": 0.9},
        ])
        assert count == 1  # Only the valid slug was saved
        captured = capsys.readouterr().out
        assert "unknown topic slug" in captured.lower()
        assert "nonexistent-topic" in captured
        db.close()

    def test_batch_get_news_topics(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.9}])
        db.save_news_topics("reddit:ml:2", [{"slug": "research", "confidence": 0.8}])

        result = db._batch_get_news_topics(["hn:top:1", "reddit:ml:2", "nonexistent"])
        assert result["hn:top:1"][0]["slug"] == "ai"
        assert result["reddit:ml:2"][0]["slug"] == "research"
        assert result["nonexistent"] == []  # No topics for unknown item
        db.close()

    def test_batch_get_empty_list(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        assert db._batch_get_news_topics([]) == {}
        db.close()

    def test_get_topic_news(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.9}])
        db.save_news_topics("reddit:ml:2", [{"slug": "ai", "confidence": 0.7}])

        result = db.get_topic_news("ai")
        assert result["topic"] is not None
        assert result["topic"]["slug"] == "ai"
        assert result["total"] == 2
        assert len(result["items"]) == 2
        # Items should have topics key
        for item in result["items"]:
            assert "topics" in item
        db.close()

    def test_get_topic_news_pagination(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        _seed_topics(db)
        db.save_news_topics("hn:top:1", [{"slug": "ai", "confidence": 0.9}])
        db.save_news_topics("reddit:ml:2", [{"slug": "ai", "confidence": 0.7}])

        r = db.get_topic_news("ai", page=1, per_page=1)
        assert len(r["items"]) == 1
        assert r["total"] == 2
        assert r["pages"] == 2
        db.close()

    def test_get_topic_news_unknown_slug(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_topics(db)
        result = db.get_topic_news("nonexistent")
        assert result["topic"] is None
        assert result["items"] == []
        assert result["total"] == 0
        db.close()


# ---------------------------------------------------------------------------
# save_items edge cases
# ---------------------------------------------------------------------------


class TestSaveItemsEdgeCases:
    def test_re_save_replaces_existing(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db, run_date="2026-07-06")

        # Re-save with different items for the same date
        new_items = [
            _make_item(
                id="hn:new:1",
                source_type=SourceType.HACKERNEWS,
                title="Replacement Article",
                url="https://example.com/new",
                ai_score=10.0,
                run_date="2026-07-06",
            ),
        ]
        db.save_items(new_items, run_date="2026-07-06", total_fetched=5)

        result = db.get_items(run_date="2026-07-06")
        assert result["total"] == 1
        assert result["items"][0]["id"] == "hn:new:1"
        db.close()

    def test_save_empty_items(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        count = db.save_items([], run_date="2026-07-06", total_fetched=0)
        assert count == 0

        # The run should still be recorded
        runs = db.get_runs()
        assert len(runs) == 1
        assert runs[0]["total_selected"] == 0
        db.close()

    def test_metadata_fields_roundtrip(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        item = _make_item(
            id="test:meta:1",
            source_type=SourceType.GITHUB,
            title="GitHub Repo",
            url="https://github.com/user/repo",
            ai_score=7.0,
            category="dev",
        )
        item.metadata["stars"] = 500
        item.metadata["language"] = "Python"
        db.save_items([item], run_date="2026-07-06", total_fetched=1)

        result = db.get_item("test:meta:1")
        assert result["metadata"]["stars"] == 500
        assert result["metadata"]["language"] == "Python"
        assert result["metadata"]["category"] == "dev"
        db.close()


# ---------------------------------------------------------------------------
# close / reconnect
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_and_reopen(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        assert db.get_items()["total"] == 4
        db.close()

        # Reopen with a new instance pointing to the same file
        db2 = HorizonDB(db_path=str(tmp_path / "test.db"))
        assert db2.get_items()["total"] == 4
        db2.close()

    def test_close_idempotent(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        db.close()
        db.close()  # Should not raise
        assert getattr(db._local, "conn", None) is None


# ---------------------------------------------------------------------------
# _row_to_item helper
# ---------------------------------------------------------------------------


class TestRowToItem:
    def test_converts_row_correctly(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        _seed_items(db)
        # Directly query to get a raw row, then convert
        import sqlite3
        conn = sqlite3.connect(str(db.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM items WHERE id = ?", ("hn:top:1",)).fetchone()
        assert row is not None

        item = _row_to_item(row)
        assert item["id"] == "hn:top:1"
        assert item["source_type"] == "hackernews"
        assert item["ai_score"] == 9.0
        assert item["ai_relevant"] is True
        assert isinstance(item["ai_tags"], list)
        assert isinstance(item["metadata"], dict)
        conn.close()

    def test_ai_relevant_null(self, tmp_path):
        """None rounds-trips via 0 → False due to ``1 if item.ai_relevant else 0``."""
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        item = _make_item(
            id="test:null:1",
            ai_relevant=None,
        )
        db.save_items([item], run_date="2026-07-06", total_fetched=1)

        result = db.get_item("test:null:1")
        # save_items treats None as falsy → stores 0 → _row_to_item reads as False
        assert result["ai_relevant"] is False
        db.close()


# ---------------------------------------------------------------------------
# raw_html / display_html
# ---------------------------------------------------------------------------


class TestRawAndDisplayHtml:
    def test_round_trips_raw_and_display_html(self, tmp_path):
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        item = _make_item(id="test:html:1", content="Plain text body.")
        item.raw_html = "<h2>Title</h2><p>Body &amp; more</p>"
        item.display_html = "<h2>Title</h2><p>Body &amp; more</p>"

        db.save_items([item], run_date="2026-07-06", total_fetched=1)
        result = db.get_item("test:html:1")

        assert result["raw_html"] == "<h2>Title</h2><p>Body &amp; more</p>"
        assert result["display_html"] == "<h2>Title</h2><p>Body &amp; more</p>"
        # content (plain text) is untouched by the new HTML fields.
        assert result["content"] == "Plain text body."
        db.close()

    def test_defaults_to_none_when_not_set(self, tmp_path):
        """Items saved without HTML extraction results (e.g. skipped URLs)
        must not break — raw_html/display_html should just be None, and the
        existing content field is unaffected."""
        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        item = _make_item(id="test:html:2", content="Only plain text, no HTML.")

        db.save_items([item], run_date="2026-07-06", total_fetched=1)
        result = db.get_item("test:html:2")

        assert result["raw_html"] is None
        assert result["display_html"] is None
        assert result["content"] == "Only plain text, no HTML."
        db.close()

    def test_legacy_row_without_html_columns_still_reads(self, tmp_path):
        """Simulates a DB file created before this migration: raw_html/
        display_html columns don't exist on the row, and _row_to_item must
        fall back to None instead of raising."""
        import sqlite3

        db = HorizonDB(db_path=str(tmp_path / "test.db"))
        db.conn  # force schema creation + migrations to run
        db.close()

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO items (id, source_type, title, url, content,
                   published_at, fetched_at, run_date)
               VALUES ('legacy:1', 'rss', 'Legacy', 'https://example.com/legacy',
                   'legacy content', '2026-07-06T00:00:00+00:00',
                   '2026-07-06T00:00:00+00:00', '2026-07-06')"""
        )
        conn.commit()
        # Select every column except raw_html/display_html, simulating a
        # pre-migration row shape (all other _row_to_item fields still need
        # to be present so this doesn't fail on an unrelated missing key).
        row = conn.execute(
            """SELECT id, source_type, title, url, content, cover_image,
                   images_json, author, published_at, fetched_at, ai_relevant,
                   ai_score, ai_reason, ai_summary, ai_tags_json, metadata_json,
                   run_date, selected, drop_reason
               FROM items WHERE id = 'legacy:1'"""
        ).fetchone()
        conn.close()

        item = _row_to_item(row)
        assert item["raw_html"] is None
        assert item["display_html"] is None
        assert item["content"] == "legacy content"
