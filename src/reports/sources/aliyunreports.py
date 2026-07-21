"""阿里云研究报告 (aliyun.com/reports) reports source.

The site is a React SPA built on Aliyun's lowcode engine — filters are
client-side (Ant Design checkboxes) and the detail page has ``在线阅读``
and ``下载报告`` buttons.

PDF download requires an Aliyun account login.  On first run, set
``headless=False`` in the config and log in when the browser window
opens.  The session is persisted to ``browser_profile_dir`` and reused
on subsequent runs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_LIST_PAGE_URL = "https://www.aliyun.com/reports"
_DETAIL_PAGE_BASE = "https://www.aliyun.com/reports"

# ── Optional Playwright import ──────────────────────────────────────────────
try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore[assignment]


class AliyunReportsConfig(BaseModel):
    """Source-local config for aliyun.com/reports filtering.

    PDF download requires an Aliyun account login.  On first run, set
    ``headless=False`` and log in when the browser window opens — the
    session is persisted to ``browser_profile_dir`` and reused.
    """

    content_category: str = "报告"
    year: str = "2026年"
    tech_category: str = "人工智能"
    pdf_output_dir: str = "data/reports_pdfs"
    browser_profile_dir: str = "data/aliyun_profile"
    headless: bool = False
    max_retries: int = 3
    timeout_ms: int = 30000
    download_pdfs: bool = True
    delay_between_requests: float = 0.5


class AliyunReportsFetcher(ReportSourceFetcher):
    """Fetches filtered reports from aliyun.com/reports via Playwright.

    Manages its own persistent browser context (not via SharedBrowserPool)
    so that Aliyun login cookies survive across runs.
    """

    source_name = "aliyunreports"
    requires_browser = False  # we manage our own browser

    def __init__(self, config: Optional[AliyunReportsConfig] = None):
        self.cfg = config or AliyunReportsConfig()
        self._playwright: Any = None
        self._browser_context: Any = None

    # ── fetch_native_ids ─────────────────────────────────────────────────

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Navigate to the listing page, apply filters, return report slugs."""
        if not _PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not installed. Run: uv sync --extra twitter")
            return []

        try:
            ctx = await self._ensure_browser()
            page = await ctx.new_page()
        except Exception as exc:
            logger.error("Failed to create browser page: %s", exc)
            return []

        try:
            for attempt in range(self.cfg.max_retries):
                try:
                    await page.goto(
                        _LIST_PAGE_URL,
                        wait_until="networkidle",
                        timeout=self.cfg.timeout_ms,
                    )
                    break
                except Exception:
                    if attempt == self.cfg.max_retries - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)

            await page.wait_for_timeout(3000)

            # ── Apply filters (client-side, no API re-fetch) ──
            for label in ["报告", "2026年", "人工智能"]:
                clicked = await self._click_filter(page, label)
                if clicked:
                    await page.wait_for_timeout(1500)

            await page.wait_for_timeout(2000)

            return await self._extract_visible_slugs(page)

        except Exception as exc:
            logger.warning("Error fetching aliyun native ids: %s", exc)
            return []
        finally:
            await page.close()

    async def _extract_visible_slugs(self, page) -> List[str]:
        """Extract report slugs from visible report cards in the DOM."""
        slugs: List[str] = []
        try:
            cards_data = await page.evaluate("""
                () => {
                    const results = [];
                    const cards = document.querySelectorAll('[class*="report-card-content"]');
                    cards.forEach(card => {
                        if (card.offsetParent === null) return;
                        const linkEl = card.querySelector('a[href*="/reports/"]')
                                    || card.closest('a[href*="/reports/"]');
                        const titleEl = card.querySelector('[class*="title"]');
                        const title = titleEl ? titleEl.innerText.trim() : '';
                        const href = linkEl ? linkEl.getAttribute('href') : '';
                        if (title || href) {
                            results.push({title, href});
                        }
                    });
                    return results;
                }
            """)
            for item in cards_data:
                href = (item.get("href") or "").strip()
                slug = href.replace("/reports/", "").rstrip("/")
                if slug:
                    slugs.append(slug)
                    logger.debug("Found visible report: %s (%s)", slug, item.get("title", "?"))
            logger.info("Extracted %d visible report slugs from DOM", len(slugs))
        except Exception as exc:
            logger.warning("Failed to extract slugs from DOM: %s", exc)
        return slugs

    # ── fetch_detail ─────────────────────────────────────────────────────

    async def fetch_detail(
        self, client: httpx.AsyncClient, native_id: str
    ) -> Optional[Report]:
        """Navigate to a report detail page, extract metadata, and download
        PDF.  The report URL is stored so users can click through to read
        online — no full-text extraction needed."""
        if not _PLAYWRIGHT_AVAILABLE:
            return None

        try:
            ctx = await self._ensure_browser()
            page = await ctx.new_page()
        except Exception as exc:
            logger.warning("Failed to create detail page: %s", exc)
            return None

        try:
            detail_url = f"{_DETAIL_PAGE_BASE}/{native_id}"

            for attempt in range(self.cfg.max_retries):
                try:
                    await page.goto(
                        detail_url,
                        wait_until="networkidle",
                        timeout=self.cfg.timeout_ms,
                    )
                    break
                except Exception:
                    if attempt == self.cfg.max_retries - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)

            await page.wait_for_timeout(3000)

            # ── Build Report from page meta + DOM ──
            report = await self._build_report_from_page(page, native_id)
            if report is None:
                return None

            if not report.content_text:
                report.content_text = report.summary or f"在线阅读: {detail_url}"

            # ── Download PDF ──
            if self.cfg.download_pdfs:
                pdf_urls = await self._download_pdfs_for_report(page, native_id, client)
                if pdf_urls:
                    report.pdf_urls = pdf_urls

            return report

        except Exception as exc:
            logger.warning("Error fetching aliyun report %s: %s", native_id, exc)
            return None
        finally:
            await page.close()

    # ── Browser management ───────────────────────────────────────────────

    async def _ensure_browser(self):
        """Return (or create) a persistent browser context.

        Uses ``launch_persistent_context`` so that cookies (including
        Aliyun login session) survive across runs.
        """
        if self._browser_context is not None:
            return self._browser_context

        pw = await async_playwright().start()
        self._playwright = pw

        profile_dir = Path(self.cfg.browser_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._browser_context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=self.cfg.headless,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        logger.info("Browser context ready (profile: %s, headless=%s)", profile_dir, self.cfg.headless)
        return self._browser_context

    async def close(self) -> None:
        """Close the browser. Call after all fetching is done."""
        if self._browser_context is not None:
            try:
                await self._browser_context.close()
            except Exception:
                pass
            self._browser_context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ── DOM-based report extraction ──────────────────────────────────────

    async def _build_report_from_page(
        self, page, native_id: str
    ) -> Optional[Report]:
        """Extract report metadata from the rendered detail page DOM."""
        try:
            meta = await page.evaluate("""
                () => {
                    const ogTitle = document.querySelector('meta[property="og:title"]');
                    const ogDesc = document.querySelector('meta[property="og:description"]');
                    const dateMeta = document.querySelector('meta[name="date"]');
                    const lastMod = document.querySelector('meta[name="last-modified"]');
                    // Full content introduction (longer than the truncated og:description).
                    const introEl = document.querySelector('[class*="report-content-introductio"]');
                    const introduction = introEl ? introEl.innerText.trim() : '';
                    // Institution + display date: "YYYY年MM月 | Institution" below the title.
                    const infoEl = document.querySelector('[class*="report-head-rela"]');
                    const sourceLine = infoEl ? infoEl.innerText.trim() : '';
                    return {
                        ogTitle: ogTitle ? ogTitle.getAttribute('content') : '',
                        ogDesc: ogDesc ? ogDesc.getAttribute('content') : '',
                        date: dateMeta ? dateMeta.getAttribute('content') : '',
                        lastModified: lastMod ? lastMod.getAttribute('content') : '',
                        introduction: introduction,
                        sourceLine: sourceLine,
                    };
                }
            """)

            # Parse title from og:title (format: "阿里云研究院:Title_阿里云研究报告与白皮书")
            raw_title = (meta.get("ogTitle") or "").strip()
            title = raw_title
            # Strip "Institution:" prefix.
            if ":" in raw_title:
                title = raw_title.split(":")[-1].strip()
            # Strip "_阿里云研究报告与白皮书" suffix.
            if "_" in title:
                title = title.split("_")[0].strip()
            # Strip parenthetical remarks appended by the page template.
            for suffix in ("(在线阅读/下载）", "(在线阅读/下载)", "(在线阅读/下载"):
                if title.endswith(suffix):
                    title = title[: -len(suffix)].strip()
            if not title:
                title = native_id

            # Parse date
            published_at = datetime.now(_SHANGHAI_TZ)
            date_str = meta.get("date") or ""
            if date_str:
                parsed = self._parse_dt(date_str)
                if parsed:
                    published_at = parsed

            updated_at = published_at
            last_mod = meta.get("lastModified") or ""
            if last_mod:
                parsed = self._parse_dt(last_mod)
                if parsed:
                    updated_at = parsed

            summary = (meta.get("introduction") or meta.get("ogDesc") or "").strip() or None

            # Extract institution from "YYYY年MM月 | Institution" line below title.
            institution = "阿里云"
            source_line = (meta.get("sourceLine") or "").strip()
            if "|" in source_line:
                institution = source_line.split("|")[-1].strip()

            return Report(
                id=f"{self.source_name}:{native_id}",
                source=self.source_name,
                native_id=native_id,
                title=title,
                institution=institution,
                author=None,
                url=f"{_DETAIL_PAGE_BASE}/{native_id}",
                pdf_urls=[],
                summary=summary,
                content_text=summary or f"在线阅读: {_DETAIL_PAGE_BASE}/{native_id}",
                categories=[],
                published_at=published_at,
                updated_at=updated_at,
                fetched_at=datetime.now(_SHANGHAI_TZ),
            )
        except Exception as exc:
            logger.warning("Failed to build report from page DOM: %s", exc)
            return None

    # ── PDF download ─────────────────────────────────────────────────────

    # Base URL pattern for direct PDF downloads (no auth required).
    _PDF_BASE = "https://merak.alicdn.com/aliyundotcom-report"

    async def _download_pdfs_for_report(
        self, page, native_id: str, client: httpx.AsyncClient
    ) -> List[dict]:
        """Download the report PDF via the public CDN URL.

        PDFs are served from ``merak.alicdn.com`` with the pattern
        ``/aliyundotcom-report/{slug}.pdf`` — no login required.
        Falls back to the download button if the CDN URL 404s.
        """
        from ..pdf import sanitize_filename

        pdf_urls: List[dict] = []
        output_dir = Path(self.cfg.pdf_output_dir) / self.source_name / native_id
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_filename(native_id)
        output_path = output_dir / f"{safe_name}.pdf"

        if output_path.exists():
            logger.info("PDF already exists, skipping: %s", output_path)
            pdf_urls.append({
                "name": native_id,
                "url": f"{self._PDF_BASE}/{native_id}.pdf",
                "local_path": str(output_path),
            })
            return pdf_urls

        # ── Primary path: public CDN URL ──
        pdf_url = f"{self._PDF_BASE}/{native_id}.pdf"
        try:
            resp = await client.get(pdf_url, timeout=30.0)
            if resp.status_code == 200 and len(resp.content) > 1000:
                output_path.write_bytes(resp.content)
                logger.info("Downloaded PDF (%d bytes) to %s", len(resp.content), output_path)
                pdf_urls.append({
                    "name": native_id,
                    "url": pdf_url,
                    "local_path": str(output_path),
                })
                return pdf_urls
            else:
                logger.debug("CDN PDF returned status %d for %s", resp.status_code, native_id)
        except Exception as exc:
            logger.debug("CDN PDF download failed for %s: %s", native_id, exc)

        # ── Fallback: intercept PDF URL from page network responses ──
        pdf_captured: Optional[str] = None

        async def _capture_pdf(response):
            nonlocal pdf_captured
            if pdf_captured:
                return
            ct = response.headers.get("content-type", "")
            if "pdf" in ct and response.status == 200 and "merak" in response.url:
                pdf_captured = response.url
                logger.debug("Captured PDF URL from page: %s", pdf_captured)

        page.on("response", _capture_pdf)

        # Reload to trigger PDF request
        try:
            await page.reload(wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        if pdf_captured:
            try:
                resp = await client.get(pdf_captured, timeout=30.0)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    output_path.write_bytes(resp.content)
                    logger.info("Downloaded PDF (%d bytes) via captured URL to %s", len(resp.content), output_path)
                    pdf_urls.append({
                        "name": native_id,
                        "url": pdf_captured,
                        "local_path": str(output_path),
                    })
                    return pdf_urls
            except Exception as exc:
                logger.warning("Failed to download captured PDF URL: %s", exc)

        # ── Last resort: click download button (requires login) ──
        try:
            dl_btn = page.locator('button:has-text("下载报告")').first
            if await dl_btn.is_visible(timeout=3000):
                async with page.expect_download(timeout=self.cfg.timeout_ms) as dl_info:
                    await dl_btn.click()
                download = await dl_info.value
                safe_name = sanitize_filename(native_id)
                out = output_dir / f"{safe_name}.pdf"
                await download.save_as(str(out))
                logger.info("Downloaded PDF via button click to %s", out)
                pdf_urls.append({
                    "name": native_id,
                    "url": page.url,
                    "local_path": str(out),
                })
        except Exception as exc:
            logger.warning("All PDF download methods failed for %s: %s", native_id, exc)

        return pdf_urls

    # ── Filter interaction ───────────────────────────────────────────────

    async def _click_filter(self, page, label: str) -> bool:
        """Click a filter checkbox by its label text."""
        try:
            # The filter labels are in <span> elements.
            target = page.locator(f'span:has-text("{label}")').first
            if await target.is_visible(timeout=2000):
                await target.click()
                logger.debug("Clicked filter: %s", label)
                return True

            # Fallback: text-based locator.
            target = page.get_by_text(label, exact=True).first
            if await target.is_visible(timeout=2000):
                await target.click()
                logger.debug("Clicked filter: %s (via text)", label)
                return True

            logger.warning("Could not find filter element for %r", label)
            return False
        except Exception as exc:
            logger.warning("Error clicking filter %r: %s", label, exc)
            return False

    # ── Parsing helpers (for API-based parsing, kept for flexibility) ─────

    @staticmethod
    def _parse_list_response(body: dict) -> List[str]:
        """Extract report slugs from a ``listAll`` API response body."""
        items: list = body.get("data") if isinstance(body, dict) else body
        if not isinstance(items, list):
            return []
        slugs: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug") or item.get("id") or item.get("reportId")
            if slug:
                slugs.append(str(slug))
        return slugs

    def _parse_detail_response(
        self, body: dict, native_id: str
    ) -> Optional[Report]:
        """Build a ``Report`` from a detail API response."""
        data: dict = body.get("data") if isinstance(body, dict) and "data" in body else body
        if not isinstance(data, dict) or not data:
            return None

        title = (data.get("title") or "").strip()
        if not title:
            return None

        published_at = self._parse_dt(data.get("publishDate") or data.get("publishedAt"))
        if published_at is None:
            published_at = datetime.now(_SHANGHAI_TZ)
        updated_at = self._parse_dt(data.get("updateDate") or data.get("updatedAt")) or published_at

        categories: List[str] = []
        raw_cats = data.get("categoryNames") or data.get("categories") or []
        if isinstance(raw_cats, list):
            categories = [str(c).strip() for c in raw_cats if c]

        pdf_list = data.get("pdfList") or data.get("docUrlList") or []
        pdf_urls = [
            {"name": doc.get("name", ""), "url": doc.get("url", "")}
            for doc in pdf_list
            if doc.get("url")
        ]

        content_text = self._clean_html(data.get("content") or "")

        return Report(
            id=f"{self.source_name}:{native_id}",
            source=self.source_name,
            native_id=native_id,
            title=title,
            institution=data.get("institution") or data.get("organName") or "阿里云",
            author=data.get("author") or None,
            url=f"{_DETAIL_PAGE_BASE}/{native_id}",
            pdf_urls=pdf_urls,
            summary=(data.get("summary") or data.get("description") or None),
            content_text=content_text,
            categories=categories,
            published_at=published_at,
            updated_at=updated_at,
            view_count=data.get("viewCount"),
            download_count=data.get("downloadCount"),
            fetched_at=datetime.now(_SHANGHAI_TZ),
        )

    # ── Utility helpers ──────────────────────────────────────────────────

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
        clean = str(value).strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                naive = datetime.strptime(clean, fmt)
                return naive.replace(tzinfo=_SHANGHAI_TZ)
            except ValueError:
                continue
        return None
