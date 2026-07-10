from datetime import datetime, timezone

from src.ai.content_selection import build_source_note, content_hash, resolve_content
from src.models import ContentItem, SourceType


def make_item(**overrides) -> ContentItem:
    defaults = dict(
        id="rss:1",
        source_type=SourceType.RSS,
        title="A title",
        url="https://example.com/a",
        published_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return ContentItem(**defaults)


def test_resolve_content_prefers_clean_content_over_raw_content() -> None:
    body = "Real article body with enough real substance to pass the over-clean guard. " * 4
    item = make_item(
        raw_content=f"A title\n\n{body}Subscribe to our newsletter for more.",
        extraction_status="success",
    )
    resolved = resolve_content(item)
    assert resolved.is_full_text is True
    assert resolved.content_source == "full_text"
    assert "newsletter" not in resolved.text  # CTA sentence stripped by clean_article_content
    assert "Real article body" in resolved.text


def test_resolve_content_falls_back_to_rss_summary_when_no_raw_content() -> None:
    item = make_item(
        rss_summary="Just a short RSS snippet.",
        extraction_status="failed",
        extraction_error="bad_status:503",
    )
    resolved = resolve_content(item)
    assert resolved.is_full_text is False
    assert resolved.content_source == "rss_summary"
    assert resolved.extraction_status == "failed"
    assert resolved.text == "Just a short RSS snippet."


def test_resolve_content_returns_none_source_when_nothing_available() -> None:
    item = make_item()
    resolved = resolve_content(item)
    assert resolved.content_source == "none"
    assert resolved.is_full_text is False
    assert resolved.text == ""


def test_resolve_content_defaults_extraction_status_to_unknown_for_old_rows() -> None:
    # Rows written before this change have no extraction_status at all.
    item = make_item(rss_summary="legacy row content")
    resolved = resolve_content(item)
    assert resolved.extraction_status == "unknown"


def test_build_source_note_empty_when_full_text() -> None:
    item = make_item(raw_content="full text here", extraction_status="success")
    assert build_source_note(resolve_content(item)) == ""


def test_build_source_note_present_when_not_full_text() -> None:
    item = make_item(rss_summary="only a summary", extraction_status="failed")
    note = build_source_note(resolve_content(item))
    assert note != ""
    assert "failed" in note
    assert "rss_summary" in note


def test_content_hash_is_deterministic_and_sensitive_to_input() -> None:
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert content_hash(None) == content_hash("")
