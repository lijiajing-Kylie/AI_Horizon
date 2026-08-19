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

import asyncio
import logging
from typing import Dict, List, Optional, Type

import httpx

from ..models import ReportsConfig
from .filter import ReportFilter
from .models import Report
from .pdf_downloader import download_report_pdfs
from .scoring import compute_composite_score
from .sources.aliresearch import AliResearchFetcher
from .sources.aliyunreports import AliyunReportsFetcher
from .sources.base import ReportSourceFetcher
from .sources.fxbaogao import FxBaoGaoFetcher
from .sources.wxmp import WxMpReportFetcher

logger = logging.getLogger(__name__)

_SOURCE_REGISTRY: Dict[str, Type[ReportSourceFetcher]] = {
    "aliresearch": AliResearchFetcher,
    "aliyunreports": AliyunReportsFetcher,
    "fxbaogao": FxBaoGaoFetcher,
    "wxmp": WxMpReportFetcher,
}


async def fetch_all_reports(
    config: ReportsConfig,
    client: httpx.AsyncClient,
    ai_client=None,  # Optional[AIClient] — created by the CLI when ai_filter_enabled
    wxmp_config=None,  # Optional[WxMpConfig] — feeds/params for bundled we-mp-rss
    wxmp_max_age: int | None = None,  # Override max_age_days for wxmp source
    db=None,  # Optional[HorizonDB] — collector 中间表读分支 + 消费标记
) -> List[Report]:
    """Fetch reports from every source named in `config.sources`, dedup by id.

    When *ai_client* is provided and *config.ai_filter_enabled* is True,
    each report is judged for tech/AI relevance before inclusion.

    *wxmp_config* (a ``WxMpConfig`` from ``config.sources.wxmp``) is forwarded
    to the bundled we-mp-rss report fetcher for feeds and gather settings.

    *db* 非 None 时,微信报告源优先从 collector 中间表读(use_store=True),
    窗口为空自动降级实时抓取;detail 全部完成后统一打消费标记。
    """
    reports: Dict[str, Report] = {}
    browser_fetchers: list = []
    wxmp_reports: List[Report] = []  # batch-processed via Playwright later

    report_filter = ReportFilter(ai_client) if ai_client and config.ai_filter_enabled else None

    total_sources = len(config.sources)
    for idx, source_item in enumerate(config.sources, 1):
        source_name = source_item.name
        logger.info("[%d/%d] Fetching source: %s", idx, total_sources, source_name)
        fetcher_cls = _SOURCE_REGISTRY.get(source_name)
        if fetcher_cls is None:
            logger.warning("Unknown report source %r; skipping", source_name)
            continue

        # Pass source-specific config where available.
        if source_name == "aliyunreports":
            from .sources.aliyunreports import AliyunReportsConfig
            fetcher = fetcher_cls(AliyunReportsConfig(year=config.aliyunreports_year))
        elif source_name == "wxmp":
            from ..models import WxMpConfig
            from .sources.wxmp import WxMpReportConfig
            wc = wxmp_config if isinstance(wxmp_config, WxMpConfig) else WxMpConfig()
            known_feeds = {
                f.name: f.feed_id for f in (wc.feeds or [])
                if f.feed_id
            } if hasattr(wc, "feeds") else {}
            fetcher = fetcher_cls(WxMpReportConfig(
                account_names=source_item.account_names,
                max_age_days=wxmp_max_age or 7,
                known_feeds=known_feeds,
                wxmp=wc,
                db=db,
            ))
        else:
            fetcher = fetcher_cls()

        native_ids = await fetcher.fetch_native_ids(client)
        source_kept = 0
        filter_skipped = 0
        for n_idx, native_id in enumerate(native_ids):
            report = await fetcher.fetch_detail(client, native_id)
            if report is None:
                continue

            # ── AI relevance filter (per-source via ai_filter) ──
            skip = getattr(report, "skip_ai_filter", False)
            if report_filter is not None and source_item.ai_filter and not skip:
                if not await report_filter.is_tech_relevant(report):
                    filter_skipped += 1
                    continue

            # ── Download PDFs (skip if already local) ──
            if config.download_pdfs and config.pdf_output_dir:
                report = await download_report_pdfs(report, config, client)

            # ── Collect wxmp reports for browser-based PDF resolution ──
            if source_name == "wxmp" and config.download_pdfs and config.pdf_output_dir:
                wxmp_reports.append(report)
            else:
                reports[report.id] = report
            source_kept += 1

            # Log AI filter progress periodically.
            if report_filter is not None and source_item.ai_filter and (n_idx + 1) % 10 == 0:
                logger.info(
                    "  AI filter: %d/%d processed (%d kept, %d filtered out) for %s",
                    n_idx + 1, len(native_ids), source_kept, filter_skipped, source_name,
                )

        if report_filter is not None and source_item.ai_filter and source_kept + filter_skipped > 0:
            logger.info(
                "  AI filter done for %s: %d kept, %d filtered out of %d",
                source_name, source_kept, filter_skipped, source_kept + filter_skipped,
            )

        logger.info(
            "[%d/%d] %s: %d native ids, %d kept (running total: %d)",
            idx, total_sources, source_name, len(native_ids), source_kept, len(reports) + len(wxmp_reports),
        )

        # 标记 store 分支已消费的微信文章(detail 循环全部完成后才标记——
        # 崩溃落在标记前则下次重读,reports UPSERT 累积按 id 不会丢)。
        if source_name == "wxmp":
            mark_consume = getattr(fetcher, "mark_reports_consumed", None)
            if mark_consume is not None:
                mark_consume()

        # Collect fetchers that need browser cleanup.
        if hasattr(fetcher, "close"):
            browser_fetchers.append(fetcher)

    # Close any self-managed browser instances (aliyunreports, etc.).
    for f in browser_fetchers:
        try:
            await f.close()
        except Exception as exc:
            logger.debug("Error closing browser for %s: %s", type(f).__name__, exc)

    # ── Batch-process wxmp reports through Playwright browser resolver ──
    if wxmp_reports and config.download_pdfs and config.pdf_output_dir:
        logger.info(
            "Launching browser resolver for %d wxmp reports …", len(wxmp_reports)
        )
        from .wxmp_browser_resolver import WxMpBrowserResolver

        resolver = WxMpBrowserResolver(
                pdf_output_dir=config.pdf_output_dir,
                headless=config.browser_headless,
            )
        try:
            resolved = await resolver.resolve_batch(wxmp_reports)
            for r in resolved:
                reports[r.id] = r
        finally:
            await resolver.close()

    # ── Composite score（0.5×AI相关 + 0.5×篇幅）统一计算，供前端排序 ──
    # 必须在 wxmp resolver 之后：此时 wxmp 报告的 PDF local_path 已写入。
    # pypdf 提取为同步 IO，用 to_thread 避免阻塞事件循环。
    for r in reports.values():
        await asyncio.to_thread(compute_composite_score, r, config.pdf_output_dir)

    return sorted(reports.values(), key=lambda r: r.published_at, reverse=True)
