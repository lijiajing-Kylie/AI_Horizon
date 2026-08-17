"""Playwright-based PDF resolution for WeChat MP (公众号) articles.

Opens each article in a headless browser and decodes the footer QR-code
(report downloads are exposed this way, not via a "阅读原文" link):

1. scroll to the article footer — this triggers WeChat's lazy-loaded
   images (``data-src`` → ``src``);
2. locate the QR image by the CTA text anchor ("扫描二维码，获完整报告"):
   a bare ``<img>`` (or a single-image block) adjacent to that text;
3. decode it (pyzbar) and follow the embedded URL, extracting the real
   PDF from the target page (which may be a preview page, e.g. 草料
   ``view.html?url=<pdf>``) and saving it to ``pdf_output_dir``.

When nothing yields a result, the report is returned unchanged with an
empty ``pdf_urls`` list; the caller can decide how to handle it.  No
WeChat keyword-gating hint is added — the frontend shows only the
original article link in that case.

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
import os
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
    # macOS Homebrew 的 zbar 装在 /opt/homebrew/lib，不在 ctypes.util.find_library
    # 的默认搜索路径（Python 3.14 探测不到）。进程内把它加进 DYLD_LIBRARY_PATH
    # 后重试一次，避免二维码策略（删除阅读原文后的唯一策略）静默失效。
    _zbar_lib_dirs = [d for d in ("/opt/homebrew/lib", "/usr/local/lib")
                      if os.path.isdir(d)]
    if _zbar_lib_dirs:
        _cur = os.environ.get("DYLD_LIBRARY_PATH", "")
        os.environ["DYLD_LIBRARY_PATH"] = ":".join(
            dict.fromkeys(_zbar_lib_dirs + ([_cur] if _cur else []))
        )
        try:
            from PIL import Image as _PILImage
            from pyzbar.pyzbar import decode as _pyzbar_decode

            _QR_AVAILABLE = True
        except ImportError:
            _QR_AVAILABLE = False
            _PILImage = None  # type: ignore[assignment]
            _pyzbar_decode = None  # type: ignore[assignment]
    else:
        _QR_AVAILABLE = False
        _PILImage = None  # type: ignore[assignment]
        _pyzbar_decode = None  # type: ignore[assignment]

# ── Footer QR-code CTA anchors ─────────────────────────────────────────
# 报告文章文末通常有「扫描二维码，获完整报告」这类提示 + 相邻的二维码图。
# 报告专属 marker 优先于「关注公众号」，避免先撞上运营二维码。
_QR_CTA_MARKERS = [
    "扫描二维码", "长按识别二维码", "识别二维码", "扫码获取", "扫码下载",
    "扫码阅读", "扫码查看", "获取完整报告", "获取全文报告", "获完整报告",
]
_QR_CTA_MARKERS_SECONDARY = ["关注公众号", "关注我们"]

# 尾部扫描的块级节点上限：只检查文章最后 30 个块，避免正文中段偶然出现
# 运营词时误定位（与 src/scrapers/wxmp.py 的策略一致）。
_QR_FOOTER_SCAN_BLOCKS = 30
_QR_FOOTER_BLOCK_TAGS = (
    "p", "div", "section", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "figure", "table",
)
# 兜底候选取用上限：无 CTA 锚点时只试文末最后几张近似正方形的图。
_QR_FALLBACK_CANDIDATES = 6
_QR_MIN_DIM = 80
_QR_MAX_DIM = 700
_QR_ASPECT_MAX = 1.8


def _qr_cta_marker_hit(text: str) -> Optional[str]:
    """文本命中哪个 CTA marker（优先报告专属，其次关注类）。"""
    for marker in (*_QR_CTA_MARKERS, *_QR_CTA_MARKERS_SECONDARY):
        if marker in text:
            return marker
    return None


def _qr_leaf_footer_blocks(container) -> list:
    """收集不含块级后代的块级元素（真正承载内容的 leaf 块）。"""
    return [
        el for el in container.find_all(_QR_FOOTER_BLOCK_TAGS)
        if el.find(_QR_FOOTER_BLOCK_TAGS) is None
    ]


def _qr_img_from_block(tag) -> Optional[object]:
    """tag 是裸 ``<img>``、或「无文字且仅含 1 张 img」的块 → 返回该 img。

    穿透 ``<a>`` 包裹（二维码链接常见形态）。
    """
    if tag is None:
        return None
    if tag.name == "img":
        return tag
    if tag.get_text("", strip=True):
        return None
    imgs = tag.find_all("img")
    return imgs[0] if len(imgs) == 1 else None


def _qr_adjacent_img(blk) -> Optional[object]:
    """取 CTA 文案块前/后一个相邻兄弟里的二维码图（覆盖图片在文案前/后两种变体）。"""
    for adj in (blk.find_previous_sibling(), blk.find_next_sibling()):
        img = _qr_img_from_block(adj)
        if img is not None:
            return img
    return None


def _qr_img_src(img) -> Optional[str]:
    """返回 img 的可访问 URL（src 优先，回退 data-src）；非 http 占位返回 None。"""
    if img is None:
        return None
    src = img.get("src") or img.get("data-src") or ""
    return src if src.startswith("http") else None


def _qr_img_squareish(img) -> bool:
    """从内联 style ``width/height: Npx`` 或 width 属性近似判断是否接近正方形。

    纯 HTML 拿不到渲染尺寸，只能按 style 里的宽高近似；任一维度缺失时不
    否决（真实尺寸由页面 CSS 决定，例如微信图 ``height: auto``）。
    """
    style = img.get("style") or ""

    def _px(prop: str) -> Optional[float]:
        m = _re.search(rf"{prop}\s*:\s*(\d+(?:\.\d+)?)px", style)
        return float(m.group(1)) if m else None

    w = _px("width")
    h = _px("height")
    if w is None:
        attr = (img.get("width") or "").strip()
        try:
            w = float(attr)
        except (TypeError, ValueError):
            w = None
    if w is None:
        return True  # 未知宽度不否决
    if not (_QR_MIN_DIM <= w <= _QR_MAX_DIM):
        return False
    if h is not None and max(w, h) / max(min(w, h), 1) > _QR_ASPECT_MAX:
        return False  # 长宽比过大 → 非二维码
    return True


def _footer_qr_candidate_urls(html: str) -> List[str]:
    """从渲染后的文章 HTML 里定位文末二维码图片的 URL（src/data-src）。

    返回候选 URL 列表：
    1. **主路径（CTA 锚点）**：最后 ``_QR_FOOTER_SCAN_BLOCKS`` 个 leaf 块里找
       命中 ``_QR_CTA_MARKERS*`` 的块，取其前/后相邻兄弟里的单图 → src。
    2. **兜底（文末正方形扫描）**：无 CTA 命中时，收集全部 img，正方形过滤，
       只取文档位置最后的 ``_QR_FALLBACK_CANDIDATES`` 张。

    过滤 ``data:`` 占位图与空 URL，去重。纯函数，便于单测。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#js_content") or soup

    # 主路径：CTA 锚点（收集所有命中的相邻图，逐个试解码）
    tail = _qr_leaf_footer_blocks(content)[-_QR_FOOTER_SCAN_BLOCKS:]
    cta_urls: List[str] = []
    for blk in tail:
        text = blk.get_text(" ", strip=True)
        if not text or _qr_cta_marker_hit(text) is None:
            continue
        img = _qr_adjacent_img(blk)
        src = _qr_img_src(img)
        if src:
            cta_urls.append(src)
    if cta_urls:
        return list(dict.fromkeys(cta_urls))

    # 兜底：文末近似正方形图
    urls: List[str] = []
    for img in content.find_all("img"):
        src = _qr_img_src(img)
        if not src:
            continue
        if not _qr_img_squareish(img):
            continue
        urls.append(src)
    return list(dict.fromkeys(urls))[-_QR_FALLBACK_CANDIDATES:]

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
        """Decode the footer QR-code of a single wxmp article and fetch its PDF.

        Returns the *report* unchanged if no PDF is obtainable (the caller
        should not treat this as an error).
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

            # ── 唯一策略：解码文末二维码（CTA 锚点定位）────────────────
            pdf_urls = await self._try_qr_code(article_page, report)
            if pdf_urls:
                report.pdf_urls = pdf_urls
                return report

            logger.info("No PDF found for %s via browser QR strategy", report.id)
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

    # ── QR code 策略（文末 CTA 锚点定位）─────────────────────────────

    async def _try_qr_code(self, page, report: Report) -> Optional[List[dict]]:
        """滚动到文末 → 定位二维码图（CTA 锚点 / 兜底正方形）→ 解码 → 下载。

        Requires ``pyzbar`` + ``Pillow`` + 系统 zbar 库。
        """
        if not _QR_AVAILABLE:
            logger.warning(
                "QR-code decoding unavailable — install pyzbar + zbar "
                "(macOS: brew install zbar; Debian: apt-get install libzbar0)"
            )
            return None

        try:
            await self._scroll_to_footer(page)
            html = await page.content()
            candidates = _footer_qr_candidate_urls(html)
            if not candidates:
                logger.debug("No footer QR candidates in %s", report.id)
                return None
            logger.debug(
                "Found %d QR candidates in %s: %s",
                len(candidates), report.id, candidates,
            )

            for src in candidates:
                try:
                    pdf_urls = await self._decode_qr_src(page, src, report)
                    if pdf_urls:
                        return pdf_urls
                except Exception as exc:
                    logger.debug("Failed to decode QR candidate %s: %s", src, exc)
                    continue

        except Exception as exc:
            logger.debug("QR-code strategy failed for %s: %s", report.id, exc)

        return None

    async def _scroll_to_footer(self, page) -> None:
        """滚动到底部触发微信图片懒加载（``data-src`` → ``src``）。

        ``#js_content`` 初始 ``visibility:hidden``，滚动会同时触发可见化。
        采用「跳底 → 回拉半屏 → 再跳底」确保页脚贴近视口。
        """
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
            await page.evaluate(
                "window.scrollTo(0, "
                "Math.max(0, document.body.scrollHeight - window.innerHeight))"
            )
            await page.wait_for_timeout(1200)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
        except Exception as exc:
            logger.debug("Scroll-to-footer failed: %s", exc)

    async def _find_img_by_src(self, page, src: str):
        """按 src 前缀在 ``#js_content`` 里定位 img，返回 locator 或 None。"""
        idx = await page.evaluate("""(prefix) => {
            const imgs = document.querySelectorAll('#js_content img');
            for (let i = 0; i < imgs.length; i++) {
                const s = imgs[i].currentSrc || imgs[i].src
                    || imgs[i].getAttribute('data-src') || '';
                if (s.startsWith(prefix)) return i;
            }
            return -1;
        }""", src[:60])
        if idx < 0:
            return None
        return page.locator("#js_content img").nth(idx)

    async def _decode_qr_src(
        self, page, src: str, report: Report
    ) -> Optional[List[dict]]:
        """对候选二维码图：优先截图解码；失败则 httpx 直抓 PNG 解码。"""
        el = await self._find_img_by_src(page, src)
        if el is not None:
            try:
                if await el.is_visible():
                    screenshot_bytes = await el.screenshot(timeout=10000)
                    if screenshot_bytes and len(screenshot_bytes) >= 200:
                        img = _PILImage.open(io.BytesIO(screenshot_bytes))
                        url = self._qr_decode_first(img)
                        if url:
                            logger.info(
                                "Decoded QR code URL for %s: %s", report.id, url
                            )
                            return await self._download_decoded_url(
                                page, url, report
                            )
            except Exception as exc:
                logger.debug("Screenshot decode failed for %s: %s", report.id, exc)

        # 兜底：httpx 直抓 PNG（带微信 Referer 绕过防盗链）再解码。
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as hc:
                resp = await hc.get(
                    src,
                    headers={
                        "Referer": "https://mp.weixin.qq.com/",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
            if resp.status_code == 200 and resp.content[:4] == b"\x89PNG":
                img = _PILImage.open(io.BytesIO(resp.content))
                url = self._qr_decode_first(img)
                if url:
                    logger.info(
                        "Decoded QR code URL for %s (via PNG fetch): %s",
                        report.id, url,
                    )
                    return await self._download_decoded_url(page, url, report)
        except Exception as exc:
            logger.debug("PNG-fetch decode failed for %s: %s", report.id, exc)

        return None

    @staticmethod
    def _qr_decode_first(img) -> Optional[str]:
        """pyzbar 解码图片，返回第一个 http(s) URL；无则 None。"""
        for code in _pyzbar_decode(img):
            url = code.data.decode("utf-8").strip()
            if url.startswith(("http://", "https://")):
                return url
        return None

    async def _download_decoded_url(
        self, page, url: str, report: Report
    ) -> Optional[List[dict]]:
        """解码出的 URL 交给下载逻辑；新开页面避免污染文章页。"""
        dl_page = await page.context.new_page()
        try:
            output_dir = self.pdf_output_dir / report.source / report.native_id
            output_dir.mkdir(parents=True, exist_ok=True)
            return await self._download_from_url(url, dl_page, report, output_dir)
        finally:
            await dl_page.close()

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

        # ── B0: URL query 里内嵌的 .pdf（预览页模式，如 草料 view.html?url=<pdf>）──
        pdf_from_query = self._extract_pdf_from_url_query(current_url)
        if pdf_from_query:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as hc:
                try:
                    resp = await hc.get(pdf_from_query)
                    saved = await self._save_if_valid_pdf(
                        resp, output_dir, safe_name,
                        pdf_from_query, report, pdf_urls,
                    )
                    if saved:
                        return True
                except Exception as exc:
                    logger.debug("Query-PDF download failed: %s", exc)

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

        # ── B2: Click a download / 查看 button ─────────────────────────
        # 「查看」按钮（草料预览页等）不触发下载，而是跳转到带真实 PDF 的
        # 预览页（view.html?url=<pdf>）——点击后从新 URL 提取。
        for btn_text in ("下载", "下载报告", "下载 PDF", "保存", "Download", "查看"):
            try:
                btn = page.locator(
                    f'button:has-text("{btn_text}"), a:has-text("{btn_text}")'
                ).first
                if not await btn.is_visible(timeout=2000):
                    continue
            except Exception:
                continue
            # 尝试触发浏览器下载
            try:
                async with page.expect_download(timeout=8000) as dl_info:
                    await btn.click()
                dl = await dl_info.value
                out = output_dir / f"{safe_name}.pdf"
                await dl.save_as(str(out))
                logger.info(
                    "PDF downloaded via click (%s) -> %s",
                    dl.suggested_filename, out,
                )
                pdf_urls.append(self._entry(safe_name, page.url, report))
                return True
            except Exception:
                pass  # 不是下载 → 可能是页面跳转，下面从新 URL 提取
            # 点击导致导航：轮询等待 URL 里出现内嵌 .pdf（如草料 view.html?url=<pdf>）
            try:
                await page.wait_for_function(
                    "() => /[?&](url|src|pdf|file)=[^&]*\\.pdf/i.test(location.href)",
                    timeout=10000,
                )
            except Exception:
                pass  # 未跳转或跳转不带 pdf → 交给下一个按钮 / 下一轮
            pdf_from_query = self._extract_pdf_from_url_query(page.url)
            if pdf_from_query:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=30.0
                ) as hc:
                    try:
                        resp = await hc.get(pdf_from_query)
                        saved = await self._save_if_valid_pdf(
                            resp, output_dir, safe_name,
                            pdf_from_query, report, pdf_urls,
                        )
                        if saved:
                            return True
                    except Exception as exc:
                        logger.debug("Query-PDF download failed: %s", exc)

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
    def _extract_pdf_from_url_query(url: str) -> Optional[str]:
        """从 URL query 参数里提取内嵌的 .pdf 地址。

        覆盖「预览页」模式：解码出的短链接跳转后形如
        ``...view.html?url=https%3A%2F%2F...pdf&filename=...``，
        真实 PDF 藏在 ``url``/``src`` 等参数里（URL-encoded）。
        """
        from urllib.parse import parse_qs, unquote, urlparse

        parsed = urlparse(url)
        if not parsed.query:
            return None
        try:
            qs = parse_qs(parsed.query)
        except Exception:
            qs = {}
        for key in ("url", "src", "pdf", "file"):
            for val in qs.get(key) or []:
                if _re.search(r"\.pdf([?#]|$)", val, _re.IGNORECASE):
                    return val
        # 兜底：直接扫描 query 里的 .pdf 形态（某些站用裸参数）
        m = _re.search(r"([^?&=]+\.pdf[^&]*)", parsed.query, _re.IGNORECASE)
        if m:
            return unquote(m.group(1))
        return None

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
