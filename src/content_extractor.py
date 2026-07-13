"""Full article text and image extraction via trafilatura.

Fetches the original URL for a news item and extracts the main article
content using trafilatura's readability-based algorithm, plus any images
found within that main content (cover image + inline images with
captions). Skips URLs that are not article-like (social media, code repos,
images, etc.).
"""

from __future__ import annotations

import asyncio
import html as html_module
import json
import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
import nh3
import trafilatura
from bs4 import BeautifulSoup
from rich.console import Console
from trafilatura.metadata import extract_metadata

from .models import ContentItem, sub_source_label

logger = logging.getLogger(__name__)

# Domains whose content is inherently non-article — skip extraction entirely.
_SKIP_DOMAINS: set[str] = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "x.com",
    "twitter.com",
    "t.me",
    "telegram.org",
    "reddit.com",
    "redd.it",
    "news.ycombinator.com",
    "lobste.rs",
    "producthunt.com",
    "youtube.com",
    "youtu.be",
    "discord.com",
    "discord.gg",
}

# File extensions that are never HTML articles.
_SKIP_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".webm",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
}

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HorizonBot/1.0; +https://github.com/kylie/horizon)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en,zh;q=0.9",
}

_MIN_CONTENT_LENGTH = 200  # fewer chars than this → treat as failed extraction
_MAX_IMAGES = 20  # cap the inline image list for image-heavy pages (galleries, etc.)

# Bumped when extraction logic changes materially, so persisted items can be
# identified as having been extracted by an older algorithm version.
EXTRACTOR_VERSION = "1"


@dataclass
class ExtractedArticle:
    """Result of a successful full-content extraction.

    ``text`` is trafilatura's plain-text output only — never HTML, never
    boilerplate-cleaned. It is the canonical source for ``ContentItem.raw_content``.
    """

    text: str
    cover_image: Optional[str] = None
    images: List[Dict[str, Any]] = field(default_factory=list)
    raw_html: Optional[str] = None  # structured main-content HTML, unsanitized
    display_html: Optional[str] = None  # raw_html after nh3 whitelist sanitize
    http_status: Optional[int] = None
    final_url: Optional[str] = None  # response.url after redirects
    extractor_version: str = EXTRACTOR_VERSION


def _should_skip(url: str) -> Optional[str]:
    """Return a skip reason for URLs that are unlikely to contain article text, or None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "url_parse_error"

    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    # Check domain blocklist
    for domain in _SKIP_DOMAINS:
        if domain in hostname:
            return f"skip_domain:{domain}"

    # Check file extension
    for ext in _SKIP_EXTENSIONS:
        if path.endswith(ext):
            return f"skip_extension:{ext}"

    return None


# ── boilerplate container removal ────────────────────────────────────────
#
# Ad/subscribe/newsletter/hiring blocks are usually their own dedicated HTML
# container, not text woven into the article — so they're removed as whole
# DOM nodes *before* trafilatura ever sees them, rather than by pattern-
# matching extracted text afterwards (which risks nuking an entire
# single-paragraph article that happens to contain one of these words).

_BOILERPLATE_CONTAINER_TAGS = ("aside", "footer")

_BOILERPLATE_CLASS_KEYWORDS = (
    "subscribe", "newsletter", "ad", "promo", "paywall",
    "signup", "join-us", "careers",
)
# Token-boundary match (hyphen/underscore/space/start/end) so e.g. "load" or
# "header" never match the bare "ad" keyword.
_BOILERPLATE_CLASS_RE = re.compile(
    r"(?:^|[-_\s])(" + "|".join(re.escape(k) for k in _BOILERPLATE_CLASS_KEYWORDS) + r")(?:[-_\s]|$)",
    re.IGNORECASE,
)


def _strip_boilerplate_containers(html: str) -> str:
    """Remove ad/subscribe/newsletter/hiring HTML containers before extraction.

    Decomposes ``<aside>``/``<footer>`` elements and any element whose
    ``class``/``id`` matches a boilerplate keyword (subscribe, newsletter,
    ad, promo, paywall, signup, join-us, careers). Returns the original
    HTML unchanged on any parse error.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.debug("boilerplate container strip parse error: %s", exc)
        return html

    try:
        for tag_name in _BOILERPLATE_CONTAINER_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for tag in soup.find_all(True):
            if tag.decomposed:
                continue
            class_attr = " ".join(tag.get("class") or [])
            id_attr = tag.get("id") or ""
            haystack = f"{class_attr} {id_attr}".strip()
            if haystack and _BOILERPLATE_CLASS_RE.search(haystack):
                tag.decompose()
    except Exception as exc:
        logger.debug("boilerplate container strip error: %s", exc)
        return html

    return str(soup)


# ── sentence-level CTA cleaning ──────────────────────────────────────────
#
# Once obvious ad/subscribe/hiring *containers* are gone (above), a CTA can
# still be one sentence tacked onto an otherwise-real paragraph (e.g. "...
# reasons explained above. Subscribe to our newsletter for more."). This
# drops only the offending sentence, never the whole paragraph/line — a
# single-paragraph article with a trailing CTA keeps its real content.

_CTA_KEYWORDS = (
    "订阅", "会员", "newsletter", "ad-free", "立即订阅", "注册", "联系我们",
    "we're hiring", "we are hiring", "apply", "join our team",
    # English equivalents of 订阅/会员 for English-language articles.
    "subscribe", "sign up", "sign-up",
)
_CTA_SENTENCE_RE = re.compile(
    "|".join(re.escape(k) for k in _CTA_KEYWORDS), re.IGNORECASE
)
# Splits on a sentence-ending punctuation mark (CJK or Latin), keeping the
# rest of the string attached to the next sentence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*")

# Over-cleaning guard, shared by the structured-HTML and plain-text
# pipelines: if cleaning removes this much of the article, it's more likely
# a false-positive CTA match ate real content than that the article really
# was mostly boilerplate — bail out to a lighter-touch fallback instead.
_OVERCLEAN_MIN_RATIO = 0.3
_OVERCLEAN_MIN_CHARS = 200


def _split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    return [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _strip_cta_sentences(text: str) -> tuple[str, bool]:
    """Drop only the sentence(s) containing a CTA signal from ``text``.

    Returns ``(cleaned_text, changed)`` — ``changed`` is ``True`` iff at
    least one sentence was removed, so callers can tell "nothing to do"
    apart from "everything was CTA" (cleaned_text == "").
    """
    sentences = _split_sentences(text)
    kept = [s for s in sentences if not _CTA_SENTENCE_RE.search(s)]
    return " ".join(kept).strip(), len(kept) != len(sentences)


# ── image extraction ─────────────────────────────────────────────────────


def _resolve_url(base_url: str, src: Optional[str]) -> Optional[str]:
    """Resolve a possibly-relative image src against the page URL."""
    if not src or not src.strip():
        return None
    try:
        return urljoin(base_url, src.strip())
    except Exception:
        return None


def _extract_figcaptions(html: str, base_url: str) -> Dict[str, str]:
    """Map absolute image URL -> caption text, from ``<figure><figcaption>`` pairs."""
    captions: Dict[str, str] = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return captions

    for figure in soup.find_all("figure"):
        figcaption = figure.find("figcaption")
        if not figcaption:
            continue
        caption_text = figcaption.get_text(strip=True)
        if not caption_text:
            continue
        for img in figure.find_all("img"):
            src = img.get("src") or img.get("data-src")
            resolved = _resolve_url(base_url, src)
            if resolved:
                captions[resolved] = caption_text

    return captions


_ICON_FILENAME_MARKERS = (
    "icon", "logo", "sprite", "badge", "avatar", "pixel", "spacer", "tracking",
)
# Wikimedia-style thumbnail filenames embed the rendered width, e.g.
# "20px-Some-icon.svg.png" — a tiny rendered width is a strong icon signal.
_THUMB_WIDTH_RE = re.compile(r"^(\d+)px-")
_MIN_COVER_IMAGE_WIDTH = 100


def _looks_like_icon(image_url: str) -> bool:
    """Heuristic for images that make poor cover images (icons/logos/pixels)."""
    path = urlparse(image_url).path.lower()
    if path.endswith(".svg") or ".svg." in path:
        return True
    filename = path.rsplit("/", 1)[-1]
    if any(marker in filename for marker in _ICON_FILENAME_MARKERS):
        return True
    width_match = _THUMB_WIDTH_RE.match(filename)
    if width_match and int(width_match.group(1)) < _MIN_COVER_IMAGE_WIDTH:
        return True
    return False


def _extract_images(html: str, url: str) -> tuple[Optional[str], List[Dict[str, Any]]]:
    """Extract a cover image and the list of in-article images.

    The cover image is taken from ``og:image``/``twitter:image`` metadata
    when present, falling back to the first in-article image. In-article
    images are read from trafilatura's main-content XML tree (so nav/ad/
    footer images are already excluded), enriched with captions pulled from
    ``<figure>/<figcaption>`` pairs in the raw HTML.
    """
    images: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    try:
        captions = _extract_figcaptions(html, url)
    except Exception:
        captions = {}

    try:
        xml = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_images=True,
            output_format="xml",
            favor_precision=True,
        )
        if xml:
            root = ElementTree.fromstring(xml)
            for graphic in root.iter("graphic"):
                resolved = _resolve_url(url, graphic.get("src"))
                if not resolved or resolved in seen_urls:
                    continue
                seen_urls.add(resolved)
                if len(images) >= _MAX_IMAGES:
                    continue
                images.append({
                    "url": resolved,
                    "alt": graphic.get("alt") or "",
                    "caption": captions.get(resolved, ""),
                    "source": urlparse(resolved).hostname or "",
                })
    except Exception as exc:
        logger.debug("image extraction error for %s: %s", url, exc)

    cover_image: Optional[str] = None
    try:
        meta = extract_metadata(html, default_url=url)
        if meta and meta.image:
            cover_image = _resolve_url(url, meta.image)
    except Exception as exc:
        logger.debug("cover image metadata error for %s: %s", url, exc)

    if not cover_image:
        # Fall back to the first in-content image that doesn't look like an
        # icon/logo/tracking pixel — those make poor full-width cover images.
        cover_image = next(
            (img["url"] for img in images if not _looks_like_icon(img["url"])),
            None,
        )

    return cover_image, images


# ── structured HTML extraction (raw_html / display_html) ────────────────
#
# ``raw_html`` preserves paragraph/heading/list/quote structure plus inline
# images with captions, built by walking trafilatura's XML content tree (the
# same tree ``_extract_images`` already parses) so image position in the
# generated markup matches the source article's document order. It mirrors
# ``raw_content`` in spirit — untouched structure, kept for traceability —
# while ``display_html`` is the nh3-sanitized, render-safe version, mirroring
# ``clean_content``.

_ALLOWED_HTML_TAGS = {
    "h2", "h3", "h4", "p", "figure", "img", "figcaption",
    "blockquote", "ul", "ol", "li", "strong", "em", "a", "br",
}
_ALLOWED_HTML_ATTRIBUTES = {
    "img": {"src", "alt"},
    "a": {"href"},
}
_ALLOWED_URL_SCHEMES = {"http", "https"}

# XML <head rend="h1|h2|h3|h4"> -> HTML heading tag. Shifted down one level
# (h1 -> h2) since the item title already renders as the page's own h1.
_HEAD_RANK_TO_TAG = {"h1": "h2", "h2": "h3", "h3": "h4", "h4": "h4"}


def sanitize_article_html(raw_html: Optional[str]) -> str:
    """Whitelist-sanitize a structured article HTML fragment for safe rendering.

    Strips everything outside a small block/inline tag whitelist (no
    ``script``/``style``/event handlers/inline styles), and only allows
    ``http``/``https`` URLs in ``href``/``src`` — defense in depth on top of
    the fact that ``_build_structured_html`` already escapes all text nodes
    and only emits ``<a>`` for http(s) targets. Never raises; returns ``""``
    for empty input.

    Args:
        raw_html: Untrusted HTML fragment (typically ``ExtractedArticle.raw_html``).

    Returns:
        Sanitized HTML safe to render via e.g. React's ``dangerouslySetInnerHTML``.
    """
    if not raw_html or not raw_html.strip():
        return ""
    try:
        return nh3.clean(
            raw_html,
            tags=_ALLOWED_HTML_TAGS,
            attributes=_ALLOWED_HTML_ATTRIBUTES,
            url_schemes=_ALLOWED_URL_SCHEMES,
            link_rel="noopener noreferrer nofollow",
        )
    except Exception as exc:
        logger.debug("html sanitize error: %s", exc)
        return ""


def _render_inline_content(el: ElementTree.Element) -> str:
    """Render a ``p``/``quote``/``item``/``head`` element's inner HTML.

    Escapes all text nodes and maps trafilatura's inline XML tags to HTML:
    ``hi rend="#b"`` -> ``strong``, ``hi rend="#i"`` -> ``em``. ``ref``
    (in-body links) is rendered as plain text only — the detail page keeps
    exactly one outbound link ("查看原文"); links woven into the article
    body are never made clickable.
    """
    parts = [html_module.escape(el.text or "")]
    for child in el:
        inner = _render_inline_content(child)
        if child.tag == "hi":
            rend = child.get("rend") or ""
            if "#b" in rend:
                parts.append(f"<strong>{inner}</strong>")
            elif "#i" in rend:
                parts.append(f"<em>{inner}</em>")
            else:
                parts.append(inner)
        else:
            parts.append(inner)
        parts.append(html_module.escape(child.tail or ""))
    return "".join(parts)


def _render_cta_filtered(el: ElementTree.Element) -> str:
    """Render a block element's inner HTML, dropping only CTA sentences.

    When no sentence in the block matches a CTA signal, formatting
    (bold/italic) is preserved exactly via ``_render_inline_content``. When
    some sentences are CTA, the block degrades to plain escaped text with
    just those sentences removed — real content in the rest of the block
    (and the rest of the article) survives even when a CTA is tacked onto
    an otherwise-genuine paragraph. Returns ``""`` (caller drops the block)
    only when *every* sentence in the block is a CTA signal.
    """
    block_text = "".join(el.itertext())
    cleaned_text, changed = _strip_cta_sentences(block_text)
    if not changed:
        return _render_inline_content(el)
    return html_module.escape(cleaned_text)


def _build_structured_html(
    root: ElementTree.Element, url: str, figcaptions: Dict[str, str]
) -> str:
    """Walk trafilatura's XML content tree and render it to an HTML fragment.

    Preserves document order for headings/paragraphs/quotes/lists/images so
    an inline image renders where it actually appeared in the source
    article, with its ``<figure>/<figcaption>`` caption attached — instead
    of being extracted separately and appended after the text.
    """
    main = root.find("main")
    if main is None:
        return ""

    blocks: List[str] = []
    for el in main:
        tag = el.tag
        if tag == "head":
            rend = el.get("rend") or "h1"
            html_tag = _HEAD_RANK_TO_TAG.get(rend, "h4")
            text = _render_inline_content(el)
            if text.strip():
                blocks.append(f"<{html_tag}>{text}</{html_tag}>")
        elif tag == "p":
            text = _render_cta_filtered(el)
            if text.strip():
                blocks.append(f"<p>{text}</p>")
        elif tag == "quote":
            text = _render_cta_filtered(el)
            if text.strip():
                blocks.append(f"<blockquote>{text}</blockquote>")
        elif tag == "list":
            list_tag = "ol" if (el.get("rend") or "ul") == "ol" else "ul"
            items = []
            for item_el in el.findall("item"):
                item_text = _render_cta_filtered(item_el)
                if item_text.strip():
                    items.append(f"<li>{item_text}</li>")
            if items:
                blocks.append(f"<{list_tag}>{''.join(items)}</{list_tag}>")
        elif tag == "graphic":
            resolved = _resolve_url(url, el.get("src"))
            if not resolved:
                continue
            alt = html_module.escape(el.get("alt") or "", quote=True)
            src = html_module.escape(resolved, quote=True)
            img_html = f'<img src="{src}" alt="{alt}">'
            caption = figcaptions.get(resolved, "")
            if caption:
                blocks.append(f"<figure>{img_html}<figcaption>{html_module.escape(caption)}</figcaption></figure>")
            else:
                blocks.append(f"<figure>{img_html}</figure>")
        # Unrecognized tags (e.g. tables, since include_tables=False is passed
        # when generating this tree) are silently skipped.

    return "".join(blocks)


def _extract_structured_html(html: str, url: str) -> tuple[Optional[str], Optional[str]]:
    """Extract structured ``(raw_html, display_html)`` for an article page.

    Returns ``(None, None)`` when trafilatura can't find a main content tree
    — callers should fall back to the plain-text ``content`` field.
    """
    try:
        xml = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_images=True,
            include_formatting=True,
            include_links=True,
            include_tables=False,
            output_format="xml",
            favor_precision=True,
        )
        if not xml:
            return None, None
        root = ElementTree.fromstring(xml)
    except Exception as exc:
        logger.debug("structured html extraction error for %s: %s", url, exc)
        return None, None

    try:
        figcaptions = _extract_figcaptions(html, url)
    except Exception:
        figcaptions = {}

    # Baseline for the over-cleaning guard below: main-content text length
    # *before* sentence-level CTA filtering (container-level removal has
    # already happened upstream, in extract_full_content, so this doesn't
    # penalize legitimate ad/subscribe container removal — only excessive
    # sentence-level cleaning).
    main = root.find("main")
    original_len = len("".join(main.itertext()).strip()) if main is not None else 0

    raw_html = _build_structured_html(root, url, figcaptions)
    if not raw_html.strip():
        return None, None

    cleaned_len = len(re.sub(r"<[^>]+>", "", raw_html))
    if original_len and (
        cleaned_len < original_len * _OVERCLEAN_MIN_RATIO or cleaned_len < _OVERCLEAN_MIN_CHARS
    ):
        # Cleaning removed too much of the article — don't ship a gutted
        # structured body; let the caller fall back to the plain-text
        # clean_content pipeline instead.
        logger.debug(
            "structured html over-cleaned (%d -> %d chars), falling back to plain text",
            original_len, cleaned_len,
        )
        return None, None

    return raw_html, sanitize_article_html(raw_html)


async def extract_full_content(
    url: str,
    http_client: httpx.AsyncClient,
    *,
    timeout: float = 15.0,
    debug: Optional[dict] = None,
) -> Optional[ExtractedArticle]:
    """Extract the main article text and images from a URL.

    Fetches the page with a browser User-Agent, then runs trafilatura's
    readability-based extraction for the plain-text article body plus any
    cover/inline images found in the same main content. Returns ``None``
    when extraction is impossible (non-HTML content, blocked response, no
    article detected, or text too short).

    Args:
        url: The article URL to fetch and extract from.
        http_client: A shared ``httpx.AsyncClient`` to use for the request.
        timeout: Request timeout in seconds (default 15).
        debug: Optional dict that, if provided, is populated with
            ``skip_reason`` (why extraction returned ``None``, or ``None``
            on success) and ``http_status`` (the response status code, if a
            request was made) for troubleshooting.

    Returns:
        An ``ExtractedArticle`` with text/cover_image/images, or ``None``.
    """
    if debug is None:
        debug = {}
    debug["skip_reason"] = None
    debug["http_status"] = None

    skip_reason = _should_skip(url)
    if skip_reason:
        debug["skip_reason"] = skip_reason
        logger.debug("skip url=%s reason=%s", url, skip_reason)
        return None

    try:
        response = await http_client.get(
            url,
            headers=_REQUEST_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        debug["skip_reason"] = f"http_error:{exc.__class__.__name__}"
        logger.debug("HTTP error fetching %s: %s", url, exc)
        return None
    except Exception as exc:
        debug["skip_reason"] = f"unexpected_error:{exc.__class__.__name__}"
        logger.debug("Unexpected error fetching %s: %s", url, exc)
        return None

    debug["http_status"] = response.status_code

    if response.status_code != 200:
        debug["skip_reason"] = f"bad_status:{response.status_code}"
        logger.debug("skip url=%s reason=%s", url, debug["skip_reason"])
        return None

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        debug["skip_reason"] = f"non_html_content_type:{content_type or 'unknown'}"
        logger.debug("skip url=%s reason=%s", url, debug["skip_reason"])
        return None

    html = response.text
    if not html or len(html) < 500:
        debug["skip_reason"] = "html_too_short"
        logger.debug("skip url=%s reason=%s", url, debug["skip_reason"])
        return None

    # Strip obvious ad/subscribe/newsletter/hiring containers before any
    # extraction runs, so both the plain-text and structured-HTML pipelines
    # (and image extraction) see the same cleaned document. Checked against
    # the original fetch length above so a blocked/empty page is still
    # caught as such, not misread as "everything was boilerplate".
    html = _strip_boilerplate_containers(html)

    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            output_format="txt",
            favor_precision=True,
        )
    except Exception as exc:
        debug["skip_reason"] = f"trafilatura_error:{exc.__class__.__name__}"
        logger.debug("trafilatura extraction error for %s: %s", url, exc)
        return None

    if not text or len(text.strip()) < _MIN_CONTENT_LENGTH:
        debug["skip_reason"] = "extract_empty_or_short"
        logger.debug("skip url=%s reason=%s", url, debug["skip_reason"])
        return None

    cover_image, images = _extract_images(html, url)
    raw_html, display_html = _extract_structured_html(html, url)

    return ExtractedArticle(
        text=text.strip(),
        cover_image=cover_image,
        images=images,
        raw_html=raw_html,
        display_html=display_html,
        http_status=response.status_code,
        final_url=str(response.url),
    )


# ── content cleaning (raw_content -> clean_content) ─────────────────────────
#
# Extracted/scraped article text is kept verbatim as "raw content" for
# traceability. ``clean_article_content`` derives a display-ready version by
# stripping common scraping boilerplate — it never mutates its input.

_WHITESPACE_RE = re.compile(r"[\s\W_]+", re.UNICODE)

# Lines that are pure boilerplate ("阅读原文 · 域名", "Read more", RSS footers,
# source attribution) and should be dropped wherever they appear.
_NOISE_LINE_RE = re.compile(
    r"""^\s*(
        阅读原文(\s*[·丨\-:：]\s*.+)? |
        原文链接(\s*[·丨\-:：]\s*.+)? |
        点击(查看|阅读)原文.* |
        read\s+more(\s+(at|on)\s+\S+)?[.…»]* |
        continue\s+reading(\s+\S+)?[.…»]* |
        the\s+post\s+.+\s+appeared\s+first\s+on\s+.+\.? |
        (来源|来自|转自|source|via)\s*[:：]\s*.+
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# A short trailing "— SiteName" style attribution line, only stripped when it
# is the very last line of the article.
_TRAILING_ATTRIBUTION_RE = re.compile(r"^[-—–]{1,2}\s*[^-—–\n]{1,40}$")


def _normalize_for_compare(text: str) -> str:
    """Normalize text for loose equality checks (case/whitespace/punct-insensitive)."""
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE_RE.sub("", text).lower()


def _collapse_blank_lines(lines: list[str]) -> str:
    """Join lines, collapsing runs of blank lines down to a single blank line."""
    collapsed: list[str] = []
    prev_blank = False
    for ln in lines:
        if ln == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        collapsed.append(ln)
    return "\n".join(collapsed).strip("\n").strip()


def clean_article_content(raw: Optional[str], *, title: Optional[str] = None) -> str:
    """Derive display-ready ``clean_content`` from ``raw_content``.

    Strips common scraping noise — "阅读原文 · 域名" / "原文链接" boilerplate,
    "Read more" / "Continue reading" prompts, RSS "appeared first on ..."
    footers, trailing site-name attribution lines, a leading duplicate of
    the item title, and CTA sentences (subscribe/newsletter/hiring prompts
    etc., see ``_strip_cta_sentences``) — and collapses runs of blank lines
    to one. CTA cleaning is sentence-level, not line-level: a line that
    mixes real content with a trailing CTA keeps its real content, so a
    single-paragraph article never gets nuked just because it contains one
    CTA sentence.

    If CTA-sentence cleaning ends up removing most of what was left after
    established boilerplate-line stripping (under 30% of that, or under 200
    characters), that's more likely an overzealous CTA match than a
    genuinely ad-only article — in that case this returns the pre-CTA text
    instead (title-dedup, noise-line, and blank-line handling still
    applied, just not sentence-level CTA removal) rather than shipping a
    gutted result. The input string is never modified; callers that need
    the untouched original should keep using the raw content separately.

    Args:
        raw: The raw extracted/scraped article text.
        title: The item's title, used to strip a leading duplicate line.

    Returns:
        Cleaned article text, or ``""`` if there's nothing left to show.
    """
    if not raw or not raw.strip():
        return ""

    # Some sources (e.g. the HN API) hand back HTML-entity-escaped text
    # (I&#x27;m, &#x2F;) even after tags have been stripped upstream — decode
    # it here so display never shows raw entity codes.
    raw = html_module.unescape(raw)

    lines = [ln.strip() for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

    # Drop leading line(s) that just repeat the title.
    if title:
        norm_title = _normalize_for_compare(title)
        if norm_title:
            while lines:
                if lines[0] == "":
                    lines.pop(0)
                elif _normalize_for_compare(lines[0]) == norm_title:
                    lines.pop(0)
                else:
                    break

    # Drop a single trailing "— SiteName" attribution line.
    end = len(lines)
    while end > 0 and lines[end - 1] == "":
        end -= 1
    if end > 0 and _TRAILING_ATTRIBUTION_RE.match(lines[end - 1]):
        end -= 1
    lines = lines[:end]

    kept = [ln for ln in lines if not (ln and _NOISE_LINE_RE.match(ln))]

    # Baseline for the over-cleaning guard below: text length *after*
    # established boilerplate-line removal (阅读原文/Read more/etc, already
    # covered by tests and not in question here) but *before* sentence-level
    # CTA cleaning — so the guard only reacts to the new CTA step cutting
    # too deep, not to legitimate noise-line stripping.
    pre_cta_text = _collapse_blank_lines(kept)
    pre_cta_len = len(pre_cta_text)

    kept = [_strip_cta_sentences(ln)[0] if ln else ln for ln in kept]
    cleaned = _collapse_blank_lines(kept)

    if pre_cta_len and (
        len(cleaned) < pre_cta_len * _OVERCLEAN_MIN_RATIO or len(cleaned) < _OVERCLEAN_MIN_CHARS
    ):
        # Over-cleaning guard: CTA-sentence removal cut too deep — keep the
        # pre-CTA text (noise lines still stripped) rather than a result
        # that's mostly gone.
        logger.debug(
            "clean_article_content CTA-cleaning over-cleaned (%d -> %d chars), using pre-CTA fallback",
            pre_cta_len, len(cleaned),
        )
        return pre_cta_text

    return cleaned


async def extract_full_content_batch(items: List[ContentItem], console: Console) -> List[ContentItem]:
    """Extract full article text for each item's URL using trafilatura.

    For each item, fetches the original URL and runs readability-based
    extraction. ``item.rss_summary`` always captures the scraper's
    original snippet, success or failure. On success, ``item.raw_content``
    holds the extractor's plain-text output and ``item.content`` (the
    legacy alias) is updated to match it. On failure/skip, ``content``
    is left unchanged (it already equals the scraper snippet).
    ``content_source``/``extraction_status``/``extraction_error`` record
    which case happened, so downstream AI prompts don't mistake "only a
    summary" for "thin content".

    Args:
        items: Content items from all scrapers.
        console: Rich console for progress/status output.

    Returns:
        The same list (mutated in-place).
    """
    if not items:
        return items

    # source_label -> {"total": n, "extracted": n, "skipped": n}
    source_stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "extracted": 0, "skipped": 0}
    )
    skipped_records: List[dict] = []

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        semaphore = asyncio.Semaphore(8)  # limit concurrent fetches

        async def _extract_one(item: ContentItem) -> None:
            source_label = f"{item.source_type.value}:{sub_source_label(item)}"
            original_content = item.content or ""
            item.rss_summary = original_content

            async with semaphore:
                extract_debug: dict = {}
                result = await extract_full_content(
                    str(item.url), client, debug=extract_debug
                )

            stats = source_stats[source_label]
            stats["total"] += 1

            item.http_status = extract_debug.get("http_status")
            item.extracted_at = datetime.now(timezone.utc)
            item.extractor_version = EXTRACTOR_VERSION

            if result:
                item.raw_content = result.text
                item.content = result.text  # legacy alias, unchanged behavior
                item.cover_image = result.cover_image
                item.images = result.images
                item.raw_html = result.raw_html
                item.display_html = result.display_html
                item.final_url = result.final_url
                item.text_length = len(result.text)
                item.content_source = "full_text"
                item.extraction_status = "success"
                item.extraction_error = None
                stats["extracted"] += 1
            else:
                skip_reason = extract_debug.get("skip_reason")
                item.extraction_error = skip_reason
                item.extraction_status = (
                    "skipped"
                    if skip_reason and skip_reason.startswith(("skip_domain:", "skip_extension:"))
                    else "failed"
                )
                item.content_source = "rss_summary" if original_content.strip() else "none"
                stats["skipped"] += 1
                skipped_records.append(
                    {
                        "title": item.title,
                        "url": str(item.url),
                        "source": source_label,
                        "skip_reason": skip_reason,
                        "http_status": extract_debug.get("http_status"),
                        "rss_had_content": bool(original_content.strip()),
                        "rss_content_length": len(original_content.strip()),
                    }
                )

        await asyncio.gather(*[_extract_one(item) for item in items])

    extracted = sum(1 for item in items if item.extraction_status == "success")
    skipped = len(items) - extracted
    console.print(
        f"📄 成功提取 {extracted} 篇完整正文 / {skipped} 篇跳过\n"
    )

    logger.debug("Full-content extraction stats by source:")
    for source_label, stats in sorted(source_stats.items()):
        total = stats["total"]
        skip_ratio = stats["skipped"] / total if total else 0.0
        logger.debug(
            "  source=%s total=%d extracted=%d skipped=%d skip_ratio=%.1f%%",
            source_label, total, stats["extracted"], stats["skipped"], skip_ratio * 100,
        )

    for record in skipped_records:
        logger.debug(
            "skipped item title=%r url=%s source=%s skip_reason=%s http_status=%s "
            "rss_had_content=%s rss_content_length=%d",
            record["title"], record["url"], record["source"], record["skip_reason"],
            record["http_status"], record["rss_had_content"], record["rss_content_length"],
        )

    if skipped_records:
        write_extraction_debug_file(source_stats, skipped_records, console)

    return items


def write_extraction_debug_file(
    source_stats: Dict[str, Dict[str, int]], skipped_records: List[dict], console: Console
) -> Path:
    """Write a JSON debug export of full-content extraction results.

    Args:
        source_stats: Per-source total/extracted/skipped counts.
        skipped_records: Per-item details for every skipped item.
        console: Rich console for progress/status output.

    Returns:
        Path to the written debug file.
    """
    debug_dir = Path("data/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    by_source = {
        source_label: {
            **stats,
            "skip_ratio": round(stats["skipped"] / stats["total"], 4) if stats["total"] else 0.0,
        }
        for source_label, stats in sorted(source_stats.items())
    }

    payload = {
        "generated_at": timestamp.isoformat(),
        "total_items": sum(s["total"] for s in source_stats.values()),
        "total_extracted": sum(s["extracted"] for s in source_stats.values()),
        "total_skipped": sum(s["skipped"] for s in source_stats.values()),
        "by_source": by_source,
        "skipped_items": skipped_records,
    }

    debug_path = debug_dir / f"extraction_debug_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    debug_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    console.print(f"🐛 正文提取 debug 导出: {debug_path}\n")
    return debug_path
