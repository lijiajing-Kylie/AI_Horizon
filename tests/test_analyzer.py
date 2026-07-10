import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import src.ai.analyzer as analyzer_module
from src.ai.analyzer import ContentAnalyzer
from src.models import ContentItem, SourceType


def _make_item(item_id: str, **overrides) -> ContentItem:
    defaults = dict(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Item {item_id}",
        url="https://example.com/item",
        published_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ContentItem(**defaults)


def test_analyze_batch_does_not_sleep_by_default(monkeypatch):
    analyzer = ContentAnalyzer(SimpleNamespace())
    items = [_make_item("rss:test:1"), _make_item("rss:test:2")]
    sleep_calls = []

    async def fake_analyze_item(item):
        item.ai_score = 8.0

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)
    monkeypatch.setattr(analyzer_module.asyncio, "sleep", fake_sleep)

    result = asyncio.run(analyzer.analyze_batch(items))

    assert len(result) == 2
    assert sleep_calls == []


def test_analyze_batch_sleeps_between_items_when_throttle_configured(monkeypatch):
    client = SimpleNamespace(config=SimpleNamespace(throttle_sec=1.5))
    analyzer = ContentAnalyzer(client)
    items = [_make_item("rss:test:1"), _make_item("rss:test:2"), _make_item("rss:test:3")]
    sleep_calls = []

    async def fake_analyze_item(item):
        item.ai_score = 8.0

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)
    monkeypatch.setattr(analyzer_module.asyncio, "sleep", fake_sleep)

    asyncio.run(analyzer.analyze_batch(items))

    assert sleep_calls == [1.5, 1.5]


def test_analyze_batch_concurrent_processing(monkeypatch):
    """Verify that higher concurrency allows overlapping item processing."""
    client = SimpleNamespace(config=SimpleNamespace(analysis_concurrency=3))
    analyzer = ContentAnalyzer(client)
    items = [_make_item(f"rss:test:{i}") for i in range(5)]
    active_count = 0
    max_active = 0

    async def fake_analyze_item(item):
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.05)  # Small delay to allow overlap
        active_count -= 1

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)

    asyncio.run(analyzer.analyze_batch(items))

    assert max_active == 3
    assert all(item.ai_score is None for item in items)  # None because fake_analyze_item doesn't set it


def test_analyze_batch_concurrent_preserves_order(monkeypatch):
    """Verify that analyze_batch preserves input order in results."""
    client = SimpleNamespace(config=SimpleNamespace(analysis_concurrency=3))
    analyzer = ContentAnalyzer(client)
    items = [_make_item(f"rss:test:{i}") for i in range(5)]

    async def fake_analyze_item(item):
        item.ai_score = float(item.id.split(":")[-1]) * 10

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)

    result = asyncio.run(analyzer.analyze_batch(items))

    assert [item.id for item in result] == [item.id for item in items]


def _fake_ai_response() -> str:
    return json.dumps({
        "relevant": True,
        "source_authority": 1, "novelty": 1, "technical_substance": 1,
        "real_world_impact": 1, "community_validation": 1, "content_completeness": 1,
        "marketing_penalty": 0, "duplicate_penalty": 0, "thin_content_penalty": 0,
        "weak_ai_relevance_penalty": 0,
        "reason": "ok", "summary": "摘要", "tags": [],
    })


def test_analyze_item_omits_source_note_when_full_text():
    captured = {}

    async def fake_complete(system, user):
        captured["user"] = user
        return _fake_ai_response()

    analyzer = ContentAnalyzer(SimpleNamespace(complete=fake_complete))
    item = _make_item("rss:full", raw_content="A real article body.", extraction_status="success")

    asyncio.run(analyzer._analyze_item(item))

    assert "正文抓取" not in captured["user"]


def test_analyze_item_includes_source_note_when_only_rss_summary():
    captured = {}

    async def fake_complete(system, user):
        captured["user"] = user
        return _fake_ai_response()

    analyzer = ContentAnalyzer(SimpleNamespace(complete=fake_complete))
    item = _make_item(
        "rss:summary-only", rss_summary="Just a snippet.", extraction_status="failed",
        extraction_error="bad_status:503",
    )

    asyncio.run(analyzer._analyze_item(item))

    assert "正文抓取failed" in captured["user"]
    assert "rss_summary" in captured["user"]
