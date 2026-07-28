"""WeChat MP scraper via local we-mp-rss (https://github.com/rachelos/we-mp-rss).

Fetches WeChat Official Account articles from a local we-mp-rss Docker instance
running at ``localhost:8001``.  The ``/feed/{feed_id}.json`` endpoint returns
structured JSON with full article HTML body and requires no authentication.

When ``auth_username`` + ``auth_password_env`` are set in config, the scraper
also auto-discovers all subscribed accounts from we-mp-rss — any account added
in the we-mp-rss admin panel is fetched automatically.
"""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from .base import BaseScraper
from ..models import ContentItem, SourceType, WxMpConfig, WxMpSourceConfig

logger = logging.getLogger(__name__)


class WxMpScraper(BaseScraper):
    """Scraper for WeChat MP articles via a local we-mp-rss instance.

    Feed IDs are auto-resolved from account names.  When auth credentials are
    configured, the scraper also auto-discovers all subscribed accounts from
    we-mp-rss and adds them to the fetch list — no config changes needed.
    """

    def __init__(self, config: WxMpConfig, http_client: httpx.AsyncClient):
        """Initialise with a WxMpConfig object (not a raw dict)."""
        super().__init__({"wxmp": config}, http_client)
        self._cfg = config
        self._base_url = config.base_url.rstrip("/")
        self._resolved_feeds: Optional[List[WxMpSourceConfig]] = None
        self._auth_token: Optional[str] = None

    async def _login(self) -> Optional[str]:
        """Authenticate with we-mp-rss and return a JWT token."""
        if not self._cfg.auth_enabled:
            return None
        username = self._cfg.auth_username
        password_env = self._cfg.auth_password_env
        if not username or not password_env:
            return None
        password = os.environ.get(password_env, "")
        if not password:
            logger.warning(
                "we-mp-rss auto-discovery: %r is empty or not set",
                password_env,
            )
            return None

        # Try httpx first, fall back to socket for Docker Desktop proxy.
        body = await self._fetch_json(
            "login",
            f"{self._base_url}/api/v1/wx/auth/login",
            method="POST",
            data={"username": username, "password": password},
        )
        if body:
            token = body.get("data", {}).get("access_token")
            if token:
                logger.info("Logged into we-mp-rss for auto-discovery")
                return token
        return None

    async def _ensure_resolved(self) -> List[WxMpSourceConfig]:
        """Resolve feed IDs, discover new accounts, return the feed list."""
        if self._resolved_feeds is not None:
            return self._resolved_feeds

        # 1. Resolve feed_ids for configured feeds that don't have one yet.
        feeds_needing_resolution = [
            f for f in self._cfg.feeds if f.enabled and not f.feed_id
        ]
        if feeds_needing_resolution:
            await self._resolve_feed_ids(feeds_needing_resolution)

        # 2. Start with configured feeds that have feed_ids.
        resolved: Dict[str, WxMpSourceConfig] = {}
        for f in self._cfg.feeds:
            if f.enabled and f.feed_id:
                resolved[f.name] = f

        # 3. Auto-discover any accounts from we-mp-rss not already in the list.
        discovered = await self._discover_new_feeds(resolved)
        for name, feed in discovered.items():
            resolved[name] = feed
            logger.info("Auto-discovered new WeChat account: %s (%s)", name, feed.feed_id)

        self._resolved_feeds = list(resolved.values())
        return self._resolved_feeds

    async def _resolve_feed_ids(self, feeds: List[WxMpSourceConfig]) -> None:
        """Query we-mp-rss API to find feed_id (mp_id) by account name."""
        try:
            name_to_id = await self._fetch_all_mp_names()
            for feed in feeds:
                resolved = name_to_id.get(feed.name)
                if resolved:
                    feed.feed_id = resolved
                    logger.info("Resolved feed_id for %s: %s", feed.name, resolved)
                else:
                    logger.warning(
                        "Could not resolve feed_id for WeChat account %r — "
                        "is it subscribed in we-mp-rss?  Skipping.",
                        feed.name,
                    )
        except Exception as exc:
            logger.warning(
                "Failed to resolve feed IDs from we-mp-rss API: %s. "
                "Feeds without feed_id will be skipped.",
                exc,
            )

    async def _discover_new_feeds(
        self, existing: Dict[str, WxMpSourceConfig]
    ) -> Dict[str, WxMpSourceConfig]:
        """Auto-discover accounts from we-mp-rss that aren't in *existing*."""
        if not self._cfg.auth_enabled:
            return {}

        if self._auth_token is None:
            self._auth_token = await self._login()
        if not self._auth_token:
            return {}

        try:
            name_to_id = await self._fetch_all_mp_names(token=self._auth_token)
            discovered: Dict[str, WxMpSourceConfig] = {}
            for name, feed_id in name_to_id.items():
                if name not in existing:
                    discovered[name] = WxMpSourceConfig(
                        name=name,
                        feed_id=feed_id,
                        category="wechat-account",
                    )
            return discovered
        except Exception as exc:
            logger.warning("Auto-discovery failed: %s", exc)
            return {}

    async def _fetch_all_mp_names(self, token: Optional[str] = None) -> Dict[str, str]:
        """Fetch all subscribed MP names → feed_id from we-mp-rss."""
        mps_url = f"{self._base_url}/api/v1/wx/mps"
        params = {"limit": 100}
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        body = await self._fetch_json("mps", mps_url, params=params, headers=headers)
        if not body:
            return {}

        mps_list = body.get("data", {}).get("list", [])
        if not mps_list and isinstance(body, list):
            mps_list = body
        elif not mps_list and isinstance(body, dict):
            mps_list = body.get("list", body.get("data", []))
        return {mp["mp_name"]: mp["id"] for mp in mps_list
                if mp.get("id") and mp.get("mp_name")}

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch items from all configured WeChat MP feeds."""
        feeds = await self._ensure_resolved()
        items: List[ContentItem] = []
        for feed in feeds:
            if not feed.feed_id:
                continue
            feed_items = await self._fetch_feed(feed, since)
            items.extend(feed_items)
        return items

    async def _fetch_json(
        self,
        feed_name: str,
        url: str,
        params: Optional[Dict[str, object]] = None,
        method: str = "GET",
        data: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[dict]:
        """Fetch JSON from we-mp-rss, falling back to raw socket if Docker
        Desktop proxy interferes (known issue: Docker Desktop on macOS returns
        503 for httpx/httpcore connections to localhost port-forwarding)."""
        # Primary path: httpx shared client.
        try:
            req_headers = headers or {}
            if method == "POST":
                response = await self.client.post(url, data=data, headers=req_headers, timeout=10.0)
            else:
                response = await self.client.get(url, params=params, headers=req_headers, follow_redirects=True)
            if response.status_code == 503:
                logger.info(
                    "httpx got 503 for %s — falling back to raw socket",
                    feed_name,
                )
                return await self._fetch_via_socket(url, method=method, data=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Error fetching %s via httpx: %s — trying raw socket fallback",
                feed_name,
                exc,
            )
            return await self._fetch_via_socket(url, method=method, data=data, headers=headers)
        except Exception as exc:
            logger.warning("Error parsing response from %s: %s", feed_name, exc)
            return None

    @staticmethod
    async def _fetch_via_socket(
        url: str,
        method: str = "GET",
        data: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[dict]:
        """Fallback: fetch JSON via asyncio-native socket to bypass proxy."""
        try:
            from urllib.parse import urlencode, urlparse

            parsed = urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8001
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query

            extra_headers = ""
            if headers:
                for k, v in headers.items():
                    extra_headers += f"{k}: {v}\r\n"

            if method == "POST":
                body_bytes = urlencode(data or {}).encode()
                raw_request = (
                    f"POST {path} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    f"User-Agent: Horizon/1.0\r\n"
                    f"Accept: application/json\r\n"
                    f"{extra_headers}"
                    f"Content-Type: application/x-www-form-urlencoded\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode() + body_bytes
            else:
                raw_request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    f"User-Agent: Horizon/1.0\r\n"
                    f"Accept: application/json\r\n"
                    f"{extra_headers}"
                    f"Connection: close\r\n\r\n"
                ).encode()

            import socket as _socket
            loop = asyncio.get_running_loop()
            reader, writer = await asyncio.open_connection(host, port, family=_socket.AF_INET)
            try:
                writer.write(raw_request)
                await writer.drain()
                resp_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
                content_length = 0
                for line in resp_data.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        content_length = int(line.split(b":")[1].strip())
                        break
                if content_length > 0:
                    body_bytes = await asyncio.wait_for(reader.readexactly(content_length), timeout=30.0)
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

    async def _fetch_feed(
        self, feed: WxMpSourceConfig, since: datetime
    ) -> List[ContentItem]:
        """Fetch items from a single WeChat MP feed."""
        items: List[ContentItem] = []
        feed_url = f"{self._base_url}/feed/{feed.feed_id}.json"
        params: Dict[str, object] = {"limit": self._cfg.fetch_limit}

        body = await self._fetch_json(feed.name, feed_url, params)
        if body is None:
            return items
        raw_items: List[dict] = body.get("items", [])

        cutoff_ts = since.timestamp()

        for raw in raw_items:
            # Parse publish time.
            published_at = self._parse_published(raw)
            if published_at is None or published_at.timestamp() < cutoff_ts:
                continue

            # Generate a stable, unique ID.
            article_id: str = raw.get("id", "")
            native_id = article_id or raw.get("link", "")

            content_html = raw.get("content") or ""
            description = raw.get("description") or ""

            item = ContentItem(
                id=self._generate_id("wechat", str(feed.feed_id), native_id),
                source_type=SourceType.WECHAT,
                title=raw.get("title", "Untitled"),
                url=raw.get("link", feed_url),
                content=content_html,
                rss_summary=description,
                rss_content_quality="high" if content_html else "low",
                author=raw.get("channel_name") or feed.name,
                published_at=published_at,
                metadata={
                    "feed_name": raw.get("channel_name") or feed.name,
                    "feed_id": feed.feed_id,
                    "category": feed.category,
                    "pic_url": raw.get("image", ""),
                },
            )
            items.append(item)

        return items

    @staticmethod
    def _parse_published(raw: dict) -> Optional[datetime]:
        """Parse the ``updated`` field from the feed JSON response.

        The we-mp-rss JSON feed may return:
        - ISO-8601 string (e.g. ``"2026-07-28T10:00:00+08:00"``)
        - Unix timestamp (int)
        - Already a number
        """
        updated = raw.get("updated")
        if updated is None:
            return None

        # Already a datetime
        if isinstance(updated, datetime):
            return updated

        # Unix timestamp (int or float)
        if isinstance(updated, (int, float)):
            return datetime.fromtimestamp(updated, tz=timezone.utc)

        # ISO-8601 string
        if isinstance(updated, str):
            try:
                return datetime.fromisoformat(updated)
            except ValueError:
                pass

            try:
                ts = float(updated)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError):
                pass

        logger.debug("Cannot parse publish time: %r", updated)
        return None
