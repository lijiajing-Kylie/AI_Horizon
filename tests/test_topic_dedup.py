"""Event-level (cross-source, cross-language) dedup via merge_topic_duplicates.

Regression coverage for the MarkTechPost / AI Hot case: two items with
different titles and languages reporting the same real-world event
(Ant Group's Robbyant open-sourcing the 6B-parameter LingBot-VLA 2.0 model)
must be merged into a single item, with the dropped source preserved in
metadata (not discarded) so the frontend can render "多源报道".
"""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from rich.console import Console

from src.models import ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator


def make_orchestrator() -> HorizonOrchestrator:
    orchestrator = HorizonOrchestrator.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(ai=SimpleNamespace())
    orchestrator.console = Console(record=True)
    return orchestrator


def make_marktechpost_item() -> ContentItem:
    return ContentItem(
        id="rss:marktechpost:lingbot-vla-2",
        source_type=SourceType.RSS,
        title="Ant Group's Robbyant Open-Sources LingBot-VLA 2.0, a 6B-Parameter VLA Model",
        url="https://www.marktechpost.com/2026/07/08/ant-robbyant-lingbot-vla-2-open-source/",
        published_at=datetime.now(timezone.utc),
        ai_relevant=True,
        ai_score=8.5,
        ai_summary=(
            "Ant Group's Robbyant lab open-sourced LingBot-VLA 2.0, a "
            "6-billion-parameter vision-language-action model for embodied AI."
        ),
        ai_tags=["VLA", "开源", "具身智能"],
        metadata={"feed_name": "MarkTechPost"},
    )


def make_aihot_item() -> ContentItem:
    return ContentItem(
        id="rss:aihot:lingbot-vla-2",
        source_type=SourceType.RSS,
        title="蚂蚁 Robbyant 开源 LingBot-VLA 2.0，参数量 60 亿的 VLA 模型",
        url="https://ai-hot.example.com/news/lingbot-vla-2-open-source",
        published_at=datetime.now(timezone.utc),
        ai_relevant=True,
        ai_score=7.8,
        ai_summary="蚂蚁旗下 Robbyant 团队开源新一代具身智能模型 LingBot-VLA 2.0，参数规模 60 亿。",
        ai_tags=["VLA", "开源"],
        metadata={"feed_name": "AI Hot"},
    )


def _mock_dedup_response(primary: ContentItem, duplicate: ContentItem) -> str:
    return json.dumps(
        {
            "duplicates": [[0, 1]],
            "source_provenance": {
                "0": {
                    "canonical_title": "蚂蚁 Robbyant 开源 60 亿参数 VLA 模型 LingBot-VLA 2.0",
                    "primary_source": {
                        "name": "MarkTechPost",
                        "url": str(primary.url),
                        "type": "media_report",
                        "reason": "更完整的英文技术媒体首发报道",
                    },
                    "sources": [
                        {
                            "name": "MarkTechPost",
                            "url": str(primary.url),
                            "type": "media_report",
                            "role": "primary",
                            "is_primary": True,
                            "reason": "首发且内容完整",
                        },
                        {
                            "name": "AI Hot",
                            "url": str(duplicate.url),
                            "type": "aggregator",
                            "role": "commentary",
                            "is_primary": False,
                            "reason": "中文转述报道",
                        },
                    ],
                    "merged_facts": [
                        "LingBot-VLA 2.0 是蚂蚁 Robbyant 团队开源的 60 亿参数 VLA 模型",
                    ],
                }
            },
        }
    )


def test_cross_source_cross_language_same_event_is_merged(monkeypatch) -> None:
    primary = make_marktechpost_item()
    duplicate = make_aihot_item()

    class FakeAIClient:
        async def complete(self, system: str, user: str) -> str:
            return _mock_dedup_response(primary, duplicate)

    monkeypatch.setattr(
        "src.orchestrator.create_ai_client", lambda config: FakeAIClient()
    )

    orchestrator = make_orchestrator()
    result = asyncio.run(orchestrator.merge_topic_duplicates([primary, duplicate]))

    # Only one item should survive on the frontend-facing list.
    assert [item.id for item in result] == [primary.id]

    kept = result[0]

    # The dropped item's source must not be discarded — it should be
    # recorded on the surviving primary for later provenance aggregation.
    topic_coverage = kept.metadata["topic_coverage"]
    assert len(topic_coverage) == 1
    assert topic_coverage[0]["label"] == "AI Hot"
    assert topic_coverage[0]["url"] == str(duplicate.url)

    prov_groups = kept.metadata["_topic_provenance_groups"]
    assert len(prov_groups) == 1
    urls_in_group = {s["source_url"] for s in prov_groups[0]["sources"]}
    assert urls_in_group == {str(primary.url), str(duplicate.url)}


def test_merged_event_exposes_multi_source_attribution(monkeypatch) -> None:
    """After merge_topic_duplicates + _build_source_attribution, the surviving
    item should carry a "多源报道" style structure the frontend can render,
    with both original article links preserved."""
    primary = make_marktechpost_item()
    duplicate = make_aihot_item()

    class FakeAIClient:
        async def complete(self, system: str, user: str) -> str:
            return _mock_dedup_response(primary, duplicate)

    monkeypatch.setattr(
        "src.orchestrator.create_ai_client", lambda config: FakeAIClient()
    )

    orchestrator = make_orchestrator()
    result = asyncio.run(orchestrator.merge_topic_duplicates([primary, duplicate]))
    HorizonOrchestrator._build_source_attribution(result)

    kept = result[0]
    provenance = kept.metadata["source_provenance"]
    assert provenance["source_count"] == 2
    assert provenance["primary_source_name"] == "MarkTechPost"

    attribution = kept.metadata["source_attribution"]
    assert attribution["count"] == 2
    assert set(attribution["labels"]) == {"MarkTechPost", "AI Hot"}
    urls = {d["url"] for d in attribution["detail"]}
    assert urls == {str(primary.url), str(duplicate.url)}
