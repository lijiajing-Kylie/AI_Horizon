"""阿里研究院 (aliresearch.com) reports source.

The site is a React SPA with no server-rendered content, but its backend exposes
plain unauthenticated JSON endpoints on the same origin (reverse-engineered from
the site's webpack bundle):

- ``POST /ch/listArticle`` with body ``{"type": "报告", "pageSize": N}`` — lists
  report articles, newest first. The response includes a ``total`` count (517 at
  the time this was written) confirming the corpus is much larger than what any
  single call returns.
- ``POST /ch/getArticle`` with body ``{"articleCode": "..."}`` — full detail for
  one report: title, full HTML body (``content``), direct PDF links
  (``docUrlList``), author/org, category tags, timestamps, view/download counts.

Known limitation: no working pagination cursor has been found for ``listArticle``
— ``pageNum``/``page``/``current``/``offset`` all silently no-op and it always
returns the newest ``pageSize`` items. ``pageSize`` itself is respected up to
~100 (larger values cause the upstream to truncate its response mid-JSON). So a
single fetch only ever pulls the ~100 most recent reports, not the full backlog;
older reports would need a different slicing strategy (e.g. by `special` topic)
to reach, which hasn't been implemented here since backfill wasn't the priority.
"""

import logging
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)

BASE_URL = "http://www.aliresearch.com"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
# Largest pageSize observed to return a complete, parseable JSON response.
_MAX_SAFE_PAGE_SIZE = 100


class AliResearchConfig(BaseModel):
    """Source-local config — not part of the generic ReportsConfig."""

    max_results: int = _MAX_SAFE_PAGE_SIZE
    report_type_label: str = "报告"  # the `type` value aliresearch tags reports with


class AliResearchFetcher(ReportSourceFetcher):
    """Fetches recent reports from aliresearch.com."""

    source_name = "aliresearch"

    def __init__(self, config: Optional[AliResearchConfig] = None):
        self.cfg = config or AliResearchConfig()

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        page_size = min(self.cfg.max_results, _MAX_SAFE_PAGE_SIZE)
        try:
            response = await client.post(
                f"{BASE_URL}/ch/listArticle",
                json={"pageSize": page_size, "type": self.cfg.report_type_label},
                timeout=30.0,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Error listing aliresearch reports: %s", e)
            return []

        if not body.get("success"):
            logger.warning("aliresearch listArticle returned failure: %s", body.get("msg"))
            return []

        return [str(item["articleCode"]) for item in body.get("data") or [] if item.get("articleCode")]

    async def fetch_detail(self, client: httpx.AsyncClient, native_id: str) -> Optional[Report]:
        try:
            response = await client.post(
                f"{BASE_URL}/ch/getArticle",
                json={"articleCode": native_id},
                timeout=30.0,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Error fetching aliresearch report %s: %s", native_id, e)
            return None

        if not body.get("success") or not body.get("data"):
            logger.warning("aliresearch getArticle(%s) returned failure: %s", native_id, body.get("msg"))
            return None

        data = body["data"]
        title = (data.get("title") or "").strip()
        if not title:
            return None

        published_at = self._parse_dt(data.get("gmtCreated")) or datetime.now(_SHANGHAI_TZ)
        updated_at = self._parse_dt(data.get("gmtModified")) or published_at

        categories = [c for c in (data.get("type", "") + "," + data.get("special", "")).split(",") if c]

        pdf_urls = [
            {"name": doc.get("name", ""), "url": doc.get("url", "")}
            for doc in (data.get("docUrlList") or [])
            if doc.get("url")
        ]

        return Report(
            id=f"{self.source_name}:{native_id}",
            source=self.source_name,
            native_id=native_id,
            title=title,
            institution=data.get("organName") or data.get("author") or "阿里研究院",
            author=data.get("author") or None,
            url=f"{BASE_URL}/ch/presentation/presentiondetails?articleCode={native_id}",
            pdf_urls=pdf_urls,
            summary=(data.get("description") or None),
            content_text=self._clean_html(data.get("content") or ""),
            categories=categories,
            published_at=published_at,
            updated_at=updated_at,
            view_count=data.get("viewCount"),
            download_count=data.get("downloadCount"),
            fetched_at=datetime.now(_SHANGHAI_TZ),
        )

    @staticmethod
    def _clean_html(html: str) -> str:
        if not html:
            return ""
        text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=_SHANGHAI_TZ)
        except ValueError:
            return None
