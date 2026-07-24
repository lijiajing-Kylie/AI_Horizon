"""Cross-source orchestration for the reports library.

Iterates the sources named in `ReportsConfig.sources`, calls each source's own
fetcher for its native ids + details, and returns the unified `Report` list.
Independent of `src.orchestrator`/`BaseScraper` — reports never enter the news
pipeline's analyzer/enricher.

When ``ReportsConfig.ai_filter_enabled`` is True, each fetched report is
passed through ``ReportFilter.is_tech_relevant()`` before inclusion; non-tech
reports (marketing, product catalogues, etc.) are silently skipped.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

import httpx

from ..models import ReportsConfig
from .filter import ReportFilter
from .models import Report
from .pdf_downloader import download_report_pdfs
from .sources.aliresearch import AliResearchFetcher
from .sources.aliyunreports import AliyunReportsFetcher
from .sources.base import ReportSourceFetcher
from .sources.fxbaogao import FxBaoGaoFetcher

logger = logging.getLogger(__name__)

_SOURCE_REGISTRY: Dict[str, Type[ReportSourceFetcher]] = {
    "aliresearch": AliResearchFetcher,
    "aliyunreports": AliyunReportsFetcher,
    "fxbaogao": FxBaoGaoFetcher,
}


async def fetch_all_reports(
    config: ReportsConfig,
    client: httpx.AsyncClient,
    ai_client=None,  # Optional[AIClient] — created by the CLI when ai_filter_enabled
) -> List[Report]:
    """Fetch reports from every source named in `config.sources`, dedup by id.

    When *ai_client* is provided and *config.ai_filter_enabled* is True,
    each report is judged for tech/AI relevance before inclusion.
    """
    reports: Dict[str, Report] = {}
    browser_fetchers: list = []

    report_filter = ReportFilter(ai_client) if ai_client and config.ai_filter_enabled else None

    for source_item in config.sources:
        source_name = source_item.name
        fetcher_cls = _SOURCE_REGISTRY.get(source_name)
        if fetcher_cls is None:
            logger.warning("Unknown report source %r; skipping", source_name)
            continue

        # Pass source-specific config where available.
        if source_name == "aliyunreports":
            from .sources.aliyunreports import AliyunReportsConfig
            fetcher = fetcher_cls(AliyunReportsConfig(year=config.aliyunreports_year))
        else:
            fetcher = fetcher_cls()

        native_ids = await fetcher.fetch_native_ids(client)
        for native_id in native_ids:
            report = await fetcher.fetch_detail(client, native_id)
            if report is None:
                continue

            # ── AI relevance filter (per-source via ai_filter) ──
            if report_filter is not None and source_item.ai_filter:
                if not await report_filter.is_tech_relevant(report):
                    continue

            # ── Download PDFs (skip if already local) ──
            if config.download_pdfs and config.pdf_output_dir:
                report = await download_report_pdfs(report, config, client)

            reports[report.id] = report

        # Collect fetchers that need browser cleanup.
        if hasattr(fetcher, "close"):
            browser_fetchers.append(fetcher)

    # Close any self-managed browser instances.
    for f in browser_fetchers:
        try:
            await f.close()
        except Exception as exc:
            logger.debug("Error closing browser for %s: %s", type(f).__name__, exc)

    return sorted(reports.values(), key=lambda r: r.published_at, reverse=True)
