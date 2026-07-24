"""RSS feed scraper implementation."""

import calendar
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional
from email.utils import parsedate_to_datetime
import httpx
import feedparser

from .base import BaseScraper
from ..models import ContentItem, SourceType, RSSSourceConfig

logger = logging.getLogger(__name__)

# RSS content length threshold: when the feed provides >= this many characters,
# skip URL-based extraction — the RSS content is considered "full article" quality.
_RSS_HIGH_QUALITY_MIN_LENGTH = 1000


def _assess_rss_quality(content: str) -> str:
    """Assess whether RSS-provided content is high enough quality to skip URL extraction."""
    stripped = content.strip()
    if not stripped:
        return "none"
    if len(stripped) >= _RSS_HIGH_QUALITY_MIN_LENGTH:
        return "high"
    return "low"


class RSSScraper(BaseScraper):
    """Scraper for RSS/Atom feeds."""

    def __init__(self, sources: List[RSSSourceConfig], http_client: httpx.AsyncClient):
        """Initialize RSS scraper.

        Args:
            sources: List of RSS feed configurations
            http_client: Shared async HTTP client
        """
        super().__init__({"sources": sources}, http_client)

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch RSS feed items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        items = []
        sources = self.config["sources"]

        for source in sources:
            if not source.enabled:
                continue

            feed_items = await self._fetch_feed(source, since)
            items.extend(feed_items)

        return items

    async def _fetch_feed(
        self, source: RSSSourceConfig, since: datetime
    ) -> List[ContentItem]:
        """Fetch items from a single RSS feed.

        Args:
            source: RSS feed configuration
            since: Only fetch items after this time

        Returns:
            List[ContentItem]: Feed content items
        """
        items = []

        try:
            # Expand environment variables in URL (e.g. ${LWN_TOKEN})
            feed_url = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)).strip(),
                str(source.url),
            )

            # Fetch feed content
            response = await self.client.get(feed_url, follow_redirects=True)
            response.raise_for_status()

            # Parse feed
            feed = feedparser.parse(response.text)

            for entry in feed.entries:
                # Parse published date
                entry_link = entry.get("link", "")
                published_at = self._parse_date(entry, entry_link)
                if not published_at or published_at < since:
                    continue

                # Generate unique ID from feed URL and entry ID
                feed_id = str(source.url).split("//")[1].replace("/", "_")
                entry_id = entry.get("id", entry.get("link", ""))
                entry_hash = hashlib.sha256(str(entry_id).encode("utf-8")).hexdigest()[
                    :16
                ]

                # Extract content
                content = self._extract_content(entry)

                item = ContentItem(
                    id=self._generate_id("rss", feed_id, entry_hash),
                    source_type=SourceType.RSS,
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", str(source.url)),
                    content=content,
                    author=entry.get("author", source.name),
                    published_at=published_at,
                    rss_content_quality=_assess_rss_quality(content),
                    metadata={
                        "feed_name": source.name,
                        "category": source.category,
                        "extraction_mode": source.extraction_mode,
                        "tags": [tag.term for tag in entry.get("tags", [])],
                    },
                )
                items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching RSS feed %s: %s", source.name, e)
        except Exception as e:
            logger.warning("Error parsing RSS feed %s: %s", source.name, e)

        return items

    def _parse_date(self, entry: dict, fallback_url: str = "") -> Optional[datetime]:
        """Parse publication date from feed entry.

        Args:
            entry: Feed entry data
            fallback_url: Optional URL to extract date from as last resort
                          (handles feeds like Meituan Tech that omit per-item pubDate)

        Returns:
            datetime: Parsed publication date or None
        """
        import re as _re

        # Try different date fields
        for field in ["published", "updated", "created"]:
            if field in entry:
                try:
                    # Try parsing structured time first
                    if f"{field}_parsed" in entry and entry[f"{field}_parsed"]:
                        return datetime.fromtimestamp(
                            calendar.timegm(entry[f"{field}_parsed"]), tz=timezone.utc
                        )
                    # Fallback to string parsing
                    date_str = entry[field]
                    return parsedate_to_datetime(date_str)
                except Exception:
                    continue

        # Fallback: extract date from URL path patterns like /YYYY/MM/DD/
        if fallback_url:
            m = _re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})(/|$|[?#])", fallback_url)
            if m:
                try:
                    return datetime(
                        int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
                    )
                except Exception:
                    pass

        return None

    def _extract_content(self, entry: dict) -> str:
        """Extract text content from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            str: Extracted text content
        """
        # Prefer content:encoded (full article body) over the short
        # summary/description teaser some feeds ship alongside it.
        if "content" in entry and entry.content:
            # content is usually a list
            value = entry.content[0].get("value", "")
            if value:
                return value
        if "summary" in entry:
            return entry.summary
        if "description" in entry:
            return entry.description

        return ""
