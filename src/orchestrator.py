"""Main orchestrator coordinating the entire workflow."""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse
import httpx
from rich.console import Console

logger = logging.getLogger(__name__)

from .models import Config, ContentItem, sub_source_label
from .storage.manager import StorageManager
from .storage.db import HorizonDB
from .services.email import EmailManager
from .services.webhook import WebhookNotifier
from .scrapers.github import GitHubScraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper
from .scrapers.reddit import RedditScraper
from .scrapers.telegram import TelegramScraper
from .scrapers.twitter import TwitterScraper
from .scrapers.twitter_playwright import TwitterPlaywrightScraper
from .scrapers.openbb import OpenBBScraper
from .scrapers.ossinsight import OSSInsightScraper
from .scrapers.gdelt import GDELTScraper
from .scrapers.google_news import GoogleNewsScraper
from .ai.client import create_ai_client
from .ai.analyzer import ContentAnalyzer
from .ai.summarizer import DailySummarizer
from .ai.enricher import ContentEnricher
from .ai.tokens import get_usage_snapshot
from .content_extractor import extract_full_content, EXTRACTOR_VERSION
from .seed_topics import build_seed_topics
from .filtering import BalancedDigestResult, apply_balanced_digest
from .dedup import (
    build_source_attribution,
    merge_cross_source_duplicates,
    merge_topic_duplicates,
)


class HorizonOrchestrator:
    """Orchestrates the complete workflow for content aggregation and analysis."""

    def __init__(self, config: Config, storage: StorageManager):
        """Initialize orchestrator.

        Args:
            config: Application configuration
            storage: Storage manager
        """
        self.config = config
        self.storage = storage
        self.db = HorizonDB()
        self.console = Console()
        self.email_manager = EmailManager(config.email, console=self.console) if config.email else None
        self.webhook_notifier = (
            WebhookNotifier(config.webhook, console=self.console)
            if config.webhook and config.webhook.enabled
            else None
        )

    async def run(self, force_hours: int = None) -> None:
        """Execute the complete workflow.

        Args:
            force_hours: Optional override for time window in hours
        """
        self.console.print("[bold cyan]🌅 Horizon - Starting aggregation...[/bold cyan]\n")

        # Check email subscriptions if configured
        if (
            self.email_manager
            and self.config.email
            and self.config.email.enabled
            and self.config.email.imap_enabled
        ):
            self.console.print("📧 Checking for new email subscriptions...")
            self.email_manager.check_subscriptions(self.storage)

        # Ensure topic seed data exists
        self._seed_topics()

        try:
            # 1. Determine time window
            since = self._determine_time_window(force_hours)
            self.console.print(f"📅 Fetching content since: {since.strftime('%Y-%m-%d %H:%M:%S')}\n")

            # 2. Fetch content from all sources
            all_items = await self.fetch_all_sources(since)
            self.console.print(f"📥 Fetched {len(all_items)} items from all sources\n")

            # 2.5 Extract full article text for each item
            all_items = await self._extract_full_content(all_items)

            if not all_items:
                self.console.print("[yellow]No new content found. Exiting.[/yellow]")
                return

            # 3. Merge cross-source duplicates (same URL from different sources)
            merged_items = self.merge_cross_source_duplicates(all_items)
            if len(merged_items) < len(all_items):
                self.console.print(
                    f"🔗 Merged {len(all_items) - len(merged_items)} cross-source duplicates "
                    f"→ {len(merged_items)} unique items\n"
                )

            # 4. Analyze with AI
            analyzed_items = await self._analyze_content(merged_items)
            self.console.print(f"🤖 Analyzed {len(analyzed_items)} items with AI\n")

            # 4.1 Persist ALL scored items immediately (selected=False) so
            #     dropped items are available for later audit queries.
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.db.save_items(analyzed_items, today, len(all_items), selected=False, replace=True)
            self.console.print(f"💾 Persisted {len(analyzed_items)} scored items to SQLite (pre-filter)\n")

            # 4.5 Filter by AI relevance (binary gate — only AI/LLM content passes)
            relevant_items = [
                item for item in analyzed_items
                if item.ai_relevant is True
            ]
            skipped_relevance = len(analyzed_items) - len(relevant_items)
            if skipped_relevance > 0:
                self.console.print(
                    f"🎯 {len(relevant_items)} items are AI-relevant "
                    f"({skipped_relevance} non-relevant items dropped)\n"
                )
            relevant_ids = {item.id for item in relevant_items}

            # 5. Filter by score threshold
            threshold = self.config.filtering.ai_score_threshold
            max_items = self.config.filtering.max_items

            above_threshold = [
                item for item in relevant_items
                if item.ai_score and item.ai_score >= threshold
            ]
            below_threshold = [
                item for item in relevant_items
                if item.ai_score and item.ai_score < threshold
            ]
            # Sort both groups descending by score
            above_threshold.sort(key=lambda x: x.ai_score or 0, reverse=True)
            below_threshold.sort(key=lambda x: x.ai_score or 0, reverse=True)

            # Backfill: when above-threshold items are fewer than max_items,
            # take the highest-scoring items below threshold to fill the gap.
            important_items = above_threshold
            if max_items is not None and len(important_items) < max_items:
                needed = max_items - len(important_items)
                important_items = important_items + below_threshold[:needed]
                # Re-sort merged list
                important_items.sort(key=lambda x: x.ai_score or 0, reverse=True)
                self.console.print(
                    f"⭐️ {len(above_threshold)} items scored ≥ {threshold}, "
                    f"backfilled {min(needed, len(below_threshold))} below-threshold "
                    f"→ {len(important_items)} total (max_items={max_items})\n"
                )
            else:
                self.console.print(
                    f"⭐️ {len(important_items)} items scored ≥ {threshold}\n"
                )
            score_passed_ids = {item.id for item in important_items}

            # 5.5 Semantic deduplication: drop items covering the same topic
            deduped_items = await self.merge_topic_duplicates(important_items)
            if len(deduped_items) < len(important_items):
                self.console.print(
                    f"🧹 Removed {len(important_items) - len(deduped_items)} topic duplicates "
                    f"→ {len(deduped_items)} unique items\n"
                )
            important_items = deduped_items
            deduped_ids = {item.id for item in important_items}

            # 5.51 Build unified source attribution for display
            self._build_source_attribution(important_items)

            # 5.6 Optional second-stage Twitter reply expansion + targeted re-analysis
            await self._expand_twitter_discussion(important_items)

            # 5.7 Topic classification: assign multi-dimensional topic tags
            await self._classify_topics(important_items)

            # 5.8 Apply per-category and global digest limits before enrichment
            balanced_result = self.apply_balanced_digest(important_items)
            important_items = balanced_result.items
            final_ids = {item.id for item in important_items}

            # 5.9 Compute drop reasons and mark selection in SQLite
            drop_reason_map: dict[str, str] = {}
            for item in analyzed_items:
                if item.id not in relevant_ids:
                    drop_reason_map[item.id] = "relevance"
                elif item.id not in score_passed_ids:
                    drop_reason_map[item.id] = "score"
                elif item.id not in deduped_ids:
                    drop_reason_map[item.id] = "topic_duplicate"
                elif item.id not in final_ids:
                    drop_reason_map[item.id] = "category_quota"

            self.db.mark_selected(final_ids, drop_reason_map, today)
            dropped_count = len(drop_reason_map)
            if dropped_count > 0:
                self.console.print(
                    f"📋 Audited {dropped_count} dropped items in SQLite "
                    f"(relevance: {sum(1 for v in drop_reason_map.values() if v == 'relevance')}, "
                    f"score: {sum(1 for v in drop_reason_map.values() if v == 'score')}, "
                    f"topic_dup: {sum(1 for v in drop_reason_map.values() if v == 'topic_duplicate')}, "
                    f"quota: {sum(1 for v in drop_reason_map.values() if v == 'category_quota')})\n"
                )

            # Show per-sub-source selection breakdown
            selected_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                key = f"{item.source_type.value}/{sub_source_label(item)}"
                selected_counts[key] += 1
            for source_key, count in sorted(selected_counts.items()):
                self.console.print(f"      • {source_key}: {count}")
            self.console.print("")

            # 6. Search related stories + enrich with background knowledge (2nd AI pass)
            await self._enrich_important_items(important_items)

            # 6.5 Update persisted items with enrichment results
            saved = self.db.save_items(important_items, today, len(all_items), selected=True, replace=False)
            self.console.print(f"💾 Updated {saved} items with enrichment data in SQLite\n")

            # 6.6 Persist topic classifications to news_topics
            topic_count = 0
            for item in important_items:
                topics_data = item.metadata.pop("_topics_classification", [])
                if topics_data:
                    topic_count += self.db.save_news_topics(item.id, topics_data)
            if topic_count > 0:
                self.console.print(f"🏷️ Saved {topic_count} topic associations\n")

            # 7. Generate and save daily summaries for each configured language
            for lang in self.config.ai.languages:
                summarizer = DailySummarizer()
                summary = await summarizer.generate_summary(important_items, today, len(all_items), language=lang)

                # Save to data/summaries/
                summary_path = self.storage.save_daily_summary(today, summary, language=lang)
                self.console.print(f"💾 Saved {lang.upper()} summary to: {summary_path}\n")

                # Copy to docs/ for GitHub Pages
                try:
                    from pathlib import Path

                    post_filename = f"{today}-summary-{lang}.md"
                    posts_dir = Path("docs/_posts")
                    posts_dir.mkdir(parents=True, exist_ok=True)

                    dest_path = posts_dir / post_filename

                    # Add Jekyll front matter
                    front_matter = (
                        "---\n"
                        "layout: default\n"
                        f"title: \"Horizon Summary: {today} ({lang.upper()})\"\n"
                        f"date: {today}\n"
                        f"lang: {lang}\n"
                        "---\n\n"
                    )

                    # Strip leading H1 header to avoid duplication with Jekyll title
                    summary_content = summary
                    first_line = summary_content.strip().split("\n")[0]
                    if first_line.startswith("# "):
                        parts = summary_content.split("\n", 1)
                        if len(parts) > 1:
                            summary_content = parts[1].strip()

                    with open(dest_path, "w", encoding="utf-8") as f:
                        f.write(front_matter + summary_content)

                    self.console.print(f"📄 Copied {lang.upper()} summary to GitHub Pages: {dest_path}\n")
                except Exception as e:
                    self.console.print(f"[yellow]⚠️  Failed to copy {lang.upper()} summary to docs/: {e}[/yellow]\n")

                # Send email if configured
                if self.email_manager and self.config.email and self.config.email.enabled:
                    self.console.print(f"📧 Sending {lang.upper()} email summary...")
                    subscribers = self.storage.load_subscribers()
                    subject = f"Horizon Summary ({lang.upper()}) - {today}"
                    self.email_manager.send_daily_summary(summary, subject, subscribers)

                # Send webhook notification if configured
                if self.webhook_notifier:
                    await self.webhook_notifier.send_daily_summary(
                        summary=summary,
                        important_items=important_items,
                        all_items_count=len(all_items),
                        date=today,
                        lang=lang,
                        summarizer=summarizer,
                    )

            self.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
            usage = get_usage_snapshot()
            if usage.total_tokens > 0:
                self.console.print(
                    f"\n🧮 Token usage this run: "
                    f"{usage.total_tokens} tokens "
                    f"(input: {usage.total_input_tokens}, output: {usage.total_output_tokens})"
                )
                for provider, u in sorted(usage.per_provider.items()):
                    if u.total <= 0:
                        continue
                    self.console.print(
                        f"   • {provider}: {u.total} tokens "
                        f"(in: {u.input_tokens}, out: {u.output_tokens})"
                    )

        except Exception as e:
            self.console.print(f"[bold red]❌ Error: {e}[/bold red]")

            # Send webhook failure notification if configured
            if self.webhook_notifier:
                await self.webhook_notifier.send_failure(
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    error_message=str(e),
                )

            raise

    def _determine_time_window(self, force_hours: int = None) -> datetime:
        if force_hours:
            since = datetime.now(timezone.utc) - timedelta(hours=force_hours)
        else:
            hours = self.config.filtering.time_window_hours
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return since

    async def fetch_all_sources(self, since: datetime) -> List[ContentItem]:
        """Fetch content from all configured sources.

        This is a stable stage entry point for integrations such as MCP.

        Args:
            since: Fetch items published after this time

        Returns:
            List[ContentItem]: All fetched items
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []

            # GitHub sources
            if self.config.sources.github:
                github_scraper = GitHubScraper(self.config.sources.github, client)
                tasks.append(self._fetch_with_progress("GitHub", github_scraper, since))

            # Hacker News
            if self.config.sources.hackernews.enabled:
                hn_scraper = HackerNewsScraper(self.config.sources.hackernews, client)
                tasks.append(self._fetch_with_progress("Hacker News", hn_scraper, since))

            # RSS feeds
            if self.config.sources.rss:
                rss_scraper = RSSScraper(self.config.sources.rss, client)
                tasks.append(self._fetch_with_progress("RSS Feeds", rss_scraper, since))

            # Reddit
            if self.config.sources.reddit.enabled:
                reddit_scraper = RedditScraper(self.config.sources.reddit, client)
                tasks.append(self._fetch_with_progress("Reddit", reddit_scraper, since))

            # Telegram
            if self.config.sources.telegram.enabled:
                telegram_scraper = TelegramScraper(self.config.sources.telegram, client)
                tasks.append(self._fetch_with_progress("Telegram", telegram_scraper, since))

            # Twitter (Apify or Playwright mode)
            if self.config.sources.twitter and self.config.sources.twitter.enabled:
                tw_cfg = self.config.sources.twitter
                if tw_cfg.mode == "playwright":
                    twitter_scraper = TwitterPlaywrightScraper(tw_cfg)
                else:
                    twitter_scraper = TwitterScraper(tw_cfg, client)
                tasks.append(self._fetch_with_progress("Twitter", twitter_scraper, since))

            # OpenBB (financial news / filings via the OpenBB Platform SDK)
            if self.config.sources.openbb and self.config.sources.openbb.enabled:
                openbb_scraper = OpenBBScraper(self.config.sources.openbb, client)
                tasks.append(self._fetch_with_progress("OpenBB", openbb_scraper, since))

            # OSS Insight trending repos
            if self.config.sources.ossinsight and self.config.sources.ossinsight.enabled:
                oss_scraper = OSSInsightScraper(self.config.sources.ossinsight, client)
                tasks.append(self._fetch_with_progress("OSS Insight", oss_scraper, since))

            # GDELT 2.0 DOC API (key-less global news)
            if self.config.sources.gdelt and self.config.sources.gdelt.enabled:
                gdelt_scraper = GDELTScraper(self.config.sources.gdelt, client)
                tasks.append(self._fetch_with_progress("GDELT", gdelt_scraper, since))

            # Google News RSS (key-less news search)
            if self.config.sources.google_news and self.config.sources.google_news.enabled:
                gn_scraper = GoogleNewsScraper(self.config.sources.google_news, client)
                tasks.append(self._fetch_with_progress("Google News", gn_scraper, since))

            # Fetch all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten results
            all_items = []
            for result in results:
                if isinstance(result, Exception):
                    self.console.print(f"[red]Error fetching source: {result}[/red]")
                elif isinstance(result, list):
                    all_items.extend(result)

            return all_items

    async def _extract_full_content(self, items: List[ContentItem]) -> List[ContentItem]:
        """Extract full article text for each item's URL using trafilatura.

        For each item, fetches the original URL and runs readability-based
        extraction. ``item.rss_summary`` always captures the scraper's
        original snippet, success or failure. On success, ``item.raw_content``
        holds the extractor's plain-text output and ``item.content`` (the
        legacy alias) is updated to match it. On failure/skip, ``content``
        is left unchanged (it already equals the scraper snippet).
        ``content_source``/``extraction_status``/``extraction_error`` record
        which case happened, so downstream AI prompts don't mistake "only a
        summary" for "thin content".

        Args:
            items: Content items from all scrapers.

        Returns:
            The same list (mutated in-place).
        """
        if not items:
            return items

        # source_label -> {"total": n, "extracted": n, "skipped": n}
        source_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "extracted": 0, "skipped": 0}
        )
        skipped_records: List[dict] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            semaphore = asyncio.Semaphore(8)  # limit concurrent fetches

            async def _extract_one(item: ContentItem) -> None:
                source_label = f"{item.source_type.value}:{sub_source_label(item)}"
                original_content = item.content or ""
                item.rss_summary = original_content

                async with semaphore:
                    extract_debug: dict = {}
                    result = await extract_full_content(
                        str(item.url), client, debug=extract_debug
                    )

                stats = source_stats[source_label]
                stats["total"] += 1

                item.http_status = extract_debug.get("http_status")
                item.extracted_at = datetime.now(timezone.utc)
                item.extractor_version = EXTRACTOR_VERSION

                if result:
                    item.raw_content = result.text
                    item.content = result.text  # legacy alias, unchanged behavior
                    item.cover_image = result.cover_image
                    item.images = result.images
                    item.raw_html = result.raw_html
                    item.display_html = result.display_html
                    item.final_url = result.final_url
                    item.text_length = len(result.text)
                    item.content_source = "full_text"
                    item.extraction_status = "success"
                    item.extraction_error = None
                    stats["extracted"] += 1
                else:
                    skip_reason = extract_debug.get("skip_reason")
                    item.extraction_error = skip_reason
                    item.extraction_status = (
                        "skipped"
                        if skip_reason and skip_reason.startswith(("skip_domain:", "skip_extension:"))
                        else "failed"
                    )
                    item.content_source = "rss_summary" if original_content.strip() else "none"
                    stats["skipped"] += 1
                    skipped_records.append(
                        {
                            "title": item.title,
                            "url": str(item.url),
                            "source": source_label,
                            "skip_reason": skip_reason,
                            "http_status": extract_debug.get("http_status"),
                            "rss_had_content": bool(original_content.strip()),
                            "rss_content_length": len(original_content.strip()),
                        }
                    )

            await asyncio.gather(*[_extract_one(item) for item in items])

        extracted = sum(1 for item in items if item.extraction_status == "success")
        skipped = len(items) - extracted
        self.console.print(
            f"📄 成功提取 {extracted} 篇完整正文 / {skipped} 篇跳过\n"
        )

        logger.debug("Full-content extraction stats by source:")
        for source_label, stats in sorted(source_stats.items()):
            total = stats["total"]
            skip_ratio = stats["skipped"] / total if total else 0.0
            logger.debug(
                "  source=%s total=%d extracted=%d skipped=%d skip_ratio=%.1f%%",
                source_label, total, stats["extracted"], stats["skipped"], skip_ratio * 100,
            )

        for record in skipped_records:
            logger.debug(
                "skipped item title=%r url=%s source=%s skip_reason=%s http_status=%s "
                "rss_had_content=%s rss_content_length=%d",
                record["title"], record["url"], record["source"], record["skip_reason"],
                record["http_status"], record["rss_had_content"], record["rss_content_length"],
            )

        if skipped_records:
            self._write_extraction_debug_file(source_stats, skipped_records)

        return items

    def _write_extraction_debug_file(
        self, source_stats: Dict[str, Dict[str, int]], skipped_records: List[dict]
    ) -> Path:
        """Write a JSON debug export of full-content extraction results.

        Args:
            source_stats: Per-source total/extracted/skipped counts.
            skipped_records: Per-item details for every skipped item.

        Returns:
            Path to the written debug file.
        """
        debug_dir = Path("data/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc)
        by_source = {
            source_label: {
                **stats,
                "skip_ratio": round(stats["skipped"] / stats["total"], 4) if stats["total"] else 0.0,
            }
            for source_label, stats in sorted(source_stats.items())
        }

        payload = {
            "generated_at": timestamp.isoformat(),
            "total_items": sum(s["total"] for s in source_stats.values()),
            "total_extracted": sum(s["extracted"] for s in source_stats.values()),
            "total_skipped": sum(s["skipped"] for s in source_stats.values()),
            "by_source": by_source,
            "skipped_items": skipped_records,
        }

        debug_path = debug_dir / f"extraction_debug_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        debug_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.console.print(f"🐛 正文提取 debug 导出: {debug_path}\n")
        return debug_path

    async def _fetch_with_progress(self, name: str, scraper, since: datetime) -> List[ContentItem]:
        """Fetch from a scraper with progress indication.

        Args:
            name: Source name for display
            scraper: Scraper instance
            since: Fetch items after this time

        Returns:
            List[ContentItem]: Fetched items
        """
        self.console.print(f"🔍 Fetching from {name}...")
        items = await scraper.fetch(since)
        self.console.print(f"   Found {len(items)} items from {name}")

        # Show per-sub-source breakdown when there are multiple sub-sources
        sub_counts: Dict[str, int] = defaultdict(int)
        for item in items:
            sub_counts[sub_source_label(item)] += 1
        if len(sub_counts) > 1:
            for sub, count in sorted(sub_counts.items()):
                self.console.print(f"      • {sub}: {count}")

        return items

    @staticmethod
    def _build_source_attribution(items: List[ContentItem]) -> None:
        build_source_attribution(items)

    def merge_cross_source_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Stable stage entry point for integrations such as MCP."""
        return merge_cross_source_duplicates(items)

    async def merge_topic_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Stable stage entry point for integrations such as MCP."""
        return await merge_topic_duplicates(items, self.config.ai, self.console)

    def apply_balanced_digest(
        self,
        items: List[ContentItem],
        *,
        log: bool = True,
    ) -> BalancedDigestResult:
        """Stable stage entry point for integrations such as MCP."""
        return apply_balanced_digest(items, self.config.filtering, console=self.console, log=log)

    async def _expand_twitter_discussion(self, items: List[ContentItem]) -> None:
        """Second-stage: fetch reply text for important Twitter items and re-analyze.

        Only runs when sources.twitter.fetch_reply_text is True.
        Bounded by max_tweets_to_expand to control cost.
        """
        tw_cfg = self.config.sources.twitter
        if not tw_cfg or not tw_cfg.enabled or not tw_cfg.fetch_reply_text:
            return

        from .models import SourceType

        twitter_items = [
            item for item in items
            if item.source_type == SourceType.TWITTER
        ][:tw_cfg.max_tweets_to_expand]

        if not twitter_items:
            return

        self.console.print(
            f"💬 Fetching reply text for {len(twitter_items)} Twitter items..."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            if tw_cfg.mode == "playwright":
                self.console.print(
                    "   [yellow]Reply expansion not yet supported in Playwright mode.[/yellow]"
                )
                return
            scraper = TwitterScraper(tw_cfg, client)
            expanded = []
            for item in twitter_items:
                try:
                    reply_lines = await scraper.fetch_replies_for_item(item)
                    if TwitterScraper.append_discussion_content(item, reply_lines):
                        expanded.append(item)
                        self.console.print(
                            f"   💬 {len(reply_lines)} replies added to: {item.title[:60]}"
                        )
                except Exception as exc:
                    self.console.print(
                        f"   [yellow]⚠️  Reply fetch failed for {item.id}: {exc}[/yellow]"
                    )

        if not expanded:
            return

        self.console.print(
            f"   Re-analyzing {len(expanded)} Twitter items with reply context...\n"
        )
        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(ai_client)
        await analyzer.analyze_batch(expanded)

    async def _enrich_important_items(self, items: List[ContentItem]) -> None:
        """Enrich items with background knowledge (2nd AI pass).

        For each item that passed the score threshold, call AI to generate
        background knowledge based on the item's actual content.

        Args:
            items: Important items to enrich (modified in-place)
        """
        if not items:
            return

        self.console.print("📚 Enriching with background knowledge...")
        ai_client = create_ai_client(self.config.ai)
        enricher = ContentEnricher(ai_client)
        await enricher.enrich_batch(items)
        self.console.print(f"   Enriched {len(items)} items\n")

    async def _analyze_content(self, items: List[ContentItem]) -> List[ContentItem]:
        """Analyze content items with AI.

        Args:
            items: Items to analyze

        Returns:
            List[ContentItem]: Analyzed items
        """
        self.console.print("🤖 Analyzing content with AI...")

        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(ai_client)

        return await analyzer.analyze_batch(items)

    async def _classify_topics(self, items: List[ContentItem]) -> None:
        """Classify items with multi-dimensional topic tags (second AI stage).

        Called after scoring + semantic dedup, before enrichment.
        Results are stored in item.metadata["_topics_classification"]
        for later persistence to news_topics table.

        Falls back to a default "行业动态" content-type topic if the
        LLM returns no content-type topics.
        """
        if not items:
            return

        self.console.print("🏷️ Classifying topics...")

        # Load active topics from DB
        topics_result = self.db.get_topics(grouped=False)
        all_topics = topics_result.get("topics", [])

        if not all_topics:
            self.console.print("   [yellow]No topics in database, skipping classification[/yellow]")
            return

        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(ai_client)
        results = await analyzer.classify_topics_batch(items, all_topics)

        # Stamp results onto items via metadata
        content_type_slugs = {
            t["slug"]
            for t in all_topics
            if t["group_name"] == "内容形态"
        }

        for result in results:
            news_id = result["news_id"]
            topics = result.get("topics", [])

            # Fallback: ensure at least one content-type topic
            has_content_type = any(
                t.get("group_name") == "内容形态" for t in topics
            )
            if not has_content_type:
                topics.append(
                    {
                        "slug": "industry-news",
                        "name": "行业动态",
                        "group_name": "内容形态",
                        "confidence": 0.5,
                        "reason": "兜底分类：模型未返回任何内容形态主题",
                    }
                )

            # Store on the matching item
            for item in items:
                if item.id == news_id:
                    item.metadata["_topics_classification"] = topics
                    break

        classified = sum(
            1 for item in items
            if item.metadata.get("_topics_classification")
        )
        self.console.print(
            f"   Classified {classified}/{len(items)} items\n"
        )
    def _seed_topics(self) -> None:
        """Ensure the topics table is populated with seed data.

        Idempotent — running multiple times only upserts.
        Errors are caught so a missing DB doesn't crash the pipeline.
        """
        try:
            topics_data = build_seed_topics()
            count = self.db.seed_topics(topics_data)
            self.console.print(f"🏷️ Ensured {count} topics in database")
        except Exception as e:
            self.console.print(
                f"[yellow]⚠️  Could not seed topics: {e}[/yellow]"
            )

