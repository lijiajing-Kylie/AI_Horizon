"""Lightweight AI keyword extraction for the classic papers library.

Standalone from the news pipeline (same as ``src.papers.weekly``): only reuses
``AIClient`` and ``parse_json_response``. arXiv weekly-featured papers get their
keywords from the heavier ``weekly.py`` enrichment; this module covers the
classic sources (openalex / huggingface) plus the ``--extract-keywords``
backfill.

Language policy: proper nouns / technical terms keep their original language
(English); generic descriptive words come out in Simplified Chinese.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from .models import Paper
from .progress import run_progress

logger = logging.getLogger(__name__)

KEYWORDS_SYSTEM = """你是一位学术编辑。根据论文标题、分类与摘要，提取 3-5 个关键词。

规则：
- 关键词必须使用简体中文，通用术语一律翻译成中文（如 "compound options" 写"复合期权"、"multi-stage real options" 写"多阶段实物期权"）
- 只有没有通用中文译法的专有名词才可保留英文原文：方法名、模型名、算法名、以人名命名的概念（如 "COS方法"、"Lévy过程"、"Transformer"）
- 禁止整条关键词都是英文，列表中的大多数关键词必须是中文
- 只输出合法 JSON，不要 markdown"""

KEYWORDS_USER = """为以下论文提取关键词。
标题：{title}
分类：{categories}
摘要：{abstract}

仅返回 JSON：
{{ "keywords": ["<关键词1>", "<关键词2>", ...] }}"""


def _get_concurrency(ai_client: AIClient) -> int:
    """Read the configured analysis concurrency, clamped to ≥ 1."""
    config = getattr(ai_client, "config", None)
    return max(getattr(config, "analysis_concurrency", 1) or 1, 1)


async def extract_paper_keywords(
    ai_client: AIClient,
    papers: List[Paper],
    concurrency: int,
) -> None:
    """AI-extract ≤5 keywords per paper. Failures leave keywords empty."""
    if not papers:
        return
    semaphore = asyncio.Semaphore(concurrency)

    async def _extract_one(paper: Paper) -> None:
        async with semaphore:
            try:
                await _extract_keywords_for_paper(ai_client, paper)
            except Exception:
                logger.warning(
                    "Keyword extraction failed for %s", paper.id, exc_info=True,
                )

    await run_progress("提取关键词", [_extract_one(p) for p in papers])


async def _extract_keywords_for_paper(ai_client: AIClient, paper: Paper) -> None:
    response = await ai_client.complete(
        system=KEYWORDS_SYSTEM,
        user=KEYWORDS_USER.format(
            title=paper.title,
            categories=", ".join(paper.categories),
            abstract=(paper.abstract or "")[:2000],
        ),
        temperature=0.2,
        max_tokens=150,
    )
    result = parse_json_response(response)
    if result and result.get("keywords"):
        paper.keywords = [
            str(k).strip() for k in result["keywords"][:5] if str(k).strip()
        ]
