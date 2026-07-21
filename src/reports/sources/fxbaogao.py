"""发现报告 (fxbaogao.com) reports source.

The site uses Next.js with server-rendered HTML for both listing and detail
pages — no JavaScript execution required for scraping.  Each organization has
an archive page at ``/archives/organization/{name}`` with ``?page=N``
pagination, newest-first.

Detail pages at ``/detail/{id}`` carry the full report body rendered directly
in the HTML.  The ``/view?id={id}`` reader page is a React SPA; optional
Playwright-based extraction is gated behind ``try_view_page`` (default off).

HTML structure (verified 2026-07):
- Listing: ``a[href*="/detail/"]`` for ids, sibling ``[class*="metas"]`` div
  carries date / org / author in ordered ``<span>`` children.
- Detail: ``h1 > a`` for title, metadata in ``[class*="metas"].flex-ca`` with
  Ant Design icons marking each field, ``[aria-hidden="true"]`` for the
  summary/intro paragraphs, ``p`` elements for the body.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fxbaogao.com"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# ── Optional Playwright import (for /view page enhancement) ──────────────
try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore[assignment]


class FxBaoGaoConfig(BaseModel):
    """Source-local config for fxbaogao.com.

    Each organization is scraped independently; the same report appearing
    under multiple orgs is deduplicated by its numeric detail id.

    ``max_age_days`` enables time-bounded fetching for scheduled runs
    (e.g. set to 1 for daily cron).  When None, all pages up to
    ``max_pages`` are fetched regardless of age.
    """

    organizations: List[str] = Field(
        default_factory=lambda: [
            "腾讯研究院",
            "阿里研究院",
            "字节跳动",
            "美团",
            "百度",
            "华为",
        ]
    )
    max_pages: int = 5
    max_per_org: int = 9999  # effectively unlimited (was 10)
    max_age_days: Optional[int] = 940  # only reports from 2024 onwards
    request_delay: float = 1.0  # seconds between page fetches
    try_view_page: bool = False  # attempt /view page extraction (needs Playwright)


class FxBaoGaoFetcher(ReportSourceFetcher):
    """Fetches reports from fxbaogao.com by organization archive pages."""

    source_name = "fxbaogao"

    def __init__(self, config: Optional[FxBaoGaoConfig] = None):
        self.cfg = config or FxBaoGaoConfig()
        self._playwright: Any = None  # type: ignore[annotation-unchecked]
        self._browser: Any = None  # type: ignore[annotation-unchecked]

    # ═══════════════════════════════════════════════════════════════════════
    # fetch_native_ids
    # ═══════════════════════════════════════════════════════════════════════

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Paginate organization archive pages, return deduplicated detail ids."""
        all_ids: List[str] = []
        seen_ids: set = set()
        cutoff = self._cutoff_date()

        for org in self.cfg.organizations:
            logger.info(
                "fxbaogao: scanning org %r (max %d pages, max %d per org)",
                org, self.cfg.max_pages, self.cfg.max_per_org,
            )
            prev_page_ids: Optional[set] = None
            org_count = 0  # how many ids we've kept for this org so far

            for page in range(1, self.cfg.max_pages + 1):
                ids, dates = await self._fetch_org_page(client, org, page)

                if not ids:
                    logger.debug(
                        "fxbaogao: %r page %d returned no results, stopping", org, page
                    )
                    break

                # Dedup
                new_ids = [i for i in ids if i not in seen_ids]
                if not new_ids:
                    logger.debug(
                        "fxbaogao: %r page %d all duplicates, stopping", org, page
                    )
                    break

                # Safety valve: broken pagination returning same ids
                page_id_set = set(ids)
                if prev_page_ids is not None and page_id_set == prev_page_ids:
                    logger.debug(
                        "fxbaogao: %r page %d same ids as previous page, stopping",
                        org,
                        page,
                    )
                    break
                prev_page_ids = page_id_set

                # Time filter: pages are newest-first, so stop when the
                # *last* (oldest) report on this page is still >= cutoff
                # but if EVERY report on the page is already before cutoff,
                # we can stop (and only keep those still in window).
                if cutoff is not None and dates:
                    in_window = [
                        (i, d) for i, d in zip(ids, dates) if d >= cutoff
                    ]
                    if not in_window:
                        logger.debug(
                            "fxbaogao: %r page %d all dates before cutoff %s, stopping",
                            org, page, cutoff.date(),
                        )
                        break
                    # Only keep the ids that are in the time window
                    for i, _d in in_window:
                        if i not in seen_ids:
                            all_ids.append(i)
                            seen_ids.add(i)
                            org_count += 1
                    # If we filtered some out, the next page will be even older → stop
                    if len(in_window) < len(ids):
                        logger.debug(
                            "fxbaogao: %r page %d partially outside time window, stopping",
                            org, page,
                        )
                        break
                else:
                    all_ids.extend(new_ids)
                    seen_ids.update(new_ids)
                    org_count += len(new_ids)

                # Stop if we've reached the per-org limit
                if org_count >= self.cfg.max_per_org:
                    logger.debug(
                        "fxbaogao: %r reached max_per_org=%d, stopping",
                        org, self.cfg.max_per_org,
                    )
                    break

                if page < self.cfg.max_pages:
                    await asyncio.sleep(self.cfg.request_delay)

        logger.info(
            "fxbaogao: collected %d unique report IDs across %d org(s)",
            len(all_ids),
            len(self.cfg.organizations),
        )
        return all_ids

    async def _fetch_org_page(
        self, client: httpx.AsyncClient, org: str, page: int
    ) -> tuple:
        """Fetch one page of an organization archive.

        Returns ``(ids, dates)`` — parallel lists of equal length.  Only
        report cards that actually belong to *org* are kept; the site's
        pagination is broken beyond page 1 and mixes in reports from other
        organisations, so we validate via the metadata row's org link.

        Dates are extracted from the metadata row; when extraction fails the
        date defaults to *now* so the item is never filtered out by the time
        cutoff.
        """
        encoded_org = quote(org, safe="")
        url = f"{BASE_URL}/archives/organization/{encoded_org}"
        if page > 1:
            url += f"?page={page}"

        try:
            resp = await client.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("fxbaogao: error fetching %r page %d: %s", org, page, exc)
            return [], []

        soup = BeautifulSoup(resp.text, "html.parser")
        ids: List[str] = []
        dates: List[datetime] = []

        for link in soup.select('a[href*="/detail/"]'):
            href = (link.get("href") or "").strip()
            m = re.search(r"/detail/(\d+)", href)
            if not m:
                continue
            native_id = m.group(1)
            if native_id in ids:
                continue

            # Verify this report card belongs to the target org.
            if not self._card_belongs_to_org(link, org):
                continue

            ids.append(native_id)
            dates.append(self._extract_date_near_link(link))

        logger.debug("fxbaogao: %r page %d → %d ids", org, page, len(ids))
        return ids, dates

    @staticmethod
    def _card_belongs_to_org(link: Tag, org: str) -> bool:
        """Check whether a report-card ``/detail/`` link belongs to *org*.

        Walks up from *link* to find the nearest ``[class*=\"metas\"]`` row
        and looks for an ``<a href=\"/archives/organization/{org}\">`` inside
        it.  Comparison is done on the URL-decoded href.
        """
        from urllib.parse import unquote

        # Walk up to find the card container (at most 3 levels)
        card = link
        for _ in range(3):
            parent = card.parent
            if parent is None:
                break
            card = parent
            metas = card.select_one('[class*="metas"]')
            if metas is not None:
                break

        if card is None:
            return True  # can't verify → keep (don't over-filter)

        metas = card.select_one('[class*="metas"]')
        if metas is None:
            # No metadata row found — keep the item rather than risk
            # false-negative filtering.
            return True

        org_link = metas.select_one('a[href*="/archives/organization/"]')
        if org_link is None:
            # No org link in metadata — keep the item.
            return True

        href = (org_link.get("href") or "").strip()
        # href looks like "/archives/organization/腾讯研究院"
        # org might be URL-encoded or not — decode both sides for comparison.
        decoded_href = unquote(href)
        decoded_org = unquote(org)
        return decoded_org in decoded_href

        logger.debug("fxbaogao: %r page %d → %d ids", org, page, len(ids))
        return ids, dates

    @staticmethod
    def _extract_date_near_link(link: Tag) -> datetime:
        """Find the date that belongs to a report-card title link.

        The metadata div (class containing ``metas`` and ``flex-ca``) sits
        right after the title link.  Inside it, the date is the ``<span>``
        immediately following the ``#icon-pubtime`` SVG icon.
        """
        # Walk up to the card container, then find the metas row
        card = link
        for _ in range(3):  # climb at most 3 levels
            parent = card.parent
            if parent is None:
                break
            card = parent
            metas = card.select_one('[class*="metas"]')
            if metas is not None:
                break

        if card is None:
            return datetime.now(_SHANGHAI_TZ)

        metas = card.select_one('[class*="metas"]')
        if metas is None:
            # Fallback: scan all text in parent
            parent = link.parent
            if parent is not None:
                text = parent.get_text(separator=" ", strip=True)
                return FxBaoGaoFetcher._parse_date_from_text(text)
            return datetime.now(_SHANGHAI_TZ)

        return FxBaoGaoFetcher._extract_date_from_metas_row(metas)

    @staticmethod
    def _extract_date_from_metas_row(metas: Tag) -> datetime:
        """Extract the date from an Ant Design metadata row.

        The date is the first ``<span>`` child whose text matches YYYY-MM-DD.
        """
        for span in metas.find_all("span"):
            text = span.get_text(strip=True)
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                return FxBaoGaoFetcher._parse_date_from_text(text)
        return datetime.now(_SHANGHAI_TZ)

    # ═══════════════════════════════════════════════════════════════════════
    # fetch_detail
    # ═══════════════════════════════════════════════════════════════════════

    async def fetch_detail(
        self, client: httpx.AsyncClient, native_id: str
    ) -> Optional[Report]:
        """Fetch and parse a single report detail page."""
        url = f"{BASE_URL}/detail/{native_id}"

        try:
            resp = await client.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("fxbaogao: error fetching detail %s: %s", native_id, exc)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # ── Title (h1 > a) ──
        title = self._extract_title(soup)
        if not title:
            logger.warning(
                "fxbaogao: no title found for detail %s, skipping", native_id
            )
            return None

        # ── Metadata row ──
        metas = soup.select_one('[class*="metas"].flex-ca')
        published_at = self._extract_date_from_metas_row(metas) if metas else self._extract_date_fallback(soup)
        institution = self._extract_institution_from_metas(metas)
        author = self._extract_author_from_metas(metas)
        categories = self._extract_categories(soup, metas)

        # ── Summary (aria-hidden div) ──
        summary = self._extract_summary(soup)

        # ── Body text ──
        content_text = self._extract_content(soup)

        # ── PDF URLs ──
        pdf_urls = self._extract_pdf_urls(soup, native_id)

        # ── Optional: /view page enhancement ──
        if self.cfg.try_view_page and _PLAYWRIGHT_AVAILABLE:
            view_extra = await self._try_view_page(native_id)
            if view_extra:
                if view_extra.get("pdf_urls"):
                    existing = {p["url"] for p in pdf_urls}
                    for p in view_extra["pdf_urls"]:
                        if p["url"] not in existing:
                            pdf_urls.append(p)
                if view_extra.get("content"):
                    if len(view_extra["content"]) > len(content_text):
                        content_text = view_extra["content"]

        return Report(
            id=f"{self.source_name}:{native_id}",
            source=self.source_name,
            native_id=native_id,
            title=title,
            institution=institution,
            author=author,
            url=url,
            pdf_urls=pdf_urls,
            summary=summary,
            content_text=content_text,
            categories=categories,
            published_at=published_at,
            updated_at=published_at,
            view_count=None,
            download_count=None,
            fetched_at=datetime.now(_SHANGHAI_TZ),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Detail-page field extractors
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        """Extract title from ``h1 > a``, falling back to og:title."""
        h1 = soup.find("h1")
        if h1:
            link = h1.find("a")
            if link:
                text = link.get_text(strip=True)
                if text:
                    return text
            text = h1.get_text(strip=True)
            if text:
                return text

        og = soup.select_one('meta[property="og:title"]')
        if og:
            content = (og.get("content") or "").strip()
            # Format: "[机构名]：标题 - 发现报告"
            if " - 发现报告" in content:
                content = content.rsplit(" - 发现报告", 1)[0].strip()
            # Strip "[机构名]：" prefix if present
            if content.startswith("["):
                bracket = content.find("]：")
                if bracket > 0:
                    content = content[bracket + 2 :].strip()
                else:
                    # Maybe it's "]：" without the CJK colon
                    bracket = content.find("]:")
                    if bracket > 0:
                        content = content[bracket + 2 :].strip()
            return content

        return ""

    @staticmethod
    def _extract_institution_from_metas(metas: Optional[Tag]) -> str:
        """Extract institution name from the metadata row.

        The org link uses ``href="/archives/organization/{name}"``.
        """
        if metas is None:
            return "未知机构"

        org_link = metas.select_one('a[href*="/archives/organization/"]')
        if org_link:
            name = org_link.get_text(strip=True)
            if name:
                return name

        return "未知机构"

    @staticmethod
    def _extract_author_from_metas(metas: Optional[Tag]) -> Optional[str]:
        """Extract author from the metadata row.

        The author is the last ``<span>`` child — after the ``#icon-uploader`` icon.
        """
        if metas is None:
            return None

        spans = metas.find_all("span")
        if not spans:
            return None

        # The last span in the metas row is the author
        last_span = spans[-1]
        text = last_span.get_text(strip=True)
        if text and text != "-" and len(text) <= 10:
            return text

        return None

    @staticmethod
    def _extract_date_fallback(soup: BeautifulSoup) -> datetime:
        """Fallback date extraction when the metas row is missing."""
        for selector in (
            'meta[property="article:published_time"]',
            'meta[name="date"]',
        ):
            meta = soup.select_one(selector)
            if meta:
                parsed = FxBaoGaoFetcher._parse_date(
                    (meta.get("content") or "").strip()
                )
                if parsed:
                    return parsed

        # Scan for YYYY-MM-DD in meta containers
        for container in soup.select('[class*="meta"], [class*="time"], [class*="date"]'):
            parsed = FxBaoGaoFetcher._parse_date_from_text(
                container.get_text(strip=True)
            )
            if parsed != datetime.now(_SHANGHAI_TZ):
                return parsed

        return FxBaoGaoFetcher._parse_date_from_text(soup.get_text())

    @staticmethod
    def _extract_categories(
        soup: BeautifulSoup, metas: Optional[Tag]
    ) -> List[str]:
        """Extract category/industry tags.

        On the detail page the first ``<a>`` in the metadata row (with class
        ``d2 ed``) links to ``/archives/industry/{name}`` — that's the primary
        category.  We also scan breadcrumbs for additional context.
        """
        cats: List[str] = []

        # Primary: the industry link in the metadata row
        if metas is not None:
            industry_link = metas.select_one('a[href*="/archives/industry/"]')
            if industry_link:
                text = industry_link.get_text(strip=True)
                if text:
                    cats.append(text)

        # Secondary: breadcrumb links (exclude "首页" and "报告详情")
        breadcrumb = soup.select_one("nav.ant-breadcrumb, [class*='breadcrumb']")
        if breadcrumb:
            for link in breadcrumb.select("a"):
                text = link.get_text(strip=True)
                if text and text not in ("首页", "Home", "报告详情", "当前位置：首页"):
                    if text not in cats:
                        cats.append(text)

        return cats

    @staticmethod
    def _extract_summary(soup: BeautifulSoup) -> Optional[str]:
        """Extract the report summary/intro paragraphs.

        The summary sits right after the ``.ant-divider`` (which follows the
        metadata row) and before the cover image / body content.  It is
        usually wrapped in a ``<div aria-hidden="true">`` with ``<p>`` tags,
        but some reports use ``<ul>`` bullet lists or plain ``<div>`` text
        instead.
        """
        # Strategy 1: aria-hidden div with <p> tags (most common)
        for hidden in soup.select('[aria-hidden="true"]'):
            paragraphs = hidden.find_all("p")
            if not paragraphs:
                continue
            text = "\n".join(
                p.get_text(separator=" ", strip=True) for p in paragraphs
            )
            if len(text) > 50:
                return text

        # Strategy 2: first text-bearing block after .ant-divider
        divider = soup.select_one(".ant-divider")
        if divider is not None:
            # Collect all following siblings until we hit a structural boundary
            parts: list[str] = []
            for sibling in divider.find_next_siblings():
                # Stop at the page-body section or sidebar
                cls = " ".join(sibling.get("class", []))
                if any(kw in cls for kw in ("page__", "footer__", "likes__", "ReportLike")):
                    break
                # Collect text from <p>, <li>, or direct text nodes
                for tag in sibling.find_all(["p", "li"]):
                    t = tag.get_text(separator=" ", strip=True)
                    if len(t) > 10:
                        parts.append(t)
                # Also handle plain <div> with direct text (no inner <p>/<li>)
                if not parts and sibling.name == "div":
                    t = sibling.get_text(separator=" ", strip=True)
                    if len(t) > 30:
                        parts.append(t)
                if parts:
                    break  # take the first text-bearing block as summary

            if parts:
                text = "\n".join(parts)
                if len(text) > 50:
                    return text

        # Strategy 3: og:description (last resort — often generic site desc)
        og = soup.select_one('meta[property="og:description"]')
        if og:
            content = (og.get("content") or "").strip()
            if len(content) > 20:
                return content

        return None

    @staticmethod
    def _extract_content(soup: BeautifulSoup) -> str:
        """Extract the report body text.

        The body ``<p>`` elements live inside the Next.js page container after
        the ``[aria-hidden="true"]`` summary block.  We collect all ``<p>``
        tags that are *after* the summary and before the sidebar / footer.
        """
        # Find the main content column (the left 16/24 column)
        main_col = soup.select_one(
            ".ant-col.ant-col-24.ant-col-lg-16, "
            "[class*='ReportCard-style-module'], "
            "article, main"
        )
        if main_col is None:
            main_col = soup

        # Remove noisy elements
        for tag_name in ("script", "style", "nav", "header", "footer", "aside"):
            for tag in main_col.find_all(tag_name):
                tag.decompose()

        # Remove the "你可能感兴趣" sidebar and similar recommendation blocks
        for noise_selector in (
            '[class*="ReportLike"], '
            '[class*="likes__"], '
            '[class*="recommend"], '
            '[class*="related"]',
        ):
            for tag in main_col.select(noise_selector):
                tag.decompose()

        # Remove the metadata row (already extracted)
        for metas in main_col.select('[class*="metas"]'):
            metas.decompose()

        # Remove the summary block (already extracted)
        for hidden in main_col.select('[aria-hidden="true"]'):
            hidden.decompose()

        # Remove breadcrumb
        for bc in main_col.select("nav.ant-breadcrumb, [class*='breadcrumb']"):
            bc.decompose()

        # Remove dividers
        for divider in main_col.select(".ant-divider, [class*='divider']"):
            divider.decompose()

        # Remove the footer "点击免费查看完整报告" area
        for footer in main_col.select('[class*="footer__"]'):
            footer.decompose()

        # Collect text from content tags
        parts: List[str] = []
        for tag in main_col.find_all(
            ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"]
        ):
            text = tag.get_text(separator=" ", strip=True)
            # Skip empty, navigation crumbs, and metadata fragments
            if not text or len(text) <= 3:
                continue
            if re.match(r"^(当前位置|首页|报告详情)$", text):
                continue
            parts.append(text)

        return "\n\n".join(parts)

    @staticmethod
    def _extract_pdf_urls(soup: BeautifulSoup, native_id: str) -> List[dict]:
        """Extract PDF links from the detail page."""
        pdfs: List[dict] = []
        seen: set = set()

        # Direct .pdf links
        for link in soup.select(
            'a[href$=".pdf"], a[href*=".pdf?"], a[href*=".pdf#"]'
        ):
            href = (link.get("href") or "").strip()
            if href and href not in seen:
                name = link.get_text(strip=True) or "PDF"
                pdfs.append({"name": name, "url": href})
                seen.add(href)

        # The /view?id= link (link to the full reader; useful as fallback)
        view_url = f"{BASE_URL}/view?id={native_id}"
        if view_url not in seen:
            pdfs.append({"name": "在线阅读", "url": view_url})
            seen.add(view_url)

        return pdfs

    # ═══════════════════════════════════════════════════════════════════════
    # /view page extraction (Playwright, optional)
    # ═══════════════════════════════════════════════════════════════════════

    async def _try_view_page(self, native_id: str) -> Optional[dict]:
        """Extract extra content/PDFs from the React-based ``/view`` reader."""
        if not _PLAYWRIGHT_AVAILABLE:
            return None

        try:
            if self._browser is None:
                pw = await async_playwright().start()
                self._playwright = pw
                self._browser = await pw.chromium.launch(headless=True)

            page = await self._browser.new_page()
            try:
                await page.goto(
                    f"{BASE_URL}/view?id={native_id}",
                    wait_until="networkidle",
                    timeout=30000,
                )
                await page.wait_for_timeout(3000)

                result = await page.evaluate("""
                    () => {
                        const pdfs = [];
                        document.querySelectorAll(
                            'a[href$=".pdf"], a[href*=".pdf?"]'
                        ).forEach(a => {
                            pdfs.push({name: a.innerText.trim() || 'PDF', url: a.href});
                        });
                        document.querySelectorAll('iframe[src*=".pdf"]').forEach(
                            iframe => { pdfs.push({name: 'PDF', url: iframe.src}); }
                        );
                        const article = document.querySelector(
                            'article, [class*="content"], [class*="article"], main'
                        );
                        const text = article ? article.innerText : document.body.innerText;
                        return {pdf_urls: pdfs, content: text};
                    }
                """)
                return result
            finally:
                await page.close()
        except Exception as exc:
            logger.debug(
                "fxbaogao: /view extraction failed for %s: %s", native_id, exc
            )
            return None

    async def close(self) -> None:
        """Clean up Playwright resources."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ═══════════════════════════════════════════════════════════════════════
    # Utility helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _cutoff_date(self) -> Optional[datetime]:
        if self.cfg.max_age_days is not None:
            return datetime.now(_SHANGHAI_TZ) - timedelta(days=self.cfg.max_age_days)
        return None

    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        if not value:
            return None
        clean = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y/%m/%d",
            "%Y年%m月%d日",
        ):
            try:
                return datetime.strptime(clean, fmt).replace(tzinfo=_SHANGHAI_TZ)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(clean)
        except ValueError:
            pass
        return None

    @classmethod
    def _parse_date_from_text(cls, text: str) -> datetime:
        """Find the first YYYY-MM-DD or YYYY年MM月DD日 pattern in *text*."""
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if m:
            try:
                return datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    tzinfo=_SHANGHAI_TZ,
                )
            except ValueError:
                pass

        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if m:
            try:
                return datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    tzinfo=_SHANGHAI_TZ,
                )
            except ValueError:
                pass

        return datetime.now(_SHANGHAI_TZ)
