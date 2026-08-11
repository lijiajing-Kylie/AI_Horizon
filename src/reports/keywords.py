"""AI keyword extraction for the research-reports library.

Standalone from the news pipeline (same as ``src.papers.keywords``): only
reuses ``AIClient``, ``parse_json_response``, and the shared progress helper.
Called from ``src/reports/cli.py`` for freshly fetched reports and for the
``backfill-keywords`` subcommand that adds keywords to previously-stored ones.

Language policy: technical terms / proper nouns keep their original language
(English); generic descriptive words come out in Simplified Chinese.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..papers.progress import run_progress
from .models import Report

logger = logging.getLogger(__name__)

KEYWORDS_SYSTEM = """你是一位科技类研究报告的编辑。根据报告的标题、机构、摘要与正文节选，提取 5-8 个能概括该报告核心思想与主要内容的关键词。

规则：
- 关键词必须覆盖报告的核心思想与主要内容，避免空洞的泛称
- 技术术语与专有名词保留英文原文（如 "Transformer"、"RAG"、"DeepSeek"、"Agent"）
- 通用描述性词使用简体中文（如 "大模型应用"、"行业趋势"、"政策解读"）
- 大多数关键词应为中文，只有没有通用中文译法的专有名词才保留英文
- 只输出合法 JSON，不要 markdown"""

KEYWORDS_USER = """为以下报告提取关键词。
标题：{title}
机构：{institution}
摘要：{summary}
正文（节选）：{content}

仅返回 JSON：
{{ "keywords": ["<关键词1>", "<关键词2>", ...] }}"""


def _get_concurrency(ai_client: AIClient) -> int:
    """Read the configured analysis concurrency, clamped to ≥ 1."""
    config = getattr(ai_client, "config", None)
    return max(getattr(config, "analysis_concurrency", 1) or 1, 1)


async def extract_report_keywords(
    ai_client: AIClient,
    reports: List[Report],
    concurrency: int,
) -> None:
    """AI-extract 5-8 keywords per report. Failures leave keywords empty."""
    if not reports:
        return
    semaphore = asyncio.Semaphore(concurrency)

    async def _extract_one(report: Report) -> None:
        async with semaphore:
            try:
                await _extract_keywords_for_report(ai_client, report)
            except Exception:
                logger.warning(
                    "Keyword extraction failed for %s", report.id, exc_info=True,
                )

    await run_progress("提取关键词", [_extract_one(r) for r in reports])


async def _extract_keywords_for_report(ai_client: AIClient, report: Report) -> None:
    summary = (report.summary or "")[:300]
    content = (report.content_text or "")[:3000]
    user = KEYWORDS_USER.format(
        title=report.title,
        institution=report.institution,
        summary=summary,
        content=content,
    )
    response = ""
    # DeepSeek 等 provider 偶发对相同 prompt 返回空 content；空响应时轻量重试。
    for attempt in range(3):
        if attempt:
            await asyncio.sleep(2)
        response = await ai_client.complete(
            system=KEYWORDS_SYSTEM,
            user=user,
            temperature=0.2,
            max_tokens=200,
        )
        if response.strip():
            break
    result = parse_json_response(response)
    if result and result.get("keywords"):
        report.keywords = [
            str(k).strip() for k in result["keywords"][:8] if str(k).strip()
        ]
