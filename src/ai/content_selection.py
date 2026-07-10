"""Shared content-tier resolution for AI-facing consumers.

``ContentItem`` can carry up to three tiers of article text — the
extractor's cleaned text, its raw extraction output, and the source
scraper's own summary/snippet. Analyzer, enricher, and language detection
must all agree on which tier to read and must all tell the AI honestly
which tier it's looking at, otherwise a summary-only item gets penalized
as if it were a thin full article. ``resolve_content`` is the single place
that priority is decided.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..content_extractor import clean_article_content
from ..models import ContentItem
from .utils import split_content_and_comments


@dataclass(frozen=True)
class ResolvedContent:
    """The best available article text for a ``ContentItem``, plus its provenance."""

    text: str
    content_source: str  # "full_text" | "rss_summary" | "none"
    is_full_text: bool  # convenience: content_source == "full_text"
    extraction_status: str  # ContentItem.extraction_status, or "unknown" for older items


def resolve_content(item: ContentItem) -> ResolvedContent:
    """Resolve the best available article text: clean_content > raw_content > rss_summary.

    ``clean_content`` is not a stored field — it's recomputed here from
    ``raw_content`` via ``clean_article_content``. Both it and
    ``raw_content`` count as ``content_source="full_text"`` for prompt
    purposes: what matters to a caller/prompt is whether the extractor
    produced the real article at all, not which cleaning stage is used.
    """
    status = item.extraction_status or "unknown"

    if item.raw_content:
        cleaned = clean_article_content(item.raw_content, title=item.title)
        text = cleaned or item.raw_content
        return ResolvedContent(text=text, content_source="full_text", is_full_text=True, extraction_status=status)

    if item.rss_summary:
        return ResolvedContent(text=item.rss_summary, content_source="rss_summary", is_full_text=False, extraction_status=status)

    return ResolvedContent(text="", content_source="none", is_full_text=False, extraction_status=status)


def build_source_note(resolved: ResolvedContent) -> str:
    """Build the prompt line warning the AI when it's only seeing a summary.

    Returns "" when ``resolved.is_full_text`` is True — no note needed.
    """
    if resolved.is_full_text:
        return ""
    return (
        f"注意：本条目正文抓取{resolved.extraction_status}（来源：{resolved.content_source}），"
        "以下内容仅为来源摘要，请勿因此判定为内容单薄而扣分。"
    )


@dataclass(frozen=True)
class StageInput:
    """The exact text a pipeline stage sends the AI, plus how it was derived.

    Shared by :func:`build_analysis_input` and :func:`build_enrichment_input`
    so the scrape-diagnostics panel can show precisely what each stage saw
    without maintaining a second copy of the truncation rules.
    """

    text: str  # the truncated string actually interpolated into the stage's prompt
    content_source: str  # ResolvedContent.content_source ("full_text" | "rss_summary" | "none")
    original_length: int  # len(text) before this stage's truncation
    sent_length: int  # len(text) after truncation — what the prompt actually contains
    truncation_limit: int  # the character cap this stage applies
    source_note: str  # build_source_note(resolved) — "" when content is full_text


def build_analysis_input(item: ContentItem) -> StageInput:
    """Reproduce ``analyzer.ContentAnalyzer._analyze_item``'s content selection.

    Mirrors the analyzer's own logic exactly (same 800/1000-char cap
    depending on whether a comments section is present) so this can be
    called from a read-only context (e.g. the diagnostics API) without
    duplicating — and risking drifting from — the real prompt-building code.
    """
    resolved = resolve_content(item)
    text, _comments = split_content_and_comments(resolved.text)
    has_comments = "--- Top Comments ---" in resolved.text
    limit = 800 if has_comments else 1000
    return StageInput(
        text=text[:limit],
        content_source=resolved.content_source,
        original_length=len(text),
        sent_length=len(text[:limit]),
        truncation_limit=limit,
        source_note=build_source_note(resolved),
    )


def build_enrichment_input(item: ContentItem) -> StageInput:
    """Reproduce ``enricher.ContentEnricher._enrich_item``'s content selection.

    Mirrors the enricher's own logic exactly (fixed 4000-char cap,
    regardless of whether a comments section is present).
    """
    resolved = resolve_content(item)
    text, _comments = split_content_and_comments(resolved.text)
    limit = 4000
    return StageInput(
        text=text[:limit],
        content_source=resolved.content_source,
        original_length=len(text),
        sent_length=len(text[:limit]),
        truncation_limit=limit,
        source_note=build_source_note(resolved),
    )


def content_hash(text: str | None) -> str:
    """Sha256 hex digest of ``text``, used to record what a translation/enrichment was derived from.

    This is recorded for future staleness detection only. Nothing in the
    current pipeline reads a stored ``*_source_hash`` back to decide
    whether to skip a translation/enrichment AI call — every run still
    re-translates/re-enriches unconditionally. Wiring up a skip-on-match
    check would require the orchestrator to load each item's prior DB row
    before enrichment, which is a separate, deliberate follow-up change.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
