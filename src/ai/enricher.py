"""Content enrichment using AI (second-pass analysis).

For items that pass the score threshold, this module:
1. Searches the web for relevant context (via DuckDuckGo)
2. Feeds search results + item content to AI to generate grounded background knowledge
"""

import asyncio
import re
import sys
import os
from datetime import datetime, timezone
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn
from ddgs import DDGS

from .client import AIClient
from .content_selection import resolve_content, build_enrichment_input, content_hash
from .html_translator import translate_display_html
from .prompts import (
    CONCEPT_EXTRACTION_SYSTEM, CONCEPT_EXTRACTION_USER,
    CONTENT_ENRICHMENT_SYSTEM, CONTENT_ENRICHMENT_USER,
)
from .utils import parse_json_response, split_content_and_comments
from ..models import ContentItem

# ── original-language detection ────────────────────────────────────────────

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _detect_original_language(item: ContentItem) -> str:
    """Detect original language using CJK-character ratio heuristic.

    Returns ``"zh"`` when > 30 % of the characters are CJK, ``"en"`` otherwise.
    Falls back to ``"unknown"`` when there is too little text.

    Deliberately excludes ``item.ai_summary``: the first-pass analyzer
    prompt (``CONTENT_ANALYSIS_USER``) forces that field to always be
    written in Chinese regardless of the source language, so including it
    would bias every item toward "zh" instead of reflecting the actual
    source text. Only ``title`` and the resolved article text (clean/raw
    extraction, or the scraper's own summary — never the ambiguous legacy
    ``content`` field) are genuine signals of the original language.
    """
    text = " ".join([
        item.title or "",
        resolve_content(item).text,
    ])
    if not text.strip():
        return "unknown"
    cjk = len(_CJK_RE.findall(text))
    total = len(text)
    if total == 0:
        return "unknown"
    return "zh" if cjk / total > 0.3 else "en"


def _stamp_language_metadata(item: ContentItem) -> None:
    """Write ``original_language`` / ``is_ai_translated`` metadata.

    Called after enrichment (or fallback translation) so the API and
    frontend know which languages are available and which is the original.
    """
    import re as _re_mod
    now = datetime.now(timezone.utc).isoformat()
    original = _detect_original_language(item)
    available: list[str] = []
    if item.metadata.get("title_en"):
        available.append("en")
    if item.metadata.get("title_zh"):
        available.append("zh")
    # Ensure the detected language is present
    if original not in available and original in ("en", "zh"):
        available.insert(0, original)
    item.metadata["original_language"] = original
    item.metadata["available_languages"] = available
    item.metadata["default_display_language"] = "zh"
    item.metadata["is_ai_translated"] = (
        original != "zh" and "zh" in available
    )
    item.metadata["translation_provider"] = (
        "llm" if item.metadata["is_ai_translated"] else None
    )
    item.metadata["translated_at"] = (
        now if item.metadata["is_ai_translated"] else None
    )


class ContentEnricher:
    """Enriches high-scoring content items with background knowledge."""

    def __init__(self, ai_client: AIClient):
        self.client = ai_client

    def _get_concurrency(self) -> int:
        """Return the configured enrichment concurrency, clamped to 1 or above."""
        config = getattr(self.client, "config", None)
        concurrency = getattr(config, "enrichment_concurrency", 1)
        return max(concurrency, 1)

    async def enrich_batch(self, items: List[ContentItem]) -> None:
        """Enrich items in-place with background knowledge.

        Args:
            items: Content items to enrich (modified in-place)
        """
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, progress_task) -> None:
            async with semaphore:
                try:
                    await self._enrich_item(item)
                except Exception as e:
                    print(f"Error enriching item {item.id}: {e}, falling back to translation")
                    await self._translate_item(item)
                try:
                    await self._translate_html(item)
                except Exception as e:
                    print(f"Error translating article HTML for {item.id}: {e}")
            progress.advance(progress_task)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Enriching", total=len(items))
            coros = [
                _process(item, task) for item in items
            ]
            await asyncio.gather(*coros)

    async def _web_search(self, query: str, max_results: int = 3) -> list:
        """Search the web for context via DuckDuckGo.

        Returns:
            List of dicts with keys: title, url, body
        """
        try:
            # Suppress primp "Impersonate ... does not exist" stderr warning
            stderr = sys.stderr
            sys.stderr = open(os.devnull, "w")
            try:
                ddgs = DDGS()
                results = await asyncio.to_thread(ddgs.text, query, max_results=max_results)
            finally:
                sys.stderr.close()
                sys.stderr = stderr
        except Exception:
            return []

        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")}
            for r in (results or [])
        ]

    async def _extract_concepts(self, item: ContentItem, content_text: str, source_note: str = "") -> List[str]:
        """Ask AI to identify concepts that need explanation.

        Args:
            item: Content item
            content_text: Extracted content text
            source_note: Warning line when content_text is only a summary (see build_source_note)

        Returns:
            List of search queries for concepts that need explanation
        """
        user_prompt = CONCEPT_EXTRACTION_USER.format(
            title=item.title,
            summary=item.ai_summary or item.title,
            tags=", ".join(item.ai_tags) if item.ai_tags else "",
            content=content_text[:1000],
            source_note=source_note,
        )

        try:
            response = await self.client.complete(
                system=CONCEPT_EXTRACTION_SYSTEM,
                user=user_prompt,
            )
            result = parse_json_response(response)
            if result is None:
                return []
            queries = result.get("queries", [])
            return queries[:3]
        except Exception:
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10)
    )
    async def _enrich_item(self, item: ContentItem) -> None:
        """Enrich a single item with background knowledge.

        Steps:
        1. Ask AI which concepts in the news need explanation
        2. Search the web for those concepts
        3. Ask AI to generate background based on search results

        Args:
            item: Content item to enrich (modified in-place via metadata)
        """
        # Extract content text and comments separately — clean_content > raw_content > rss_summary
        _text, comments_text = split_content_and_comments(resolve_content(item).text)
        comments_text = comments_text[:2000]
        enrichment_input = build_enrichment_input(item)
        content_text = enrichment_input.text
        source_note = enrichment_input.source_note

        # Step 1: AI identifies concepts to explain
        queries = await self._extract_concepts(item, content_text, source_note)

        # Step 2: Search web for each concept
        all_results = []
        web_sections = []
        for query in queries:
            results = await self._web_search(query)
            all_results.extend(results)
            if results:
                lines = [f"- [{r['title']}]({r['url']}): {r['body']}" for r in results]
                web_sections.append(f"**{query}:**\n" + "\n".join(lines))
        web_context = "\n\n".join(web_sections) if web_sections else ""

        # Index of available URLs for citation validation
        available_urls = {r["url"]: r["title"] for r in all_results if r.get("url")}

        # Step 3: AI generates background grounded in search results
        user_prompt = CONTENT_ENRICHMENT_USER.format(
            title=item.title,
            url=str(item.url),
            summary=item.ai_summary or item.title,
            score=item.ai_score or 0,
            reason=item.ai_reason or "",
            tags=", ".join(item.ai_tags) if item.ai_tags else "",
            content=content_text,
            source_note=source_note,
            comments_section=f"\n**Community Comments:**\n{comments_text}" if comments_text else "",
            related_context=web_context or "No related background available.",
        )

        response = await self.client.complete(
            system=CONTENT_ENRICHMENT_SYSTEM,
            user=user_prompt,
        )

        # Parse JSON response with robust fallback
        result = parse_json_response(response)
        if result is None:
            # Gracefully degrade: fall back to a lightweight translation
            # instead of dropping the item untranslated.
            print(f"Warning: could not parse enrichment response for {item.id}, falling back to translation")
            await self._translate_item(item)
            return

        # Combine structured sub-fields into per-language detailed_summary
        for lang in ("en", "zh"):
            if result.get(f"title_{lang}"):
                val = result[f"title_{lang}"]
                item.metadata[f"title_{lang}"] = val.get("text") or str(val) if isinstance(val, dict) else str(val)

            parts = []
            for field in ("whats_new", "why_it_matters", "key_details"):
                text = result.get(f"{field}_{lang}", "").strip()
                if text:
                    parts.append(text)
            if parts:
                item.metadata[f"detailed_summary_{lang}"] = " ".join(parts)

            if result.get(f"community_discussion_{lang}"):
                val = result[f"community_discussion_{lang}"]
                item.metadata[f"community_discussion_{lang}"] = val.get("text") or str(val) if isinstance(val, dict) else str(val)

        # Store bilingual scoring reason for downstream rendering
        for lang in ("en", "zh"):
            key = f"reason_{lang}"
            if result.get(key):
                val = result[key]
                item.metadata[key] = val.get("text") or str(val) if isinstance(val, dict) else str(val)

        # Store enrichment citation sources — only URLs from our search results.
        # Uses "enrichment_sources" to avoid collision with source_provenance.
        if result.get("sources") and available_urls:
            valid = [
                {"url": u, "title": available_urls[u]}
                for u in result["sources"]
                if u in available_urls
            ]
            if valid:
                item.metadata["enrichment_sources"] = valid

        # Backward-compatible fallback fields (English as default)
        item.metadata["detailed_summary"] = item.metadata.get("detailed_summary_en", "")
        item.metadata["community_discussion"] = item.metadata.get("community_discussion_en", "")

        # Stamp original-language tracking metadata
        _stamp_language_metadata(item)

        # Record only — see content_hash() docstring: nothing reads this
        # back to skip a future enrichment call, it's bookkeeping for later
        # staleness detection.
        item.metadata["enrichment_source_hash"] = content_hash(content_text)

    async def _translate_item(self, item: ContentItem) -> None:
        """Lightweight translation fallback: when full enrichment fails, at least
        translate the title and summary to Chinese so the item is not dropped."""
        try:
            response = await self.client.complete(
                system="You are a translator. Translate to Simplified Chinese. Return only valid JSON, no other text.",
                user=(
                    f'Title: {item.title}\n'
                    f'Summary: {item.ai_summary or item.title}\n'
                    f'Reason: {item.ai_reason or ""}\n\n'
                    'Return JSON:\n'
                    '{"title_zh": "<中文标题>", "summary_zh": "<用中文写1-2句摘要>", "reason_zh": "<用中文写一句话，表达相同的评分判断>"}'
                ),
            )
            result = parse_json_response(response)
            if result:
                if result.get("title_zh"):
                    item.metadata["title_zh"] = result["title_zh"]
                if result.get("summary_zh"):
                    item.metadata["detailed_summary_zh"] = result["summary_zh"]
                if result.get("reason_zh"):
                    item.metadata["reason_zh"] = result["reason_zh"]
                # Record only, per content_hash()'s docstring — no skip logic reads this.
                item.metadata["enrichment_source_hash"] = content_hash(
                    f"{item.title}|{item.ai_summary}|{item.ai_reason}"
                )
            _stamp_language_metadata(item)
        except Exception:
            pass

    async def _translate_html(self, item: ContentItem) -> None:
        """Populate ``display_html_zh`` when the article body isn't already Chinese.

        Runs independently of ``_enrich_item``/``_translate_item`` (title/summary
        translation) so a failure or skip here never affects them, and vice
        versa. Never raises — a failed translation just leaves
        ``display_html_zh`` unset, and the frontend falls back to
        ``display_html``.
        """
        if not item.display_html:
            return
        if _detect_original_language(item) == "zh":
            item.display_html_zh = item.display_html
            return
        item.display_html_zh = await translate_display_html(self.client, item.display_html)
        if item.display_html_zh:
            # Record only, per content_hash()'s docstring — no skip logic
            # reads this back; every run still re-translates unconditionally.
            item.metadata["display_html_source_hash"] = content_hash(item.display_html)
