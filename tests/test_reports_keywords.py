from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.ai.client import AIClient
from src.reports.keywords import extract_report_keywords
from src.reports.models import Report


class _FakeAIClient(AIClient):
    """Stub AIClient returning canned JSON responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, system, user, temperature=None, max_tokens=None):
        self.calls.append(user)
        return self.responses.pop(0) if self.responses else '{"keywords": []}'


def _report(**overrides) -> Report:
    defaults = dict(
        id="aliresearch:591792162400768000",
        source="aliresearch",
        native_id="591792162400768000",
        title="2026 人工智能十大趋势研判",
        institution="阿里研究院",
        author="阿里巴巴",
        url="http://www.aliresearch.com/ch/presentation/presentiondetails?articleCode=591792162400768000",
        summary="年度技术前瞻，聚焦大模型与行业落地。",
        content_text="报告指出，Transformer 架构持续演进，RAG 与 Agent 成为企业落地的核心路径……",
        categories=["趋势研判"],
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Report(**defaults)


def test_extract_report_keywords_sets_and_truncates():
    fake = _FakeAIClient([
        '{"keywords": ["大模型应用", "Transformer", "RAG", "Agent", "行业趋势", "政策解读", "产业升级", "云计算", "多余关键词", "再多一个"]}',
    ])
    reports = [_report()]
    asyncio.run(extract_report_keywords(fake, reports, concurrency=2))

    assert reports[0].keywords == [
        "大模型应用", "Transformer", "RAG", "Agent",
        "行业趋势", "政策解读", "产业升级", "云计算",
    ]  # truncated to 8


def test_extract_report_keywords_handles_bad_json_gracefully():
    fake = _FakeAIClient(["this is not json at all"])
    reports = [_report()]
    asyncio.run(extract_report_keywords(fake, reports, concurrency=2))

    assert reports[0].keywords == []


def test_extract_report_keywords_skips_missing_keywords_field():
    fake = _FakeAIClient(['{"summary": "Only a summary"}'])
    reports = [_report()]
    asyncio.run(extract_report_keywords(fake, reports, concurrency=2))

    assert reports[0].keywords == []


def test_extract_report_keywords_prompts_with_content():
    fake = _FakeAIClient(['{"keywords": ["大模型"]}'])
    report = _report()
    asyncio.run(extract_report_keywords(fake, [report], concurrency=2))

    assert "2026 人工智能十大趋势研判" in fake.calls[0]
    assert "阿里研究院" in fake.calls[0]
    assert "Transformer" in fake.calls[0]
