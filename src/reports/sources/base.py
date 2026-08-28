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
    # 静态列表源置 True：fetch_native_ids 每轮都重列同一批报告(如"整年档案")，
    # 且详情内容基本不变。为 True 时 fetch_all_reports 会查库内已有 native_id、
    # 跳过 fetch_detail,避免无谓的重抓 + 重过 AI 过滤 + updated_row_at 刷屏。
    # 列表本身有时间窗(如 wxmp max_age、fxbaogao max_age_days)或详情会变的源保持 False。
    reuse_existing: bool = False

    @abstractmethod
    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Return the source's own ids for reports currently available to fetch."""

    @abstractmethod
    async def fetch_detail(self, client: httpx.AsyncClient, native_id: str) -> Optional[Report]:
        """Fetch and convert a single report to the shared `Report` shape."""
