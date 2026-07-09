"""Full article text and image extraction via trafilatura.

Fetches the original URL for a news item and extracts the main article
content using trafilatura's readability-based algorithm, plus any images
found within that main content (cover image + inline images with
captions). Skips URLs that are not article-like (social media, code repos,
images, etc.).
"""

from __future__ import annotations

import html as html_module
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
import nh3
import trafilatura
from bs4 import BeautifulSoup
from trafilatura.metadata import extract_metadata

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


@dataclass
class ExtractedArticle:
    """Result of a successful full-content extraction."""

    text: str
    cover_image: Optional[str] = None
    images: List[Dict[str, Any]] = field(default_factory=list)
    raw_html: Optional[str] = None  # structured main-content HTML, unsanitized
    display_html: Optional[str] = None  # raw_html after nh3 whitelist sanitize


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
    ``hi rend="#b"`` -> ``strong``, ``hi rend="#i"`` -> ``em``, and
    ``ref target="..."`` -> ``a href="..."`` (only for http(s) targets —
    anything else is rendered as plain text, dropping the link).
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
        elif child.tag == "ref":
            target = (child.get("target") or "").strip()
            if target.startswith("http://") or target.startswith("https://"):
                parts.append(f'<a href="{html_module.escape(target, quote=True)}">{inner}</a>')
            else:
                parts.append(inner)
        else:
            parts.append(inner)
        parts.append(html_module.escape(child.tail or ""))
    return "".join(parts)


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
            text = _render_inline_content(el)
            if text.strip():
                blocks.append(f"<p>{text}</p>")
        elif tag == "quote":
            text = _render_inline_content(el)
            if text.strip():
                blocks.append(f"<blockquote>{text}</blockquote>")
        elif tag == "list":
            list_tag = "ol" if (el.get("rend") or "ul") == "ol" else "ul"
            items = []
            for item_el in el.findall("item"):
                item_text = _render_inline_content(item_el)
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

    raw_html = _build_structured_html(root, url, figcaptions)
    if not raw_html.strip():
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


def clean_article_content(raw: Optional[str], *, title: Optional[str] = None) -> str:
    """Derive display-ready ``clean_content`` from ``raw_content``.

    Strips common scraping noise — "阅读原文 · 域名" / "原文链接" boilerplate,
    "Read more" / "Continue reading" prompts, RSS "appeared first on ..."
    footers, trailing site-name attribution lines, and a leading duplicate
    of the item title — and collapses runs of blank lines to one. The input
    string is never modified; callers that need the untouched original
    should keep using the raw content separately.

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

    # Collapse runs of blank lines down to a single blank line.
    collapsed: list[str] = []
    prev_blank = False
    for ln in kept:
        if ln == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        collapsed.append(ln)

    return "\n".join(collapsed).strip("\n").strip()
