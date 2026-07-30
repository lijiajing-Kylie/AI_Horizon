"""Playwright-based PDF resolution for WeChat MP (公众号) articles.

Opens each article in a headless browser and attempts, in order:

1. **阅读原文** — find the "read original" link at the bottom of the article,
   follow it, and intercept any PDF download.
2. **二维码** — detect QR-code images embedded in the article, decode the
   embedded URL, visit it, and attempt PDF download.

Both strategies are completely independent — failure in one does not affect
the other.  When neither yields a result, the report is returned unchanged
so the caller can decide how to handle it (e.g. log a warning or escalate
to a WeChatFerry-based fallback).

Usage::

    resolver = WxMpBrowserResolver(pdf_output_dir="data/reports_pdfs")
    report = await resolver.resolve(report)
    await resolver.close()

Batch-processing (reuses the browser across all calls)::

    reports = await resolver.resolve_batch(reports)
"""

from __future__ import annotations

import asyncio
import io
import logging
import re as _re
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from .models import Report
from .pdf import sanitize_filename

logger = logging.getLogger(__name__)

# ── Optional browser (Playwright) ──────────────────────────────────────
try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore[assignment]

# ── Optional QR-code decoding ──────────────────────────────────────────
try:
    from PIL import Image as _PILImage
    from pyzbar.pyzbar import decode as _pyzbar_decode

    _QR_AVAILABLE = True
except ImportError:
    _QR_AVAILABLE = False
    _PILImage = None  # type: ignore[assignment]
    _pyzbar_decode = None  # type: ignore[assignment]

# ═══════════════════════════════════════════════════════════════════════
#  WeChat keyword-gating detection (same logic as WxMpReportFetcher)
# ═══════════════════════════════════════════════════════════════════════

# Quoted keyword near reply verb: 回复「xxx」/ 关键词"xxx" etc.
_BROWSER_QUOTED_KW_RE = _re.compile(
    '(?:回复|输入|发送|关键词)\\s*[：:\\s]*'
    '(?:'
    '"([^"]{1,40})"'           # ASCII double
    '|'
    '「([^」]{1,40})」'
    '|'
    '『([^』]{1,40})』'
    '|'
    '“([^“]{1,40})”'
    "|"
    '‘([^‘]{1,40})’'
    ')'
)

# Unquoted: 回复xxx获取 + PDF
_BROWSER_UNQUOTED_KW_RE = _re.compile(
    '(?:回复|输入|发送)\\s*'
    '(?P<keyword>(?!关键词)[^，。、\\s"\'“”‘’'
    '「『」』]{2,30}?)'
    '\\s*(?:获取|下载|领取).*?(?:PDF|报告)'
)

# Gating context: 关注XX公众号
_BROWSER_GATE_CONTEXT_RE = _re.compile(
    '关注\\s*(?P<account>[^，。\\s]{2,20}?)\\s*(?:公众号|微信公众号|微信)'
)

# ═══════════════════════════════════════════════════════════════════════
#  Resolver
# ═══════════════════════════════════════════════════════════════════════


class WxMpBrowserResolver:
    """Playwright-based PDF resolver for WeChat MP articles.

    Manages a persistent Chromium context (``launch_persistent_context``) so
    that session state — including any manual login cookies — survives across
    the batch of reports within a single pipeline run.

    Call ``close()`` when done to release browser resources.
    """

    def __init__(
        self,
        pdf_output_dir: str,
        headless: bool = True,
        browser_profile_dir: str = "data/wxmp_browser_profile",
    ) -> None:
        self.pdf_output_dir = Path(pdf_output_dir)
        self._headless = headless
        self._browser_profile_dir = browser_profile_dir
        self._playwright: Optional[object] = None
        self._browser_context: Optional[object] = None

    # ── Public API ──────────────────────────────────────────────────────

    async def resolve(self, report: Report) -> Report:
        """Try both browser-based strategies for a single wxmp article.

        Returns the *report* unchanged if neither strategy succeeds (the
        caller should not treat this as an error).
        """
        if not _PLAYWRIGHT_AVAILABLE:
            logger.error(
                "Playwright not available — install with: uv sync --extra twitter"
            )
            return report

        # Already has a local PDF — nothing to do.
        if any(entry.get("local_path") for entry in report.pdf_urls):
            return report

        # For wxmp sources the AI relevance filter in `fetcher.py` already
        # handles content quality — every report reaching this point is worth
        # a browser attempt.  No additional keyword pre-filter here.
        ctx = await self._ensure_browser()
        article_page = await ctx.new_page()  # type: ignore[union-attr]

        try:
            # ── Load the WeChat article ────────────────────────────────
            try:
                await article_page.goto(
                    report.url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await article_page.wait_for_timeout(3000)
            except Exception as exc:
                logger.warning("Failed to load article %s: %s", report.id, exc)
                return report

            # ── Strategy 1: "阅读原文" link ─────────────────────────────
            read_url = await self._find_read_original_url(article_page)
            if read_url:
                logger.info("Found 阅读原文 link for %s: %s", report.id, read_url)

                # Use a fresh page so we don't navigate away from the article —
                # Strategy 2 (QR code) still needs it.
                dl_page = await ctx.new_page()  # type: ignore[union-attr]
                try:
                    pdf_urls = await self._download_from_url(
                        read_url, dl_page, report
                    )
                    if pdf_urls:
                        report.pdf_urls = pdf_urls
                        return report
                finally:
                    await dl_page.close()

            # ── Strategy 2: QR-code images ─────────────────────────────
            pdf_urls = await self._try_qr_code(article_page, report)
            if pdf_urls:
                report.pdf_urls = pdf_urls
                return report

            # ── Strategy 3: scan page text for WeChat keyword-gating ──
            # When neither direct download strategy works, check whether
            # the article says "关注公众号，回复关键词获取PDF".  If so,
            # add a wechat_keyword entry so the frontend can guide the
            # user instead of showing a broken download link.
            if not any(e.get("type") == "wechat_keyword" for e in report.pdf_urls):
                kw_info = await self._detect_wechat_keyword_on_page(article_page)
                if kw_info:
                    kw_info["url"] = report.url
                    report.pdf_urls = list(report.pdf_urls) + [kw_info]
                    logger.info(
                        "Detected WeChat keyword gate for %s: "
                        "account=%r keyword=%r",
                        report.id, kw_info.get("account", ""),
                        kw_info.get("keyword", ""),
                    )
                    return report

            logger.info("No PDF found for %s via any browser strategy", report.id)
            return report

        except Exception as exc:
            logger.warning("Browser resolution failed for %s: %s", report.id, exc)
            return report
        finally:
            await article_page.close()

    async def resolve_batch(self, reports: List[Report]) -> List[Report]:
        """Resolve PDFs for many reports, reusing the browser session."""
        if not reports:
            return reports

        resolved: List[Report] = []
        for i, report in enumerate(reports):
            logger.info(
                "[%d/%d] Resolving PDF for: %s",
                i + 1,
                len(reports),
                report.title,
            )
            resolved.append(await self.resolve(report))
        return resolved

    async def close(self) -> None:
        """Release browser resources.

        Idempotent — safe to call multiple times.
        """
        if self._browser_context is not None:
            try:
                await self._browser_context.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._browser_context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()  # type: ignore[union-attr]
            except Exception:
                pass
            self._playwright = None

    # ── Strategy 1: "阅读原文" ─────────────────────────────────────────

    @staticmethod
    async def _find_read_original_url(page) -> Optional[str]:
        """Locate the *href* of the "阅读原文" link inside a WeChat article.

        Returns ``None`` when no suitable link is found.
        """
        try:
            return await page.evaluate("""() => {
                const selectors = [
                    '#js_view_source a[href]',
                    '.rich_media_area_extra_inner a[href]',
                    'a.rich_media_tool_btn[href]',
                    '.rich_media_content a[href]',
                ];
                // Try common selectors first.
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.href && el.href !== '#') return el.href;
                }
                // Fallback: scan all links for 阅读原文 text.
                for (const a of document.querySelectorAll('a[href]')) {
                    const t = a.innerText.trim();
                    if (t === '阅读原文'  || t === '查看原文' ||
                        t === '阅读全文'  || t === 'Read more') {
                        if (a.href && a.href !== '#') return a.href;
                    }
                }
                return null;
            }""")
        except Exception as exc:
            logger.debug("Failed to find 阅读原文 link: %s", exc)
            return None

    # ── Strategy 2: QR code ────────────────────────────────────────────

    async def _try_qr_code(self, page, report: Report) -> Optional[List[dict]]:
        """Find QR-code images in the article body and decode them.

        Requires ``pyzbar`` + ``Pillow`` — silently skipped when unavailable.
        """
        if not _QR_AVAILABLE:
            logger.debug("QR-code decoding unavailable (install pyzbar + Pillow)")
            return None

        try:
            # Collect candidate image positions in the article content area.
            candidates: List[dict] = await page.evaluate("""() => {
                const results = [];
                const container = document.querySelector('#js_content')
                    || document.querySelector('.rich_media_content')
                    || document;
                const imgs = container.querySelectorAll('img');
                imgs.forEach((img, i) => {
                    const src = img.src || img.getAttribute('data-src') || '';
                    if (!src) return;
                    const r = img.getBoundingClientRect();
                    // QR codes tend to be roughly square, 100-600 px.
                    const minDim = Math.min(r.width, r.height);
                    const maxDim = Math.max(r.width, r.height);
                    if (minDim < 80 || maxDim > 700) return;
                    if (maxDim / minDim > 1.8) return;  // too oblong
                    results.push({index: i, src, width: r.width, height: r.height});
                });
                return results;
            }""")

            if not candidates:
                return None

            logger.debug(
                "Found %d candidate QR images in %s", len(candidates), report.id
            )

            container_sel = (
                "#js_content"
                if await page.query_selector("#js_content")
                else ".rich_media_content"
            )
            img_elements = page.locator(f"{container_sel} img")

            for c in candidates:
                try:
                    el = img_elements.nth(c["index"])
                    if not await el.is_visible():
                        continue

                    screenshot_bytes = await el.screenshot(timeout=10000)
                    if not screenshot_bytes or len(screenshot_bytes) < 200:
                        continue

                    img = _PILImage.open(io.BytesIO(screenshot_bytes))
                    decoded = _pyzbar_decode(img)
                    for code in decoded:
                        url = code.data.decode("utf-8").strip()
                        if not url.startswith(("http://", "https://")):
                            continue

                        logger.info(
                            "Decoded QR code URL for %s: %s", report.id, url
                        )

                        dl_page = await page.context.new_page()
                        try:
                            output_dir = (
                                self.pdf_output_dir
                                / report.source
                                / report.native_id
                            )
                            output_dir.mkdir(parents=True, exist_ok=True)
                            pdf_urls = await self._download_from_url(
                                url, dl_page, report, output_dir
                            )
                            if pdf_urls:
                                return pdf_urls
                        finally:
                            await dl_page.close()

                except Exception as exc:
                    logger.debug("Failed to decode QR image for %s: %s", report.id, exc)
                    continue

        except Exception as exc:
            logger.debug("QR-code strategy failed for %s: %s", report.id, exc)

        return None

    # ── Strategy 3: WeChat keyword gate detection ───────────────────────

    @staticmethod
    async def _detect_wechat_keyword_on_page(page) -> Optional[dict]:
        """Scan the rendered page text for "回复关键词获取PDF" patterns.

        Returns the same dict shape as ``_detect_wechat_keyword()`` in
        ``wxmp.py``, or ``None`` when no gating pattern is detected.
        """
        try:
            text = await page.evaluate("document.body.innerText")
        except Exception as exc:
            logger.info("Failed to get page text for keyword detection: %s", exc)
            return None

        if not text:
            logger.info("Empty page text for keyword detection")
            return None
        if len(text) < 15:
            logger.info(
                "Page text too short (%d chars) for keyword detection",
                len(text),
            )
            return None

        logger.info(
            "Scanning %d chars of page text for WeChat keyword gate …",
            len(text),
        )

        keyword: Optional[str] = None
        account: str = ""

        # Pass 1: quoted keyword near reply verb.
        m = _BROWSER_QUOTED_KW_RE.search(text)
        if m and m.lastindex is not None:
            kw = m.group(m.lastindex)
            if kw:
                keyword = kw.strip()
                logger.info(
                    "Browser found quoted keyword: %r", keyword,
                )
        else:
            # Pass 2: unquoted keyword + download verb.
            m = _BROWSER_UNQUOTED_KW_RE.search(text)
            if m:
                keyword = (m.group("keyword") or "").strip()
                logger.info(
                    "Browser found unquoted keyword: %r", keyword,
                )

        if not keyword:
            logger.info(
                "No keyword pattern found in browser page text "
                "(last 200 chars: %r)", text[-200:],
            )
            return None

        # Extract account from gating context.
        m = _BROWSER_GATE_CONTEXT_RE.search(text)
        if m:
            acct = (m.group("account") or "").strip()
            if acct:
                account = acct
                logger.info("Browser found gating account: %r", account)

        return {
            "name": f"微信关键词：{keyword}",
            "type": "wechat_keyword",
            "account": account,
            "keyword": keyword,
        }

    # ── PDF download helpers ────────────────────────────────────────────

    async def _download_from_url(
        self,
        url: str,
        page,
        report: Report,
        output_dir: Optional[Path] = None,
    ) -> List[dict]:
        """Follow *url* and attempt to obtain a PDF.

        Returns a ``[{name, url, local_path}, …]`` list (empty when nothing
        could be downloaded).
        """
        pdf_urls: List[dict] = []

        if output_dir is None:
            output_dir = self.pdf_output_dir / report.source / report.native_id
            output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_filename(report.title or report.native_id, max_len=80)

        # ── Path A: URL ends with ".pdf" — try HTTP directly ────────────
        if _re.search(r"\.pdf([?#]|$)", url):
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as hc:
                try:
                    resp = await hc.get(url)
                    saved = await self._save_if_valid_pdf(
                        resp, output_dir, safe_name, url, report, pdf_urls
                    )
                    if saved:
                        return pdf_urls
                except Exception as exc:
                    logger.debug("HTTP download failed for %s: %s", url, exc)

        # ── Path B: navigate a browser page and try to obtain a PDF ─────
        # Retry up to 2 times — some pages need a moment after load.
        for attempt in (1, 2):
            found = await self._browser_download_attempt(
                url, page, output_dir, safe_name, report, pdf_urls
            )
            if found:
                return pdf_urls

            # Second attempt: reload after a brief wait.
            await asyncio.sleep(1.0)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
            except Exception:
                break

        return pdf_urls

    async def _browser_download_attempt(
        self,
        url: str,
        page,
        output_dir: Path,
        safe_name: str,
        report: Report,
        pdf_urls: List[dict],
    ) -> bool:
        """One attempt: navigate to *url* and try every way to obtain a PDF."""
        import base64

        # Navigate
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception as exc:
            logger.debug("Browser nav failed for %s: %s", url, exc)
            return False

        current_url = page.url

        # ── B1: Check if current page IS a PDF ─────────────────────────
        if _re.search(r"\.pdf([?#]|$)", current_url):
            try:
                b64 = await page.evaluate("""async () => {
                    try {
                        const r = await fetch(window.location.href);
                        if (!r.ok) return null;
                        const buf = await r.arrayBuffer();
                        const u8 = new Uint8Array(buf);
                        let bin = '';
                        for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
                        return btoa(bin);
                    } catch(e) { return null; }
                }""")
                if b64:
                    raw = base64.b64decode(b64)
                    if raw.startswith(b"%PDF") and len(raw) > 1000:
                        out = output_dir / f"{safe_name}.pdf"
                        out.write_bytes(raw)
                        logger.info(
                            "PDF downloaded via browser fetch (%d bytes) -> %s",
                            len(raw), out,
                        )
                        pdf_urls.append(self._entry(safe_name, current_url, report))
                        return True
            except Exception as exc:
                logger.debug("Browser fetch failed: %s", exc)

        # ── B2: Try to click a download button ─────────────────────────
        try:
            async with page.expect_download(timeout=12000) as dl_info:
                for btn_text in ("下载", "下载报告", "下载 PDF", "保存", "Download"):
                    btn = page.locator(f'button:has-text("{btn_text}"), a:has-text("{btn_text}")').first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        break
            dl = await dl_info.value
            out = output_dir / f"{safe_name}.pdf"
            await dl.save_as(str(out))
            logger.info("PDF downloaded via click (%s) -> %s", dl.suggested_filename, out)
            pdf_urls.append(self._entry(safe_name, current_url, report))
            return True
        except Exception:
            pass

        # ── B3: Scan the rendered page for PDF links ──────────────────
        pdf_links: List[str] = await page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.href;
                if (/\\.pdf([?#]|$)/i.test(h)) links.push(h);
                else if (a.innerText.includes('下载') && h.startsWith('http')) links.push(h);
            });
            return [...new Set(links)];
        }""")

        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as hc:
            for link in pdf_links:
                try:
                    resp = await hc.get(link)
                    saved = await self._save_if_valid_pdf(
                        resp, output_dir, safe_name, link, report, pdf_urls
                    )
                    if saved:
                        return True
                except Exception:
                    continue

        return False

    # ── Misc helpers ────────────────────────────────────────────────────

    @staticmethod
    def _entry(name: str, url: str, report: Report) -> dict:
        """Build a ``pdf_urls`` entry dict with a serveable ``local_path``."""
        safe = sanitize_filename(name, max_len=80)
        return {
            "name": safe,
            "url": url,
            "local_path": (
                f"/api/reports/pdfs/{report.source}"
                f"/{report.native_id}/{safe}.pdf"
            ),
        }

    @staticmethod
    async def _save_if_valid_pdf(
        resp: httpx.Response,
        output_dir: Path,
        safe_name: str,
        source_url: str,
        report: Report,
        pdf_urls: List[dict],
    ) -> bool:
        """Save *resp* as a PDF if it looks valid.  Returns True on success."""
        if resp.status_code != 200:
            return False
        body = resp.content
        if len(body) < 1000:
            return False
        if not body.startswith(b"%PDF"):
            return False

        out = output_dir / f"{safe_name}.pdf"
        out.write_bytes(body)
        logger.info("PDF saved (%d bytes) from %s -> %s", len(body), source_url, out)
        safe = sanitize_filename(safe_name, max_len=80)
        pdf_urls.append({
            "name": safe,
            "url": source_url,
            "local_path": (
                f"/api/reports/pdfs/{report.source}"
                f"/{report.native_id}/{safe}.pdf"
            ),
        })
        return True

    async def _ensure_browser(self):
        """Get or create a persistent Chromium context."""
        if self._browser_context is not None:
            return self._browser_context

        pw = await async_playwright().start()
        self._playwright = pw

        profile_dir = Path(self._browser_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._browser_context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=self._headless,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        logger.info(
            "WxMp browser ready (profile: %s, headless=%s)",
            profile_dir,
            self._headless,
        )
        return self._browser_context
