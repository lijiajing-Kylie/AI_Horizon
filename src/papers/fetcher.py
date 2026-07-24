"""Cross-source orchestration for the papers library.

Calls each source enabled in `PapersConfig` and returns the unified `Paper`
list, deduped by id. Independent of `src.orchestrator`/`BaseScraper` —
papers never enter the news pipeline's analyzer/enricher.
"""

import logging
from typing import Dict, List, Optional

import httpx

from ..models import PapersConfig
from .models import Paper
from .sources.base import PaperSourceFetcher
from .sources.huggingface import HuggingFaceFetcher
from .sources.openalex import OpenAlexFetcher

logger = logging.getLogger(__name__)


async def fetch_all_papers(
    config: PapersConfig,
    client: httpx.AsyncClient,
    only_source: Optional[str] = None,
    month: Optional[str] = None,
    week: Optional[str] = None,
    top_n: Optional[int] = None,
) -> List[Paper]:
    """Fetch papers from every enabled source, optionally restricted to one.

    `only_source` backs the CLI's `--source` flag so a single source can be
    run on its own schedule (e.g. Hugging Face monthly) without re-running
    the others on the same invocation.

    `month`, `week`, and `top_n` are forwarded to the Hugging Face fetcher
    for targeted backfills.
    """
    fetchers: List[PaperSourceFetcher] = []
    if config.openalex.enabled and only_source in (None, "openalex"):
        fetchers.append(OpenAlexFetcher(config.openalex))
    if config.huggingface.enabled and only_source in (None, "huggingface"):
        fetchers.append(HuggingFaceFetcher(config.huggingface))

    papers: Dict[str, Paper] = {}
    for fetcher in fetchers:
        for paper in await fetcher.fetch(client):
            papers[paper.id] = paper

    return sorted(papers.values(), key=lambda p: p.published_at, reverse=True)
