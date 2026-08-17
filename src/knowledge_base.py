"""Render a single news item as Markdown for export to a knowledge base.

V1 scope: the backend only renders the Markdown content and a download
filename (derived from the title); the browser performs the actual download.
No server-side storage, no directory configuration, no batch export.

The body is exported in Chinese when a translation is available: the AI
translation lives in ``display_html_zh`` (Chinese HTML), so we convert that
fragment to text and fall back to the cleaned original text otherwise.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Optional

from .content_extractor import clean_article_content
from .reports.pdf import sanitize_filename

# Block-level tags that start a new line when converting HTML → text.
_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "blockquote", "li", "tr"}
)


class _TextExtractor(HTMLParser):
    """Extract visible text from a whitelisted HTML fragment.

    ``display_html`` / ``display_html_zh`` are nh3-cleaned fragments (block
    elements + inline strong/em/br), so a simple block-aware text pass is
    sufficient — no full document parsing needed.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" or tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        lines = [ln.strip() for ln in "".join(self._parts).split("\n")]
        return "\n".join(ln for ln in lines if ln)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    finally:
        parser.close()
    return parser.text()


def _extract_body(item: dict) -> str:
    """Full article body, preferring the Chinese-translated HTML.

    Priority: ``display_html_zh`` (Chinese) → ``display_html`` (original
    language) → ``clean_content`` (already-cleaned plain text). The HTML
    branches are converted to text and run through the same noise cleaning
    that ``clean_content`` uses.
    """
    html = item.get("display_html_zh") or item.get("display_html")
    if html:
        text = clean_article_content(_html_to_text(html), title=item.get("title"))
        if text.strip():
            return text.strip()
    return (item.get("clean_content") or "").strip()


def _yaml_str(value: str) -> str:
    """Quote a frontmatter scalar as a JSON double-quoted string.

    JSON double-quoted strings are valid YAML scalars and escape quotes,
    colons and newlines that would otherwise break the frontmatter block.
    """
    return json.dumps(value, ensure_ascii=False)


def _date_str(published_at: Any) -> str:
    """Return ``YYYY-MM-DD`` from either a datetime or an ISO string.

    ``db.get_item()`` hands the API layer ``published_at`` as an ISO string
    (TEXT column), while the ``ContentItem`` model keeps it as a datetime —
    both must render the same date.
    """
    if isinstance(published_at, datetime):
        return published_at.date().isoformat()
    if isinstance(published_at, date):
        return published_at.isoformat()
    return str(published_at or "")[:10]


def build_item_markdown(item: dict, note: Optional[str] = None) -> str:
    """Assemble the item as a standard Markdown file with YAML frontmatter.

    Precondition: ``item`` has passed through ``_attach_content()`` so it
    carries ``clean_content`` as a fallback. Field priority mirrors what the
    detail page shows: prefer the Chinese enriched title/summary, and the
    Chinese-translated body when available.

    When ``note`` is a non-blank string, a ``## 我的笔记`` section is appended
    at the end of the file under the user's own note. ``None``/empty/whitespace
    notes are skipped entirely so the output stays byte-identical to a plain
    export; the note body is passed through verbatim (multiline text and
    markdown syntax are preserved, only leading/trailing whitespace stripped).
    """
    meta = item.get("metadata") or {}
    title = meta.get("title_zh") or item.get("title") or ""
    summary = meta.get("detailed_summary_zh") or item.get("ai_summary") or ""
    body = _extract_body(item)
    tags = item.get("ai_tags") or []

    lines = [
        "---",
        f"title: {_yaml_str(title)}",
        f"date: {_date_str(item.get('published_at'))}",
        f"url: {_yaml_str(item.get('url') or '')}",  # 仅溯源
        "tags:",
    ]
    lines += [f"  - {_yaml_str(t)}" for t in tags] if tags else ["  []"]
    lines += [
        "---",
        "",
        f"# {title}",
        "",
        "## 摘要",
        "",
        summary.strip() or "（无摘要）",
        "",
        "## 正文",
        "",
        body if body else "（无正文）",
    ]
    if note and note.strip():
        lines += ["", "## 我的笔记", "", note.strip()]
    return "\n".join(lines) + "\n"


def build_markdown_filename(item: dict) -> str:
    """Download filename for the item, derived from its (Chinese) title.

    Uses ``sanitize_filename`` so illegal characters are replaced and the
    name stays within sane length. Name collisions are left to the browser
    (it appends ``(1)``, ``(2)``, ... automatically).
    """
    meta = item.get("metadata") or {}
    title = meta.get("title_zh") or item.get("title") or item.get("id") or "horizon"
    stem = sanitize_filename(title, max_len=120)
    return f"{stem}.md"
