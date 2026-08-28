"""Tests for the training sub-track selection gate (src/filtering.py)."""

from datetime import datetime, timezone

from src.filtering import select_training_items
from src.models import ContentItem, FilteringConfig, SourceType


def _make_item(
    item_id: str,
    training_relevance: float,
    ai_score: float = 0.0,
    ai_relevant: bool = False,
) -> ContentItem:
    item = ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Item {item_id}",
        url=f"https://example.com/{item_id}",
        published_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )
    item.training_relevance = training_relevance
    item.ai_score = ai_score
    item.ai_relevant = ai_relevant
    return item


def test_disabled_returns_empty_and_marks_nothing():
    cfg = FilteringConfig(training_enabled=False)
    items = [_make_item("a", 5.0)]
    selected, candidate_ids = select_training_items(items, cfg)
    assert selected == []
    assert candidate_ids == set()
    assert not items[0].is_training


def test_selects_only_items_at_or_above_threshold():
    cfg = FilteringConfig(training_enabled=True, training_relevance_threshold=4.0, training_max_items=6)
    items = [_make_item("a", 5.0), _make_item("b", 3.5), _make_item("c", 4.0)]
    selected, candidate_ids = select_training_items(items, cfg)
    assert [i.id for i in selected] == ["a", "c"]
    assert candidate_ids == {"a", "c"}
    assert all(i.is_training for i in selected)
    # Below-threshold items are NOT marked
    assert not items[1].is_training


def test_sorts_by_relevance_desc_and_caps():
    cfg = FilteringConfig(training_enabled=True, training_relevance_threshold=0.0, training_max_items=2)
    items = [_make_item(str(i), float(i)) for i in (6, 5, 4, 3, 2, 1)]
    selected, candidate_ids = select_training_items(items, cfg)
    assert [i.id for i in selected] == ["6", "5"]
    # candidate_ids includes everything that cleared the gate, even over the cap
    assert candidate_ids == {"1", "2", "3", "4", "5", "6"}


def test_marketing_course_ads_pass_independent_gate():
    """Course ads / bootcamp recruiting (ai_relevant=False, low ai_score) still
    qualify — the whole point of the independent training gate."""
    cfg = FilteringConfig(training_enabled=True, training_relevance_threshold=4.0, training_max_items=None)
    items = [
        _make_item("ad1", 5.0, ai_score=2.0, ai_relevant=False),
        _make_item("ad2", 4.0, ai_score=1.5, ai_relevant=False),
    ]
    selected, candidate_ids = select_training_items(items, cfg)
    assert len(selected) == 2
    assert candidate_ids == {"ad1", "ad2"}
    assert all(i.is_training for i in selected)


def test_training_max_items_none_keeps_all_candidates():
    cfg = FilteringConfig(training_enabled=True, training_relevance_threshold=4.0, training_max_items=None)
    items = [_make_item("a", 5.0), _make_item("b", 4.5), _make_item("c", 4.0)]
    selected, _ = select_training_items(items, cfg)
    assert len(selected) == 3
