"""WeChat MP reports source for the research-reports pipeline.

Fetches WeChat MP articles as research reports via a local we-mp-rss instance.
Registered in ``_SOURCE_REGISTRY`` when ``wxmp`` is listed in config's
``reports.sources``.

The ``/feed/{feed_id}.json`` endpoint already includes all fields needed for
a ``Report`` (title, content, published_at, channel_name), so article data is
cached during ``fetch_native_ids`` and returned directly from ``fetch_detail``
— no extra API calls needed.
"""

from __future__ import annotations

import json as json_mod
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)


class WxMpReportConfig:
    """Per-source config for the wxmp report fetcher."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        account_names: Optional[List[str]] = None,
        max_age_days: int = 7,
        fetch_limit: int = 100,
        known_feeds: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url
        self.account_names = account_names or []
        self.max_age_days = max_age_days
        self.fetch_limit = fetch_limit
        # Fallback mapping: account name → feed_id (e.g. from config.sources.wxmp.feeds).
        self.known_feeds = known_feeds or {}


class WxMpReportFetcher(ReportSourceFetcher):
    """Fetcher for WeChat MP articles treated as research reports.

    Article data is cached from the feed listing — ``fetch_detail`` returns
    Reports from cache rather than making extra API calls.
    """

    source_name = "wxmp"

    def __init__(self, config: Optional[WxMpReportConfig] = None) -> None:
        self.cfg = config or WxMpReportConfig()
        self._base_url = self.cfg.base_url.rstrip("/")
        # Cache: account name → feed_id
        self._name_to_id: Optional[Dict[str, str]] = None
        # Cache: native_id → article dict (populated during fetch_native_ids)
        self._article_cache: Dict[str, dict] = {}

    async def _resolve_feed_ids(self, client: httpx.AsyncClient) -> Dict[str, str]:
        """Query we-mp-rss feed index to map account names to feed IDs.

        Uses the ``/feed/all.json`` endpoint (no auth required) to build the
        name → feed_id mapping from embedded feed metadata.
        """
        if self._name_to_id is not None:
            return self._name_to_id

        self._name_to_id = {}

        body: Optional[dict] = None
        url_full = f"{self._base_url}/feed/all.json?limit=100"

        # Try httpx first.
        try:
            resp = await client.get(
                f"{self._base_url}/feed/all.json",
                params={"limit": 100},
                timeout=30.0,
            )
            if resp.status_code == 503:
                logger.info("httpx got 503 for feed/all.json — falling back to raw socket")
                body = await self._fetch_json_via_socket(url_full)
            else:
                resp.raise_for_status()
                body = resp.json()
        except httpx.ConnectError:
            logger.warning(
                "we-mp-rss not reachable at %s — skipping wxmp source",
                self._base_url,
            )
        except httpx.TimeoutException:
            logger.warning(
                "we-mp-rss at %s timed out — skipping wxmp source",
                self._base_url,
            )
        except Exception as exc:
            logger.info("httpx failed for feed/all.json (%s) — trying raw socket", exc)
            body = await self._fetch_json_via_socket(url_full)

        if body is None:
            return self._name_to_id

        for item in body.get("items", []):
            feed = item.get("feed") or {}
            mp_name = feed.get("name", "") or item.get("channel_name", "")
            mp_id = feed.get("id", "")
            if mp_name and mp_id and mp_name not in self._name_to_id:
                self._name_to_id[mp_name] = mp_id

        # Inject special feeds that are not in /feed/all.json.
        self._name_to_id["__featured__"] = "MP_WXS_FEATURED_ARTICLES"

        # Inject known feeds from config (fallback for accounts with no recent articles).
        for acct_name, acct_id in self.cfg.known_feeds.items():
            if acct_name not in self._name_to_id:
                self._name_to_id[acct_name] = acct_id

        return self._name_to_id

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Fetch article IDs from configured accounts within the time window,
        caching full article data for ``fetch_detail``."""
        name_to_id = await self._resolve_feed_ids(client)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.max_age_days)
        cutoff_ts = cutoff.timestamp()
        all_ids: List[str] = []
        self._article_cache = {}

        for name in self.cfg.account_names:
            feed_id = name_to_id.get(name)
            if not feed_id:
                logger.warning("Unknown WeChat account %r — skipping", name)
                continue

            url = f"{self._base_url}/feed/{feed_id}.json"
            items: List[dict] = []
            try:
                resp = await client.get(
                    url, params={"limit": self.cfg.fetch_limit}, timeout=8.0,
                )
                if resp.status_code == 503:
                    logger.info("httpx got 503 for feed %s — falling back to raw socket", name)
                    body = await self._fetch_json_via_socket(
                        f"{url}?limit={self.cfg.fetch_limit}"
                    )
                    items = body.get("items", []) if body else []
                else:
                    resp.raise_for_status()
                    items = resp.json().get("items", [])
            except httpx.ConnectError:
                logger.warning(
                    "we-mp-rss not reachable at %s — skipping account %r",
                    self._base_url, name,
                )
                continue
            except httpx.TimeoutException:
                logger.warning(
                    "we-mp-rss feed %r timed out — skipping", name,
                )
                continue
            except Exception as exc:
                logger.info("httpx failed for feed %s (%s) — trying raw socket", name, exc)
                body = await self._fetch_json_via_socket(
                    f"{url}?limit={self.cfg.fetch_limit}"
                )
                items = body.get("items", []) if body else []

            for item in items:
                ts = self._parse_ts(item.get("updated"))
                if ts is None or ts < cutoff_ts:
                    continue

                article_id = str(item.get("id", ""))
                if not article_id:
                    continue

                # Cache the full article data for fetch_detail.
                self._article_cache[article_id] = {
                    "id": article_id,
                    "title": item.get("title", "Untitled"),
                    "description": item.get("description") or "",
                    "content": item.get("content") or "",
                    "link": item.get("link", ""),
                    "channel_name": item.get("channel_name") or name,
                    "updated": item.get("updated"),
                    "image": item.get("image", ""),
                }
                all_ids.append(article_id)

        return all_ids

    async def fetch_detail(
        self, client: httpx.AsyncClient, native_id: str
    ) -> Optional[Report]:
        """Return a Report from the article data cached in ``fetch_native_ids``."""
        article = self._article_cache.get(native_id)
        if article is None:
            logger.debug("No cached data for article %s — skip", native_id)
            return None

        published_at = self._parse_dt(article["updated"])
        if published_at is None:
            published_at = datetime.now(timezone.utc)

        content_text = self._extract_text(article["content"])

        return Report(
            id=f"wxmp:{native_id}",
            source="wxmp",
            native_id=native_id,
            title=article["title"],
            institution=article["channel_name"],
            url=article["link"],
            summary=article["description"],
            content_text=content_text or article["description"],
            categories=[],
            published_at=published_at,
            updated_at=published_at,
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    async def _fetch_json_via_socket(url: str) -> Optional[dict]:
        """Fallback: fetch JSON via asyncio-native socket to bypass Docker
        Desktop proxy (known issue: Docker Desktop on macOS returns 503 for
        httpx/httpcore connections to localhost port-forwarding)."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8001
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query

            import socket as _socket
            import asyncio
            loop = asyncio.get_running_loop()
            reader, writer = await asyncio.open_connection(host, port, family=_socket.AF_INET)
            try:
                raw_request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    f"User-Agent: Horizon/1.0\r\n"
                    f"Accept: application/json\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode()
                writer.write(raw_request)
                await writer.drain()
                resp_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
                content_length = 0
                for line in resp_data.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        content_length = int(line.split(b":")[1].strip())
                        break
                if content_length > 0:
                    body_bytes = await asyncio.wait_for(
                        reader.readexactly(content_length), timeout=60.0,
                    )
                else:
                    body_bytes = await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()

            raw_headers = resp_data.decode("utf-8", errors="replace")
            status_line = raw_headers.split("\r\n")[0]
            if "200" not in status_line:
                logger.warning("Socket fallback got %s for %s", status_line, url)
                return None
            return json_mod.loads(body_bytes)
        except asyncio.TimeoutError:
            logger.warning("Socket fallback timeout for %s", url)
            return None
        except Exception as exc:
            logger.warning("Socket fallback failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _parse_ts(updated: object) -> Optional[float]:
        """Parse ``updated`` field to a Unix timestamp."""
        if updated is None:
            return None
        if isinstance(updated, (int, float)):
            return float(updated)
        if isinstance(updated, datetime):
            return updated.timestamp()
        if isinstance(updated, str):
            try:
                return datetime.fromisoformat(updated).timestamp()
            except (ValueError, TypeError):
                pass
            try:
                return float(updated)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _parse_dt(updated: object) -> Optional[datetime]:
        """Parse ``updated`` field to a datetime."""
        if updated is None:
            return None
        if isinstance(updated, datetime):
            return updated
        if isinstance(updated, (int, float)):
            return datetime.fromtimestamp(updated, tz=timezone.utc)
        if isinstance(updated, str):
            try:
                return datetime.fromisoformat(updated)
            except (ValueError, TypeError):
                pass
            try:
                return datetime.fromtimestamp(float(updated), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        return None

    @staticmethod
    def _extract_text(html: str) -> str:
        """Strip HTML tags to get clean plain text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
