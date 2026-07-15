"""Unit coverage for src.dedup.apply_multi_source_bonus.

Items independently corroborated by >= MULTI_SOURCE_BONUS_THRESHOLD sources
(per the final source_provenance.source_count, written by
build_source_attribution) get a small score bump. Must run after any
re-analysis pass that overwrites score_breakdown/ai_score.
"""
from datetime import datetime, timezone

from src.dedup import (
    MULTI_SOURCE_BONUS,
    MULTI_SOURCE_BONUS_THRESHOLD,
    apply_multi_source_bonus,
)
from src.models import ContentItem, SourceType


def make_item(*, ai_score: float, source_count: int | None, total_breakdown: float | None = None) -> ContentItem:
    metadata: dict = {}
    if source_count is not None:
        metadata["source_provenance"] = {"source_count": source_count}
    if total_breakdown is not None:
        metadata["score_breakdown"] = {"total": total_breakdown, "source_authority": 2.0}

    return ContentItem(
        id="rss:example:1",
        source_type=SourceType.RSS,
        title="Example",
        url="https://example.com/a",
        published_at=datetime.now(timezone.utc),
        ai_relevant=True,
        ai_score=ai_score,
        metadata=metadata,
    )


def test_three_or_more_sources_get_bonus():
    item = make_item(ai_score=7.0, source_count=3, total_breakdown=7.0)
    apply_multi_source_bonus([item])

    assert item.ai_score == 7.0 + MULTI_SOURCE_BONUS
    assert item.metadata["score_breakdown"]["multi_source_bonus"] == MULTI_SOURCE_BONUS
    assert item.metadata["score_breakdown"]["total"] == 7.0 + MULTI_SOURCE_BONUS


def test_two_sources_get_no_bonus():
    item = make_item(ai_score=7.0, source_count=2, total_breakdown=7.0)
    apply_multi_source_bonus([item])

    assert item.ai_score == 7.0
    assert item.metadata["score_breakdown"]["multi_source_bonus"] == 0.0
    assert item.metadata["score_breakdown"]["total"] == 7.0


def test_missing_source_provenance_defaults_to_no_bonus():
    item = make_item(ai_score=7.0, source_count=None)
    apply_multi_source_bonus([item])

    assert item.ai_score == 7.0


def test_bonus_is_capped_at_ten():
    item = make_item(ai_score=9.7, source_count=MULTI_SOURCE_BONUS_THRESHOLD, total_breakdown=9.7)
    apply_multi_source_bonus([item])

    assert item.ai_score == 10.0
    assert item.metadata["score_breakdown"]["total"] == 10.0


def test_unscored_items_are_skipped():
    item = make_item(ai_score=0.0, source_count=5)
    item.ai_score = None
    apply_multi_source_bonus([item])

    assert item.ai_score is None
