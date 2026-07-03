"""Main orchestrator coordinating the entire workflow."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from urllib.parse import urlparse
import httpx
from rich.console import Console

from .models import Config, ContentItem
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


@dataclass
class BalancedDigestResult:
    """Items and selection statistics from balanced digest filtering."""

    items: List[ContentItem]
    enabled: bool = False
    group_counts: Dict[str, int] = field(default_factory=dict)
    group_limits: Dict[str, Optional[int]] = field(default_factory=dict)
    duplicate_categories: List[str] = field(default_factory=list)


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

            # 5. Filter by score threshold
            threshold = self.config.filtering.ai_score_threshold
            important_items = [
                item for item in relevant_items
                if item.ai_score and item.ai_score >= threshold
            ]
            important_items.sort(key=lambda x: x.ai_score or 0, reverse=True)

            self.console.print(
                f"⭐️ {len(important_items)} items scored ≥ {threshold}\n"
            )

            # 5.5 Semantic deduplication: drop items covering the same topic
            deduped_items = await self.merge_topic_duplicates(important_items)
            if len(deduped_items) < len(important_items):
                self.console.print(
                    f"🧹 Removed {len(important_items) - len(deduped_items)} topic duplicates "
                    f"→ {len(deduped_items)} unique items\n"
                )
            important_items = deduped_items

            # 5.6 Optional second-stage Twitter reply expansion + targeted re-analysis
            await self._expand_twitter_discussion(important_items)

            # 5.7 Topic classification: assign multi-dimensional topic tags
            await self._classify_topics(important_items)

            # 5.8 Apply per-category and global digest limits before enrichment
            balanced_result = self.apply_balanced_digest(important_items)
            important_items = balanced_result.items

            # Show per-sub-source selection breakdown
            selected_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                key = f"{item.source_type.value}/{self._sub_source_label(item)}"
                selected_counts[key] += 1
            for source_key, count in sorted(selected_counts.items()):
                self.console.print(f"      • {source_key}: {count}")
            self.console.print("")

            # 6. Search related stories + enrich with background knowledge (2nd AI pass)
            await self._enrich_important_items(important_items)

            # 6.5 Persist scored + enriched items to SQLite for API serving
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            saved = self.db.save_items(important_items, today, len(all_items))
            self.console.print(f"💾 Persisted {saved} items to SQLite\n")

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
            sub_counts[self._sub_source_label(item)] += 1
        if len(sub_counts) > 1:
            for sub, count in sorted(sub_counts.items()):
                self.console.print(f"      • {sub}: {count}")

        return items

    @staticmethod
    def _sub_source_label(item: ContentItem) -> str:
        """Return a human-readable sub-source label for an item."""
        meta = item.metadata
        if meta.get("subreddit"):
            return f"r/{meta['subreddit']}"
        if meta.get("feed_name"):
            return meta["feed_name"]
        if meta.get("channel"):
            return f"@{meta['channel']}"
        if meta.get("period") and meta.get("repo"):
            return f"ossinsight:{meta.get('primary_language', 'all')}"
        if meta.get("repo"):
            return meta["repo"]
        if meta.get("watchlist"):
            return meta["watchlist"]
        if meta.get("source_name"):
            return meta["source_name"]
        if meta.get("gn_query"):
            return f"google_news:{meta['gn_query']}"
        if meta.get("domain"):
            return meta["domain"]
        return item.author or "unknown"

    def merge_cross_source_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items that point to the same URL from different sources.

        This is a stable stage helper for integrations such as MCP.

        Keeps the item with the richest content and combines metadata.

        Args:
            items: Items to deduplicate

        Returns:
            List[ContentItem]: Deduplicated items
        """
        def normalize_url(url: str) -> str:
            parsed = urlparse(str(url))
            # Strip www prefix, trailing slashes, and fragments
            host = parsed.hostname or ""
            if host.startswith("www."):
                host = host[4:]
            path = parsed.path.rstrip("/")
            return f"{host}{path}"

        # Group by normalized URL
        url_groups: Dict[str, List[ContentItem]] = {}
        for item in items:
            key = normalize_url(str(item.url))
            url_groups.setdefault(key, []).append(item)

        merged = []
        for key, group in url_groups.items():
            if len(group) == 1:
                merged.append(group[0])
                continue

            # Pick the item with the richest content as primary
            primary = max(group, key=lambda x: len(x.content or ""))

            # Merge metadata and source info from other items
            all_sources = set()
            for item in group:
                all_sources.add(item.source_type.value)
                # Merge metadata (engagement, discussion, etc.)
                for mk, mv in item.metadata.items():
                    if mk not in primary.metadata or not primary.metadata[mk]:
                        primary.metadata[mk] = mv

                # Append content (e.g., comments from another source)
                if item is not primary and item.content:
                    if primary.content and item.content not in primary.content:
                        primary.content = (primary.content or "") + f"\n\n--- From {item.source_type.value} ---\n" + item.content

            primary.metadata["merged_sources"] = list(all_sources)
            merged.append(primary)

        return merged

    async def merge_topic_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items covering the same topic using AI semantic deduplication.

        This is a stable stage helper for integrations such as MCP.

        Sends all item titles, tags, and summaries to AI in a single call.
        Items must already be sorted by ai_score descending so that the first
        item in each duplicate group is always the highest-scored one.
        Content (comments) from duplicate items is merged into the primary.

        Falls back to returning items unchanged if the AI call fails.
        """
        if len(items) <= 1:
            return items

        from .ai.prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
        from .ai.utils import parse_json_response

        # Build the item list for the prompt
        lines = []
        for i, item in enumerate(items):
            tags = ", ".join(item.ai_tags) if item.ai_tags else "—"
            summary = item.ai_summary or "—"
            lines.append(f"[{i}] {item.title}\n    Tags: {tags}\n    Summary: {summary}")
        items_text = "\n\n".join(lines)

        try:
            ai_client = create_ai_client(self.config.ai)
            response = await ai_client.complete(
                system=TOPIC_DEDUP_SYSTEM,
                user=TOPIC_DEDUP_USER.format(items=items_text),
            )
            result = parse_json_response(response)
            if result is None:
                self.console.print("[yellow]  dedup: could not parse AI response, skipping[/yellow]")
                return items

            duplicate_groups = result.get("duplicates", [])
        except Exception as e:
            self.console.print(f"[yellow]  dedup: AI call failed ({e}), skipping[/yellow]")
            return items

        if not duplicate_groups:
            return items

        # Build a set of indices to drop (all non-primary duplicates)
        drop_indices: set[int] = set()
        for group in duplicate_groups:
            if not isinstance(group, list) or len(group) < 2:
                continue
            primary_idx = group[0]
            if primary_idx < 0 or primary_idx >= len(items):
                continue
            primary = items[primary_idx]
            for dup_idx in group[1:]:
                if not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx >= len(items):
                    continue
                if dup_idx == primary_idx:
                    continue
                dup = items[dup_idx]
                # Merge comments/content from the duplicate into the primary
                if dup.content:
                    if not primary.content or dup.content not in primary.content:
                        label = dup.source_type.value
                        primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
                self.console.print(
                    f"   [dim]dedup: keep [{primary_idx}] {primary.title}[/dim]\n"
                    f"   [dim]       drop [{dup_idx}] {dup.title}[/dim]"
                )
                drop_indices.add(dup_idx)

        return [item for i, item in enumerate(items) if i not in drop_indices]

    def apply_balanced_digest(
        self,
        items: List[ContentItem],
        *,
        log: bool = True,
    ) -> BalancedDigestResult:
        """Apply configured category quotas and the final item cap.

        Categories are read from ``item.metadata["category"]``. If a category
        appears in more than one configured group, the first group in config
        order wins.
        """
        filtering = self.config.filtering
        groups = filtering.category_groups
        max_items = filtering.max_items

        if not groups and max_items is None:
            return BalancedDigestResult(items=items)

        sorted_items = sorted(
            items,
            key=lambda item: item.ai_score or 0,
            reverse=True,
        )

        category_to_group: Dict[str, str] = {}
        duplicate_categories: List[str] = []
        for group_key, group in groups.items():
            for category in group.categories:
                if category in category_to_group:
                    if category_to_group[category] != group_key:
                        duplicate_categories.append(category)
                    continue
                category_to_group[category] = group_key

        if log:
            for category in sorted(set(duplicate_categories)):
                first_group = category_to_group[category]
                self.console.print(
                    f"[yellow]Warning: category '{category}' is configured in multiple "
                    f"groups; using '{first_group}'.[/yellow]"
                )

        selected: List[tuple[ContentItem, str]] = []
        group_counts: Dict[str, int] = defaultdict(int)
        default_group = filtering.default_group

        for item in sorted_items:
            category = item.metadata.get("category")
            group_key = (
                category_to_group.get(category, default_group)
                if isinstance(category, str)
                else default_group
            )

            if group_key in groups:
                limit = groups[group_key].limit
            else:
                limit = filtering.default_group_limit

            if limit is not None and group_counts[group_key] >= limit:
                continue

            selected.append((item, group_key))
            group_counts[group_key] += 1

        if max_items is not None:
            selected = selected[:max_items]

        final_counts: Dict[str, int] = defaultdict(int)
        for _, group_key in selected:
            final_counts[group_key] += 1

        group_limits: Dict[str, Optional[int]] = {
            group_key: group.limit for group_key, group in groups.items()
        }
        group_limits.setdefault(default_group, filtering.default_group_limit)

        if log:
            self.console.print(
                f"⚖️ Balanced digest selected {len(selected)}/{len(items)} items"
            )
            for group_key, group in groups.items():
                label = group.name or group_key
                self.console.print(
                    f"      • {label}: {final_counts.get(group_key, 0)}/{group.limit}"
                )
            if (
                final_counts.get(default_group, 0)
                or filtering.default_group_limit is not None
            ):
                limit_label = (
                    str(filtering.default_group_limit)
                    if filtering.default_group_limit is not None
                    else "unlimited"
                )
                self.console.print(
                    f"      • {default_group}: "
                    f"{final_counts.get(default_group, 0)}/{limit_label}"
                )
            self.console.print("")

        return BalancedDigestResult(
            items=[item for item, _ in selected],
            enabled=True,
            group_counts=dict(final_counts),
            group_limits=group_limits,
            duplicate_categories=sorted(set(duplicate_categories)),
        )

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
            topics_data = _build_seed_topics()
            count = self.db.seed_topics(topics_data)
            self.console.print(f"🏷️ Ensured {count} topics in database")
        except Exception as e:
            self.console.print(
                f"[yellow]⚠️  Could not seed topics: {e}[/yellow]"
            )

    async def _generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary.

        Args:
            items: Important items to include (already enriched with background/related)
            date: Date string
            total_fetched: Total items fetched
            language: Output language ("en" or "zh")

        Returns:
            str: Markdown summary
        """
        self.console.print("📝 Generating daily summary...")

        summarizer = DailySummarizer()

        return await summarizer.generate_summary(items, date, total_fetched, language=language)


# ---------------------------------------------------------------------------
# Topic seed data
# ---------------------------------------------------------------------------


def _build_seed_topics() -> list[dict]:
    """Build the complete list of seed topics.

    Returns a list of dicts suitable for HorizonDB.seed_topics().
    """
    return [
        # === 公司与模型 ===
        {
            "name": "OpenAI / ChatGPT",
            "slug": "openai-chatgpt",
            "group_name": "公司与模型",
            "description": "OpenAI 旗下产品与模型相关新闻，包括 ChatGPT、GPT 系列、o1/o3、Sora、DALL-E 等",
            "keywords": ["OpenAI", "ChatGPT", "GPT", "GPT-4", "GPT-5", "o1", "o3", "Sora", "DALL-E", "Sam Altman"],
            "aliases": ["openai", "chatgpt", "gpt"],
            "sort_order": 10,
            "is_active": 1,
        },
        {
            "name": "Anthropic / Claude",
            "slug": "anthropic-claude",
            "group_name": "公司与模型",
            "description": "Anthropic 旗下 Claude 系列模型相关新闻",
            "keywords": ["Anthropic", "Claude", "Claude 3", "Claude 4", "Claude 5", "Opus", "Sonnet", "Haiku", "Dario Amodei"],
            "aliases": ["anthropic", "claude"],
            "sort_order": 20,
            "is_active": 1,
        },
        {
            "name": "Google / Gemini",
            "slug": "google-gemini",
            "group_name": "公司与模型",
            "description": "Google DeepMind 旗下 Gemini 系列模型及 AI 产品相关新闻",
            "keywords": ["Google", "Gemini", "DeepMind", "Gemma", "Gemini 2", "Gemini 3", "Veo", "Imagen", "NotebookLM", "Project Mariner"],
            "aliases": ["google", "gemini", "deepmind", "gemma"],
            "sort_order": 30,
            "is_active": 1,
        },
        {
            "name": "DeepSeek",
            "slug": "deepseek",
            "group_name": "公司与模型",
            "description": "深度求索旗下 DeepSeek 系列模型相关新闻",
            "keywords": ["DeepSeek", "DeepSeek-V2", "DeepSeek-V3", "DeepSeek-R1", "DeepSeek-Coder", "幻方量化"],
            "aliases": ["deepseek", "深度求索"],
            "sort_order": 40,
            "is_active": 1,
        },
        {
            "name": "通义千问 Qwen",
            "slug": "qwen",
            "group_name": "公司与模型",
            "description": "阿里云通义千问 Qwen 系列模型相关新闻",
            "keywords": ["Qwen", "通义千问", "Qwen2", "Qwen3", "Qwen-VL", "Qwen-Audio", "阿里云", "阿里巴巴"],
            "aliases": ["qwen", "通义千问", "tongyi", "阿里"],
            "sort_order": 50,
            "is_active": 1,
        },
        {
            "name": "Kimi / 月之暗面",
            "slug": "kimi-moonshot",
            "group_name": "公司与模型",
            "description": "月之暗面 Kimi 系列模型与产品相关新闻",
            "keywords": ["Kimi", "月之暗面", "Moonshot AI", "杨植麟"],
            "aliases": ["kimi", "moonshot", "月之暗面"],
            "sort_order": 60,
            "is_active": 1,
        },
        {
            "name": "MiniMax",
            "slug": "minimax",
            "group_name": "公司与模型",
            "description": "MiniMax（稀宇科技）旗下模型与产品相关新闻",
            "keywords": ["MiniMax", "稀宇科技", "MiniMax-Text", "MiniMax-VL", "海螺AI", "Hailuo AI"],
            "aliases": ["minimax", "稀宇科技", "hailuo"],
            "sort_order": 70,
            "is_active": 1,
        },
        {
            "name": "智谱 GLM",
            "slug": "zhipu-glm",
            "group_name": "公司与模型",
            "description": "智谱 AI 旗下 GLM 系列模型相关新闻",
            "keywords": ["智谱", "GLM", "ChatGLM", "GLM-4", "CodeGeeX", "CogView", "CogVideo"],
            "aliases": ["zhipu", "glm", "chatglm", "智谱"],
            "sort_order": 80,
            "is_active": 1,
        },
        {
            "name": "xAI / Grok",
            "slug": "xai-grok",
            "group_name": "公司与模型",
            "description": "xAI 旗下 Grok 系列模型相关新闻",
            "keywords": ["xAI", "Grok", "Elon Musk", "Grok-1", "Grok-2", "Grok-3", "X.com"],
            "aliases": ["xai", "grok", "elon musk"],
            "sort_order": 90,
            "is_active": 1,
        },
        {
            "name": "Meta / Llama",
            "slug": "meta-llama",
            "group_name": "公司与模型",
            "description": "Meta 旗下 Llama 系列开源模型相关新闻",
            "keywords": ["Meta", "Llama", "Llama 3", "Llama 4", "LLaMA", "Code Llama", "Zuckerberg", "FAIR"],
            "aliases": ["meta", "llama", "facebook"],
            "sort_order": 100,
            "is_active": 1,
        },
        {
            "name": "Microsoft / Copilot",
            "slug": "microsoft-copilot",
            "group_name": "公司与模型",
            "description": "微软 AI 产品与战略相关新闻，包括 Copilot、Azure AI、Phi 系列模型等",
            "keywords": ["Microsoft", "Copilot", "Azure AI", "Phi", "Phi-3", "Phi-4", "微软", "Satya Nadella"],
            "aliases": ["microsoft", "copilot", "msft", "微软", "azure"],
            "sort_order": 110,
            "is_active": 1,
        },
        {
            "name": "NVIDIA 英伟达",
            "slug": "nvidia",
            "group_name": "公司与模型",
            "description": "NVIDIA 芯片、AI 算力、CUDA 生态相关新闻",
            "keywords": ["NVIDIA", "英伟达", "GPU", "H100", "H200", "B100", "B200", "CUDA", "Jensen Huang", "黄仁勋"],
            "aliases": ["nvidia", "nvda", "英伟达"],
            "sort_order": 120,
            "is_active": 1,
        },
        {
            "name": "Hugging Face",
            "slug": "huggingface",
            "group_name": "公司与模型",
            "description": "Hugging Face 平台、开源工具、模型库相关新闻",
            "keywords": ["Hugging Face", "HuggingFace", "transformers", "diffusers", "datasets", "Gradio", "Spaces"],
            "aliases": ["huggingface", "hf"],
            "sort_order": 130,
            "is_active": 1,
        },
        {
            "name": "Cursor",
            "slug": "cursor",
            "group_name": "公司与模型",
            "description": "Cursor AI 编辑器及 Anysphere 公司相关新闻",
            "keywords": ["Cursor", "Anysphere", "AI editor", "AI IDE", "AI coding assistant"],
            "aliases": ["cursor", "anysphere"],
            "sort_order": 140,
            "is_active": 1,
        },
        {
            "name": "OpenRouter",
            "slug": "openrouter",
            "group_name": "公司与模型",
            "description": "OpenRouter API 网关及模型路由平台相关新闻",
            "keywords": ["OpenRouter", "model routing", "API gateway"],
            "aliases": ["openrouter"],
            "sort_order": 150,
            "is_active": 1,
        },

        # === 技术方向 ===
        {
            "name": "Agent 智能体",
            "slug": "ai-agent",
            "group_name": "技术方向",
            "description": "AI Agent、自主智能体、多 Agent 协作、工具使用相关进展",
            "keywords": ["Agent", "智能体", "AI agent", "autonomous agent", "multi-agent", "agentic", "SWE-agent", "Devin", "AutoGPT", "CrewAI", "LangGraph", "function calling"],
            "aliases": ["agent", "智能体", "agentic"],
            "sort_order": 10,
            "is_active": 1,
        },
        {
            "name": "AI 编码",
            "slug": "ai-coding",
            "group_name": "技术方向",
            "description": "AI 辅助编程、代码生成、代码理解、IDE 集成相关进展",
            "keywords": ["code generation", "AI coding", "Copilot", "Cursor", "code completion", "code review", "Devin", "SWE-bench", "Claude Code", "Aider", "Codex", "Windsurf"],
            "aliases": ["coding", "code", "编程", "代码"],
            "sort_order": 20,
            "is_active": 1,
        },
        {
            "name": "推理能力",
            "slug": "reasoning",
            "group_name": "技术方向",
            "description": "LLM 推理能力、Chain-of-Thought、数学推理、逻辑推理相关进展",
            "keywords": ["reasoning", "Chain-of-Thought", "CoT", "o1", "o3", "DeepSeek-R1", "推理", "math", "mathematical reasoning", "logical reasoning", "test-time compute", "scaling inference"],
            "aliases": ["reasoning", "推理", "cot", "chain-of-thought"],
            "sort_order": 30,
            "is_active": 1,
        },
        {
            "name": "多模态",
            "slug": "multimodal",
            "group_name": "技术方向",
            "description": "多模态模型、视觉语言模型、跨模态理解与生成相关进展",
            "keywords": ["multimodal", "多模态", "vision-language", "VLM", "GPT-4V", "GPT-4o", "Gemini Vision", "Claude Vision", "Qwen-VL", "visual understanding", "document understanding"],
            "aliases": ["multimodal", "多模态", "vlm", "vision"],
            "sort_order": 40,
            "is_active": 1,
        },
        {
            "name": "图像生成",
            "slug": "image-generation",
            "group_name": "技术方向",
            "description": "AI 图像生成、文生图、图像编辑模型与工具相关进展",
            "keywords": ["image generation", "文生图", "Stable Diffusion", "DALL-E", "Midjourney", "Flux", "SDXL", "SD3", "Imagen", "ControlNet", "IP-Adapter", "ComfyUI"],
            "aliases": ["image", "图像生成", "stable diffusion", "dalle", "midjourney", "flux"],
            "sort_order": 50,
            "is_active": 1,
        },
        {
            "name": "AI 视频",
            "slug": "ai-video",
            "group_name": "技术方向",
            "description": "AI 视频生成、视频理解、视频编辑模型与工具相关进展",
            "keywords": ["video generation", "AI video", "Sora", "Runway", "Pika", "Kling", "可灵", "Veo", "Luma", "视频生成", "video understanding"],
            "aliases": ["video", "视频", "sora", "runway", "kling", "veo"],
            "sort_order": 60,
            "is_active": 1,
        },
        {
            "name": "语音与音频",
            "slug": "speech-audio",
            "group_name": "技术方向",
            "description": "语音识别、语音合成、音频生成、实时对话 AI 相关进展",
            "keywords": ["speech", "audio", "TTS", "text-to-speech", "语音", "whisper", "ElevenLabs", "GPT-4o voice", "real-time", "voice assistant"],
            "aliases": ["speech", "audio", "语音", "tts", "voice"],
            "sort_order": 70,
            "is_active": 1,
        },
        {
            "name": "具身智能",
            "slug": "embodied-ai",
            "group_name": "技术方向",
            "description": "具身智能、机器人、自动驾驶、物理世界 AI 相关进展",
            "keywords": ["embodied", "robot", "robotics", "具身智能", "机器人", "self-driving", "autonomous driving", "自动驾驶", "Figure", "Tesla Bot", "Optimus", "physical AI"],
            "aliases": ["embodied", "robot", "具身智能", "机器人"],
            "sort_order": 80,
            "is_active": 1,
        },
        {
            "name": "端侧 AI",
            "slug": "on-device-ai",
            "group_name": "技术方向",
            "description": "端侧推理、手机/PC AI、芯片、边缘计算相关进展",
            "keywords": ["on-device", "edge", "端侧", "Apple Intelligence", "Qualcomm", "MediaTek", "NPU", "llama.cpp", "ollama", "MLX", "Gemma", "Phi", "mobile", "local LLM"],
            "aliases": ["on-device", "edge", "端侧", "local", "mobile", "ollama"],
            "sort_order": 90,
            "is_active": 1,
        },
        {
            "name": "开源生态",
            "slug": "open-source-ecosystem",
            "group_name": "技术方向",
            "description": "开源 AI 模型、框架、工具、社区动态相关新闻",
            "keywords": ["open source", "开源", "open weights", "open model", "Apache", "MIT", "Llama", "Mistral", "Falcon", "OLMo", "Llama.cpp", "vLLM", "community"],
            "aliases": ["open source", "开源", "open-source", "oss"],
            "sort_order": 100,
            "is_active": 1,
        },
        {
            "name": "部署工程",
            "slug": "deployment-engineering",
            "group_name": "技术方向",
            "description": "模型部署、推理优化、服务框架、企业 AI 落地相关进展",
            "keywords": ["deployment", "部署", "serving", "inference optimization", "quantization", "量化", "vLLM", "TGI", "TensorRT", "GGUF", "AWQ", "speculative decoding", "KV cache", "enterprise", "企业部署"],
            "aliases": ["deployment", "部署", "serving", "inference", "推理优化"],
            "sort_order": 110,
            "is_active": 1,
        },
        {
            "name": "数据与训练",
            "slug": "data-training",
            "group_name": "技术方向",
            "description": "训练数据、合成数据、预训练、微调、RLHF、数据标注相关进展",
            "keywords": ["training", "训练", "finetuning", "微调", "RLHF", "DPO", "GRPO", "synthetic data", "合成数据", "pretraining", "curriculum learning", "data annotation", "数据标注", "SFT", "LoRA", "QLoRA"],
            "aliases": ["training", "训练", "finetuning", "微调", "rlhf", "dpo"],
            "sort_order": 120,
            "is_active": 1,
        },
        {
            "name": "安全对齐",
            "slug": "safety-alignment",
            "group_name": "技术方向",
            "description": "AI 安全、对齐、红队测试、越狱防御、价值观对齐相关进展",
            "keywords": ["safety", "安全", "alignment", "对齐", "red teaming", "jailbreak", "越狱", "RLHF", "Constitutional AI", "harmlessness", "responsible AI", "AI ethics"],
            "aliases": ["safety", "安全", "alignment", "对齐", "jailbreak", "red team"],
            "sort_order": 130,
            "is_active": 1,
        },
        {
            "name": "MCP 与工具调用",
            "slug": "mcp-tool-use",
            "group_name": "技术方向",
            "description": "Model Context Protocol、工具调用、插件系统、API 集成相关进展",
            "keywords": ["MCP", "Model Context Protocol", "tool use", "function calling", "plugin", "Anthropic MCP", "工具调用", "tool calling", "API integration"],
            "aliases": ["mcp", "tool use", "function calling", "工具调用"],
            "sort_order": 140,
            "is_active": 1,
        },

        # === 内容形态 ===
        {
            "name": "模型发布",
            "slug": "model-release",
            "group_name": "内容形态",
            "description": "新模型、模型新版本、模型 checkpoint 发布",
            "keywords": ["模型发布", "model release", "new model", "launch", "发布", "checkpoint", "weights", "open source release"],
            "aliases": ["release", "发布", "模型发布"],
            "sort_order": 10,
            "is_active": 1,
        },
        {
            "name": "产品更新",
            "slug": "product-update",
            "group_name": "内容形态",
            "description": "产品功能更新、新功能上线、产品迭代",
            "keywords": ["产品更新", "product update", "new feature", "功能更新", "rollout", "推出", "上线", "upgrade"],
            "aliases": ["product", "产品", "update", "更新"],
            "sort_order": 20,
            "is_active": 1,
        },
        {
            "name": "论文研究",
            "slug": "paper-research",
            "group_name": "内容形态",
            "description": "学术论文、技术报告、研究成果",
            "keywords": ["论文", "paper", "research", "研究", "arxiv", "preprint", "conference", "NeurIPS", "ICML", "ICLR", "CVPR", "ACL", "EMNLP"],
            "aliases": ["paper", "论文", "research", "研究", "arxiv"],
            "sort_order": 30,
            "is_active": 1,
        },
        {
            "name": "评测基准",
            "slug": "benchmark-evaluation",
            "group_name": "内容形态",
            "description": "模型评测、基准测试、排行榜、性能对比",
            "keywords": ["评测", "benchmark", "evaluation", "leaderboard", "LMSYS", "Chatbot Arena", "MMLU", "HumanEval", "SWE-bench", "AIME"],
            "aliases": ["benchmark", "评测", "evaluation", "evaluation"],
            "sort_order": 40,
            "is_active": 1,
        },
        {
            "name": "教程实践",
            "slug": "tutorial-practice",
            "group_name": "内容形态",
            "description": "教程、实践指南、技术分享、踩坑经验",
            "keywords": ["教程", "tutorial", "guide", "how-to", "实践", "hands-on", "workshop", "教程", "指南"],
            "aliases": ["tutorial", "教程", "guide", "实践"],
            "sort_order": 50,
            "is_active": 1,
        },
        {
            "name": "大佬观点",
            "slug": "expert-opinion",
            "group_name": "内容形态",
            "description": "行业领袖、知名研究者、企业高管的观点、预测、评论",
            "keywords": ["观点", "opinion", "预测", "commentary", "interview", "采访", "预测", "展望", "think piece"],
            "aliases": ["opinion", "观点", "commentary", "评论"],
            "sort_order": 60,
            "is_active": 1,
        },
        {
            "name": "现象与趋势",
            "slug": "phenomenon-trend",
            "group_name": "内容形态",
            "description": "行业现象、趋势分析、数据报告、市场研究",
            "keywords": ["趋势", "trend", "现象", "报告", "report", "统计", "数据", "分析", "预测", "增长", "survey"],
            "aliases": ["trend", "趋势", "现象", "报告"],
            "sort_order": 70,
            "is_active": 1,
        },
        {
            "name": "行业动态",
            "slug": "industry-news",
            "group_name": "内容形态",
            "description": "AI 行业商业动态，包括投融资、合作、竞争、人事变动、公司战略",
            "keywords": ["行业动态", "industry", "投融资", "acquisition", "收购", "融资", "funding", "IPO", "合作", "partnership", "竞争", "裁员", "layoff", "战略"],
            "aliases": ["industry", "行业", "投融资", "funding", "收购", "合作"],
            "sort_order": 80,
            "is_active": 1,
        },
        {
            "name": "政策监管",
            "slug": "policy-regulation",
            "group_name": "内容形态",
            "description": "AI 政策、法律法规、监管框架、合规要求",
            "keywords": ["政策", "policy", "监管", "regulation", "法规", "法律", "欧盟", "EU AI Act", "白宫", "行政令", "国会", "数据隐私", "GDPR", "版权", "copyright"],
            "aliases": ["policy", "政策", "regulation", "监管", "法律"],
            "sort_order": 90,
            "is_active": 1,
        },
    ]
