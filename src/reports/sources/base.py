"""Abstract base for a single reports source (one institution's website)."""

from abc import ABC, abstractmethod
from typing import List, Optional

import httpx

from ..models import Report


class ReportSourceFetcher(ABC):
    """Fetches report listings and details from one institution's site.

    Each concrete source owns its own HTTP/API quirks entirely; `fetcher.py`
    only calls `fetch_native_ids()` then `fetch_detail()` per id and never
    touches a source's transport details directly.
    """

    source_name: str
    requires_browser: bool = False

    @abstractmethod
    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Return the source's own ids for reports currently available to fetch."""

    @abstractmethod
    async def fetch_detail(self, client: httpx.AsyncClient, native_id: str) -> Optional[Report]:
        """Fetch and convert a single report to the shared `Report` shape."""
