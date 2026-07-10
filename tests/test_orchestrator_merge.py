from datetime import datetime, timezone

from rich.console import Console

from src.models import ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator


def make_orchestrator() -> HorizonOrchestrator:
    orchestrator = HorizonOrchestrator.__new__(HorizonOrchestrator)
    orchestrator.console = Console(record=True)
    return orchestrator


def make_item(item_id: str, source_type: SourceType, content: str, **extra) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=source_type,
        title=f"title-{item_id}",
        url="https://example.com/same-article",
        content=content,
        published_at=datetime.now(timezone.utc),
        **extra,
    )


def test_merge_promotes_successful_extraction_from_non_primary_duplicate() -> None:
    # `hn` has the longer raw `content` (comments appended) so it would be
    # picked as primary by content length alone, but its own extraction
    # failed. `rss` has a shorter `content` but a successful extraction —
    # that raw_content/raw_html/display_html must survive the merge.
    hn = make_item(
        "hn:1",
        SourceType.HACKERNEWS,
        content="short original text" + ("\n--- Top Comments ---\nlots of comment text" * 20),
        extraction_status="failed",
        extraction_error="bad_status:503",
    )
    rss = make_item(
        "rss:1",
        SourceType.RSS,
        content="full article text",
        raw_content="full article text",
        raw_html="<main><p>full article text</p></main>",
        display_html="<p>full article text</p>",
        content_source="full_text",
        extraction_status="success",
        http_status=200,
        final_url="https://example.com/same-article",
        text_length=18,
        extractor_version="1",
    )

    orchestrator = make_orchestrator()
    merged = orchestrator.merge_cross_source_duplicates([hn, rss])

    assert len(merged) == 1
    primary = merged[0]
    # hn was picked as primary by raw content length ...
    assert primary.id == "hn:1"
    # ... but the successful extraction from rss must have been promoted onto it.
    assert primary.raw_content == "full article text"
    assert primary.raw_html == "<main><p>full article text</p></main>"
    assert primary.display_html == "<p>full article text</p>"
    assert primary.extraction_status == "success"
    assert primary.content_source == "full_text"
    assert primary.http_status == 200


def test_merge_leaves_primary_untouched_when_its_own_extraction_succeeded() -> None:
    a = make_item(
        "a:1", SourceType.RSS, content="AAAA" * 50,
        raw_content="a-content", extraction_status="success", content_source="full_text",
    )
    b = make_item(
        "b:1", SourceType.RSS, content="short",
        raw_content="b-content", extraction_status="success", content_source="full_text",
    )

    orchestrator = make_orchestrator()
    merged = orchestrator.merge_cross_source_duplicates([a, b])

    assert len(merged) == 1
    primary = merged[0]
    assert primary.id == "a:1"  # longer raw content wins primary selection
    assert primary.raw_content == "a-content"  # its own extraction, not clobbered by b's
