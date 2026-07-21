"""AI translation for paper titles and abstracts.

Uses the same AIClient infrastructure as the news pipeline. Translates
title + abstract from the detected source language (usually English) to
Simplified Chinese, skipping papers already in Chinese.
"""

import asyncio
import logging
import re
from typing import List

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from .models import Paper

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _detect_language(title: str, abstract: str) -> str:
    """Detect source language using CJK-character ratio heuristic.

    Returns ``"zh"`` when > 30 % of the characters are CJK, ``"en"``
    otherwise. Falls back to ``"unknown"`` when there is too little text.
    Mirrors the logic in ``src.ai.enricher:_detect_original_language``.
    """
    text = f"{title or ''} {abstract or ''}".strip()
    if not text:
        return "unknown"
    cjk = len(_CJK_RE.findall(text))
    total = len(text)
    if total == 0:
        return "unknown"
    return "zh" if cjk / total > 0.3 else "en"


async def translate_paper(client: AIClient, paper: Paper) -> Paper:
    """Translate a single paper's title and abstract to Simplified Chinese.

    If the paper is already in Chinese, sets ``original_language`` and
    copies the original fields as their own translations so the frontend
    can tell translation was considered but unnecessary.

    Never raises — failures are logged and the paper is returned with
    ``original_language`` set but no translation fields populated.
    """
    original_lang = _detect_language(paper.title, paper.abstract)
    paper.original_language = original_lang

    if original_lang == "zh":
        # Already Chinese — no translation needed; copy as-is so the
        # frontend sees both language variants populated identically.
        paper.title_zh = paper.title
        paper.abstract_zh = paper.abstract
        return paper

    if original_lang == "unknown":
        return paper

    # Truncate abstract to keep the AI prompt reasonably sized.
    abstract_snippet = paper.abstract[:2000] if paper.abstract else ""

    try:
        response = await client.complete(
            system=(
                "You are a translator specializing in academic papers. "
                "Translate the following paper title and abstract to Simplified Chinese. "
                "Preserve all technical terms, proper names (model names, institutions, "
                "person names), and acronyms in their original form. "
                "Output natural, fluent Chinese academic writing — not literal "
                "word-for-word translation. "
                "Return only valid JSON, no other text."
            ),
            user=(
                f"Title: {paper.title}\n"
                f"Abstract: {abstract_snippet}\n\n"
                'Return JSON:\n'
                '{"title_zh": "<中文标题>", "abstract_zh": "<中文摘要>"}'
            ),
            temperature=0.1,
        )
        result = parse_json_response(response)
        if result:
            if result.get("title_zh"):
                paper.title_zh = result["title_zh"]
            if result.get("abstract_zh"):
                paper.abstract_zh = result["abstract_zh"]
    except Exception:
        logger.warning(
            "Translation failed for paper %s", paper.id, exc_info=True
        )

    return paper


async def translate_papers(
    client: AIClient,
    papers: List[Paper],
    concurrency: int = 3,
) -> List[Paper]:
    """Translate a batch of papers with concurrency control.

    Papers already in Chinese (detected via CJK ratio) are skipped.
    Each translation runs behind an ``asyncio.Semaphore`` to avoid
    overwhelming the AI provider.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _translate_one(paper: Paper) -> Paper:
        # Skip papers already detected as Chinese (set by a prior
        # translate_paper call or pre-seeded).
        if paper.original_language == "zh":
            return paper
        async with sem:
            return await translate_paper(client, paper)

    tasks = [_translate_one(p) for p in papers]
    results = await asyncio.gather(*tasks)
    return list(results)
