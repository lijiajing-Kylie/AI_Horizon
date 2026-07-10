"""Chinese translation of structured article HTML (``display_html``).

Translates ``display_html`` block-by-block (``p``/``h2``/``h3``/``h4``/
``blockquote``/``li``/``figcaption``) instead of handing the whole document
to the AI in one shot: each block's inner HTML (which only ever contains the
inline whitelist ``strong``/``em``/``a``/``br``) is sent for translation with
strict instructions to keep tags/attributes untouched and translate only the
visible text. ``img``/``figure`` elements and ``a``/``img`` attributes are
never part of a translated block, so they cannot be altered by the AI.

The AI is not trusted: each translated block is whitelist-sanitized before
being spliced back in, and the fully reassembled document is sanitized again
via ``content_extractor.sanitize_article_html`` before being returned. If the
AI returns a different number of translations than blocks were sent — for
any batch — the whole translation is abandoned and ``None`` is returned, so
callers never persist a partially-translated document.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import nh3
from bs4 import BeautifulSoup

from .client import AIClient
from .prompts import HTML_TRANSLATION_SYSTEM, HTML_TRANSLATION_USER
from .utils import parse_json_response
from ..content_extractor import sanitize_article_html

logger = logging.getLogger(__name__)

# Block-level tags that carry translatable text. Deliberately excludes
# img/figure/ul/ol/br — those are structural and never sent to the AI.
_BLOCK_TAGS = ["h2", "h3", "h4", "p", "blockquote", "li", "figcaption"]

# Inline tags a translated block is allowed to contain, mirroring
# content_extractor's whitelist minus the block-level tags (a block's inner
# HTML can only ever contain inline markup). No "a" here: the body never
# renders clickable links (content_extractor._render_inline_content no
# longer emits them either) — if the AI hallucinates one in translation,
# nh3 strips the tag and keeps just the anchor text.
_ALLOWED_INLINE_TAGS = {"strong", "em", "br"}
_ALLOWED_INLINE_ATTRIBUTES: dict[str, set[str]] = {}
_ALLOWED_URL_SCHEMES = {"http", "https"}

# Batching keeps individual prompts small enough to stay reliable and fast;
# a long article's blocks are translated across multiple sequential calls.
_MAX_BLOCKS_PER_BATCH = 20
_MAX_CHARS_PER_BATCH = 3000


def _clean_inline_fragment(fragment: str) -> str:
    """Whitelist-sanitize a single translated block's inner HTML."""
    try:
        return nh3.clean(
            fragment,
            tags=_ALLOWED_INLINE_TAGS,
            attributes=_ALLOWED_INLINE_ATTRIBUTES,
            url_schemes=_ALLOWED_URL_SCHEMES,
            link_rel="noopener noreferrer nofollow",
        )
    except Exception:
        return ""


def _chunk_blocks(blocks: List) -> List[List]:
    """Split translatable blocks into batches bounded by count and char length."""
    batches: List[List] = []
    current: List = []
    current_chars = 0
    for el in blocks:
        snippet_len = len(el.decode_contents())
        if current and (
            len(current) >= _MAX_BLOCKS_PER_BATCH
            or current_chars + snippet_len > _MAX_CHARS_PER_BATCH
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(el)
        current_chars += snippet_len
    if current:
        batches.append(current)
    return batches


async def _translate_snippets(client: AIClient, snippets: List[str]) -> Optional[List[str]]:
    """Ask the AI to translate a batch of HTML snippets to Chinese.

    Returns the translated snippets in the same order, or ``None`` if the
    response is missing, malformed, or doesn't contain exactly as many
    translations as snippets were sent.
    """
    user_prompt = HTML_TRANSLATION_USER.format(
        n=len(snippets),
        snippets_json=json.dumps(snippets, ensure_ascii=False),
    )
    try:
        response = await client.complete(
            system=HTML_TRANSLATION_SYSTEM,
            user=user_prompt,
        )
    except Exception as exc:
        logger.debug("html translation request failed: %s", exc)
        return None

    result = parse_json_response(response)
    if not isinstance(result, dict):
        return None
    translations = result.get("translations")
    if not isinstance(translations, list) or len(translations) != len(snippets):
        return None
    if not all(isinstance(t, str) for t in translations):
        return None
    return translations


async def translate_display_html(client: AIClient, display_html: str) -> Optional[str]:
    """Translate ``display_html``'s text blocks to Chinese, preserving structure.

    Args:
        client: AI client to use for translation.
        display_html: Sanitized structured article HTML (as produced by
            ``content_extractor.sanitize_article_html``).

    Returns:
        A new sanitized HTML string with block text translated to Chinese,
        or ``None`` if there was nothing to translate or translation failed
        at any stage (caller should leave ``display_html_zh`` unset).
    """
    if not display_html or not display_html.strip():
        return None

    soup = BeautifulSoup(display_html, "html.parser")
    blocks = [el for el in soup.find_all(_BLOCK_TAGS) if el.get_text(strip=True)]
    if not blocks:
        return None

    original_img_count = len(soup.find_all("img"))

    for batch in _chunk_blocks(blocks):
        snippets = [el.decode_contents() for el in batch]
        translations = await _translate_snippets(client, snippets)
        if translations is None:
            logger.debug("html translation batch failed or size mismatch, aborting")
            return None
        for el, translated in zip(batch, translations):
            clean = _clean_inline_fragment(translated)
            el.clear()
            fragment = BeautifulSoup(clean, "html.parser")
            for child in list(fragment.contents):
                el.append(child)

    result = str(soup)
    sanitized = sanitize_article_html(result)
    if not sanitized:
        return None

    # Cheap structural sanity check: translation must never touch image
    # count (images live outside translated blocks) — a mismatch means
    # something went wrong during reassembly and the result isn't trustworthy.
    if len(BeautifulSoup(sanitized, "html.parser").find_all("img")) != original_img_count:
        logger.debug("html translation image count mismatch, aborting")
        return None

    return sanitized
