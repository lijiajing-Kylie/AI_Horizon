import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import src.ai.enricher as enricher_module
from src.ai.content_selection import content_hash
from src.ai.enricher import ContentEnricher
from src.models import ContentItem, SourceType


def _make_item(**overrides) -> ContentItem:
    defaults = dict(
        id="rss:1",
        source_type=SourceType.RSS,
        title="A title",
        url="https://example.com/a",
        published_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ContentItem(**defaults)


def _fake_enrichment_response() -> str:
    return json.dumps({
        "title_en": "Title", "title_zh": "标题",
        "whats_new_en": "Something new happened.", "whats_new_zh": "发生了新事情。",
        "why_it_matters_en": "It matters.", "why_it_matters_zh": "这很重要。",
        "key_details_en": "Details.", "key_details_zh": "细节。",
        "reason_en": "Reason.", "reason_zh": "理由。",
        "community_discussion_en": "", "community_discussion_zh": "",
        "sources": [],
    })


def test_translate_html_records_display_html_source_hash(monkeypatch):
    enricher = ContentEnricher(SimpleNamespace())
    item = _make_item(display_html="<p>hello</p>", raw_content="hello world", extraction_status="success")

    call_count = {"n": 0}

    async def fake_translate(client, display_html):
        call_count["n"] += 1
        return "<p>你好</p>"

    monkeypatch.setattr(enricher_module, "translate_display_html", fake_translate)

    asyncio.run(enricher._translate_html(item))

    assert item.display_html_zh == "<p>你好</p>"
    assert item.metadata["display_html_source_hash"] == content_hash("<p>hello</p>")

    # Recorded, but never used to skip — calling again re-translates.
    asyncio.run(enricher._translate_html(item))
    assert call_count["n"] == 2


def test_enrich_item_records_enrichment_source_hash(monkeypatch):
    async def fake_complete(system, user):
        return _fake_enrichment_response()

    enricher = ContentEnricher(SimpleNamespace(complete=fake_complete))
    item = _make_item(raw_content="Real article body about something important.", extraction_status="success")

    async def fake_extract_concepts(item, content_text, source_note=""):
        return []

    monkeypatch.setattr(enricher, "_extract_concepts", fake_extract_concepts)

    asyncio.run(enricher._enrich_item(item))

    assert item.metadata["title_zh"] == "标题"
    assert "enrichment_source_hash" in item.metadata
    assert item.metadata["enrichment_source_hash"] == content_hash("Real article body about something important.")


def test_translate_item_fallback_records_enrichment_source_hash():
    async def fake_complete(system, user):
        return json.dumps({"title_zh": "标题", "summary_zh": "摘要", "reason_zh": "理由"})

    enricher = ContentEnricher(SimpleNamespace(complete=fake_complete))
    item = _make_item(title="A title", ai_summary="a summary", ai_reason="a reason")

    asyncio.run(enricher._translate_item(item))

    expected = content_hash(f"{item.title}|{item.ai_summary}|{item.ai_reason}")
    assert item.metadata["enrichment_source_hash"] == expected
