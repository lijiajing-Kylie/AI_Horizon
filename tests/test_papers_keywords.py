from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.ai.client import AIClient
from src.papers.keywords import extract_paper_keywords
from src.papers.models import Paper


class _FakeAIClient(AIClient):
    """Stub AIClient returning canned JSON responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, system, user, temperature=None, max_tokens=None):
        self.calls.append(user)
        return self.responses.pop(0) if self.responses else '{"keywords": []}'


def _paper(**overrides) -> Paper:
    defaults = dict(
        id="openalex:W1",
        source="openalex",
        native_id="W1",
        title="Diffusion Models for Image Generation",
        authors=["Alice"],
        abstract="We propose a diffusion model approach for high-fidelity image synthesis.",
        url="https://openalex.org/W1",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        categories=["Machine Learning"],
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Paper(**defaults)


def test_extract_paper_keywords_sets_and_truncates():
    fake = _FakeAIClient([
        '{"keywords": ["扩散模型", "Diffusion Model", "图像生成", "Image Generation", "注意力机制", "Attention", "训练"]}',
    ])
    papers = [_paper()]
    asyncio.run(extract_paper_keywords(fake, papers, concurrency=2))

    assert papers[0].keywords == [
        "扩散模型", "Diffusion Model", "图像生成",
        "Image Generation", "注意力机制",
    ]  # truncated to 5


def test_extract_paper_keywords_handles_bad_json_gracefully():
    fake = _FakeAIClient(["this is not json at all"])
    papers = [_paper()]
    asyncio.run(extract_paper_keywords(fake, papers, concurrency=2))

    assert papers[0].keywords == []


def test_extract_paper_keywords_skips_missing_keywords_field():
    fake = _FakeAIClient(['{"title_en": "Only a title"}'])
    papers = [_paper()]
    asyncio.run(extract_paper_keywords(fake, papers, concurrency=2))

    assert papers[0].keywords == []


def test_extract_paper_keywords_prompts_with_abstract():
    fake = _FakeAIClient(['{"keywords": ["A"]}'])
    paper = _paper()
    asyncio.run(extract_paper_keywords(fake, [paper], concurrency=2))

    assert "Diffusion Models for Image Generation" in fake.calls[0]
    assert "high-fidelity image synthesis" in fake.calls[0]
