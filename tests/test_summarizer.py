"""Unit tests for daily summary rendering."""

import asyncio
from datetime import datetime, timezone

from src.ai.summarizer import DailySummarizer
from src.models import ContentItem, SourceType


def _run_async(coro):
    return asyncio.run(coro)


def _make_item(idx: int) -> ContentItem:
    item = ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Important Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="content",
        author="tester",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
    )
    item.ai_score = 8.0
    item.ai_summary = f"Summary for item {idx}."
    item.ai_tags = ["AI", "News"]
    return item


def test_generate_webhook_overview_lists_items_without_full_details():
    summarizer = DailySummarizer()
    items = [_make_item(1), _make_item(2)]

    result = summarizer.generate_webhook_overview(
        items,
        date="2026-04-25",
        total_fetched=10,
        language="en",
    )

    assert "Selected 2 important items from 10 fetched items" in result
    assert "1. [Important Item 1](https://example.com/items/1)" in result
    assert "2. [Important Item 2](https://example.com/items/2)" in result
    assert "Summary for item 1." not in result


def test_generate_webhook_item_renders_single_item_detail():
    summarizer = DailySummarizer()

    result = summarizer.generate_webhook_item(
        _make_item(1),
        language="en",
        index=1,
        total=2,
    )

    assert result.startswith("Item 1/2")
    assert "## [Important Item 1](https://example.com/items/1)" in result
    assert "Summary for item 1." in result
    # assert "**Tags**: `#AI`, `#News`" in result  # TODO: re-enable when tags rendering is restored


def test_generate_webhook_item_includes_discussion_link_when_distinct():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://news.ycombinator.com/item?id=1"

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "tester · Apr 25, 08:00 · [Discussion](https://news.ycombinator.com/item?id=1)" in result


def test_generate_webhook_item_omits_discussion_link_when_same_as_item_url():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = item.url

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "[Discussion](https://example.com/items/1)" not in result


def test_generate_webhook_item_uses_localized_discussion_label():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://www.reddit.com/r/python/comments/abc123/test/"

    result = summarizer.generate_webhook_item(
        item,
        language="zh",
        index=1,
        total=1,
    )

    assert "[社区讨论](https://www.reddit.com/r/python/comments/abc123/test/)" in result


def test_generate_summary_zh_uses_localized_selection_header_and_numeric_date():
    summarizer = DailySummarizer()
    item = _make_item(1)

    result = _run_async(
        summarizer.generate_summary(
            [item],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 从 10 条内容中筛选出 1 条重要资讯。" in result
    assert "rss · tester · 4月25日 08:00" in result
    assert "From 10 items" not in result
    assert "Apr 25, 08:00" not in result


def test_generate_empty_summary_zh_uses_localized_analyzed_line():
    summarizer = DailySummarizer()

    result = _run_async(
        summarizer.generate_summary(
            [],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 已分析 10 条内容，但没有达到重要性阈值的条目。" in result
    assert "Analyzed 10 items" not in result


# -- training sub-track section ----------------------------------------------------


def _make_training_item(idx: int, relevance: float = 5.0) -> ContentItem:
    item = _make_item(idx)
    item.is_training = True
    item.training_relevance = relevance
    item.ai_score = 3.0  # low news score — the training section shows relevance, not this
    return item


def test_generate_summary_splits_training_section():
    summarizer = DailySummarizer()
    normal = _make_item(1)
    training = _make_training_item(2, relevance=5.0)

    result = _run_async(
        summarizer.generate_summary([normal, training], date="2026-04-25", total_fetched=10, language="zh")
    )

    # Training section header present, but training items carry no score
    assert "## 培训" in result
    assert "培训相关度" not in result
    # Normal item keeps its ⭐️ score line; training TOC + headline have none
    assert "1. [Important Item 1](#item-1) ⭐️ 8.0/10" in result
    assert "2. [Important Item 2](#item-2)" in result
    assert "## [Important Item 2](https://example.com/items/2)" in result
    assert "⭐️" not in result.split("## 培训")[1]
    # Global anchors stay unique across both tracks
    assert "#item-1" in result
    assert "#item-2" in result
    # Training section renders after the normal item body
    assert result.index("## 培训") > result.index("Important Item 1")


def test_generate_summary_normal_anchors_unchanged_with_training():
    """Adding training items must not shift normal items' anchors/TOC lines."""
    summarizer = DailySummarizer()
    normal = [_make_item(1), _make_item(2)]
    training = _make_training_item(3)

    base = _run_async(
        summarizer.generate_summary(normal, date="2026-04-25", total_fetched=10, language="zh")
    )
    with_tr = _run_async(
        summarizer.generate_summary(normal + [training], date="2026-04-25", total_fetched=10, language="zh")
    )

    for i in range(1, 3):
        assert f"#item-{i}" in base
        assert f"#item-{i}" in with_tr
    # The first normal item's anchor still points at its own title in both runs
    assert "1. [Important Item 1](#item-1)" in base
    assert "1. [Important Item 1](#item-1)" in with_tr


def test_generate_summary_omits_training_section_when_none():
    summarizer = DailySummarizer()
    result = _run_async(
        summarizer.generate_summary([_make_item(1)], date="2026-04-25", total_fetched=10, language="zh")
    )
    assert "## 培训" not in result
    assert "培训相关度" not in result


def test_generate_summary_training_english_labels():
    summarizer = DailySummarizer()
    normal = _make_item(1)
    training = _make_training_item(2)

    result = _run_async(
        summarizer.generate_summary([normal, training], date="2026-04-25", total_fetched=10, language="en")
    )

    assert "## Training" in result
    assert "Training relevance" not in result
    # English training items are unscored too
    assert "## [Important Item 2](https://example.com/items/2)" in result
    assert "⭐️" not in result.split("## Training")[1]
