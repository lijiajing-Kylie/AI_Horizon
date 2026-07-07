"""Content analysis using AI."""

import asyncio
from typing import Any, List
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

from .client import AIClient
from .prompts import CONTENT_ANALYSIS_SYSTEM, CONTENT_ANALYSIS_USER
from .prompts import TOPIC_CLASSIFICATION_SYSTEM, TOPIC_CLASSIFICATION_USER
from .utils import parse_json_response, split_content_and_comments, build_discussion_section
from ..models import ContentItem

DEFAULT_THROTTLE_SEC = 0.0


class ContentAnalyzer:
    """Analyzes content items using AI to determine importance."""

    def __init__(self, ai_client: AIClient):
        self.client = ai_client

    def _get_throttle_sec(self) -> float:
        """Return the configured inter-item throttle, clamped to zero or above."""
        config = getattr(self.client, "config", None)
        throttle_sec = getattr(config, "throttle_sec", DEFAULT_THROTTLE_SEC)
        return max(throttle_sec, 0.0)

    def _get_concurrency(self) -> int:
        """Return the configured analysis concurrency, clamped to 1 or above."""
        config = getattr(self.client, "config", None)
        concurrency = getattr(config, "analysis_concurrency", 1)
        return max(concurrency, 1)

    async def analyze_batch(self, items: List[ContentItem]) -> List[ContentItem]:
        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, index: int, progress_task) -> ContentItem:
            async with semaphore:
                try:
                    await self._analyze_item(item)
                except Exception as e:
                    print(f"Error analyzing item {item.id}: {e}")
                    item.ai_relevant = False
                    item.ai_score = 0.0
                    item.ai_reason = "Analysis failed"
                    item.ai_summary = item.title
                if throttle_sec > 0 and index < len(items) - 1:
                    await asyncio.sleep(throttle_sec)
            progress.advance(progress_task)
            return item

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing", total=len(items))
            coros = [
                _process(item, i, task) for i, item in enumerate(items)
            ]
            analyzed_items = await asyncio.gather(*coros)

        return analyzed_items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10)
    )
    async def _analyze_item(self, item: ContentItem) -> None:
        """Analyze a single content item.

        Args:
            item: Content item to analyze (modified in-place)
        """
        # Prepare content section
        text, comments = split_content_and_comments(item.content)
        has_comments = "--- Top Comments ---" in (item.content or "")
        content_limit = 800 if has_comments else 1000
        content_section = f"Content: {text[:content_limit]}" if text else ""

        # Prepare discussion section (comments, engagement)
        discussion_section = build_discussion_section(item.metadata, comments[:1500])

        # Generate user prompt
        user_prompt = CONTENT_ANALYSIS_USER.format(
            title=item.title,
            source=f"{item.source_type.value}",
            author=item.author or "Unknown",
            url=str(item.url),
            content_section=content_section,
            discussion_section=discussion_section
        )

        # Get AI completion
        response = await self.client.complete(
            system=CONTENT_ANALYSIS_SYSTEM,
            user=user_prompt,
        )

        # Parse JSON response with robust fallback
        result = parse_json_response(response)
        if result is None:
            print(f"Warning: could not parse analysis response for {item.id}, using defaults")
            item.ai_relevant = False
            item.ai_score = 0.0
            item.ai_reason = "Analysis response parse failed"
            item.ai_summary = item.title
            item.ai_tags = []
            return

        # Update item with analysis results
        item.ai_relevant = result.get("relevant", False)
        item.ai_score = float(result.get("score", 0))
        item.ai_reason = result.get("reason", "")
        item.ai_summary = result.get("summary", item.title)
        item.ai_tags = result.get("tags", [])

    # -- topic classification (second-stage) ----------------------------------

    @staticmethod
    def _format_topics_for_prompt(
        topics: list[dict],
    ) -> str:
        """Format a list of topic dicts into a readable prompt section.

        Each topic dict should have: slug, name, group_name, description,
        keywords (list), aliases (list).
        """
        by_group: dict[str, list[dict]] = {}
        for t in topics:
            by_group.setdefault(t["group_name"], []).append(t)

        lines = []
        for group_name in by_group:
            lines.append(f"### {group_name}")
            for t in by_group[group_name]:
                extras = []
                if t.get("keywords"):
                    extras.append(f"Keywords: {', '.join(t['keywords'])}")
                if t.get("aliases"):
                    extras.append(f"Also known as: {', '.join(t['aliases'])}")
                extra = " | " + " | ".join(extras) if extras else ""
                lines.append(
                    f"- {t['name']} (slug: `{t['slug']}`): {t.get('description', '')}{extra}"
                )
            lines.append("")

        return "\n".join(lines)

    async def classify_topics_batch(
        self,
        items: list[ContentItem],
        topics: list[dict],
    ) -> list[dict[str, Any]]:
        """Classify a batch of items with multi-dimensional topic tags.

        Args:
            items: Content items to classify (already scored + deduped)
            topics: List of topic dicts from the database (slug, name, etc.)

        Returns:
            List of dicts with keys: news_id, topics (list of topic dicts).
            Each topic dict has: slug, name, group_name, confidence, reason.
        """
        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        topics_prompt = self._format_topics_for_prompt(topics)

        async def _process(
            item: ContentItem, index: int, progress_task
        ) -> dict[str, Any]:
            async with semaphore:
                result = {"news_id": item.id, "topics": []}
                try:
                    result["topics"] = await self._classify_topics_for_item(
                        item, topics_prompt
                    )
                except Exception as e:
                    print(f"Error classifying topics for {item.id}: {e}")
                if throttle_sec > 0 and index < len(items) - 1:
                    await asyncio.sleep(throttle_sec)
            progress.advance(progress_task)
            return result

        results: list[dict[str, Any]] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Classifying topics", total=len(items))
            coros = [
                _process(item, i, task) for i, item in enumerate(items)
            ]
            results = await asyncio.gather(*coros)

        return results

    async def _classify_topics_for_item(
        self,
        item: ContentItem,
        topics_prompt: str,
    ) -> list[dict[str, Any]]:
        """Classify a single item with topic tags.

        Args:
            item: Content item to classify
            topics_prompt: Pre-formatted topics list for the prompt

        Returns:
            List of topic dicts with slug, name, group_name, confidence, reason.
        """
        # Prepare content section
        text, comments = split_content_and_comments(item.content)
        has_comments = "--- Top Comments ---" in (item.content or "")
        content_limit = 800 if has_comments else 1000
        content_section = f"Content: {text[:content_limit]}" if text else ""

        # Prepare discussion section
        discussion_section = build_discussion_section(item.metadata, comments[:1500])

        # Build user prompt
        user_prompt = TOPIC_CLASSIFICATION_USER.format(
            topics=topics_prompt,
            title=item.title,
            source=f"{item.source_type.value}",
            author=item.author or "Unknown",
            url=str(item.url),
            summary=item.ai_summary or item.title,
            tags=", ".join(item.ai_tags) if item.ai_tags else "",
            content_section=content_section,
            discussion_section=discussion_section,
        )

        # Get AI completion
        response = await self.client.complete(
            system=TOPIC_CLASSIFICATION_SYSTEM,
            user=user_prompt,
        )

        # Parse JSON response
        result = parse_json_response(response)
        if result is None:
            print(f"Warning: could not parse topic classification for {item.id}")
            return []

        topics = result.get("topics", [])
        if not isinstance(topics, list):
            return []

        # Validate and clean
        cleaned = []
        for t in topics:
            if not isinstance(t, dict):
                continue
            slug = (t.get("slug") or "").strip()
            if not slug:
                continue
            cleaned.append(
                {
                    "slug": slug,
                    "name": (t.get("name") or slug).strip(),
                    "group_name": (t.get("group_name") or "").strip(),
                    "confidence": float(t.get("confidence", 0.5)),
                    "reason": (t.get("reason") or "").strip(),
                }
            )

        return cleaned
