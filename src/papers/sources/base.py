"""Abstract base for a single papers source."""

from abc import ABC, abstractmethod
from typing import List

import httpx

from ..models import Paper


class PaperSourceFetcher(ABC):
    """Fetches papers from one source in a single call.

    Unlike `src.reports.sources.base.ReportSourceFetcher` (list-then-detail,
    since report sites require a separate detail fetch per item), each
    papers source returns its full batch of `Paper`s from one `fetch()`
    call — both OpenAlex and Hugging Face's daily-papers API already return
    complete records.
    """

    source_name: str

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> List[Paper]:
        """Fetch and convert this source's current batch of papers."""
