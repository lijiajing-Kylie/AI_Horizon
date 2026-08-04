"""Rule-based filters for the arXiv weekly-featured pipeline.

Pure functions — no IO, no AI — so they are trivially unit-testable. They
operate on ``Paper`` objects in place where they fill a field (``venue``,
``github_url``) and return new lists where they drop papers.

Pipeline order (see ``src.papers.weekly.apply_rules``):
    withdrawn → short-abstract → keyword whitelist → keyword blacklist
    → github-url extraction → venue-signal priority → truncate
"""

from __future__ import annotations

import re
from typing import List, Optional

from .models import Paper

# ── Top-conference whitelist used for the venue priority signal ─────────────
TOP_CONFERENCE_NAMES: List[str] = [
    "NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "NAACL",
    "CVPR", "ICCV", "ECCV", "AAAI", "IJCAI", "ICRA", "CoRL", "MLSys", "KDD",
]

# Phrases that indicate the paper has been accepted / will appear at a venue.
_ACCEPT_RE = re.compile(
    r"(?i)\b(accepted|to appear|to be published|accepted to|accepted at|"
    r"appeared at|appears in|presented at|published at|accepted for)\b"
)

GITHUB_URL_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

_WITHDRAWN_RE = re.compile(r"\bwithdrawn\b", re.IGNORECASE)


def detect_venue(comment: Optional[str], journal_ref: Optional[str]) -> Optional[str]:
    """Detect a top-conference signal from arXiv comment / journal_ref.

    Two signals, strongest first:

    1. **Strong** — an acceptance phrase (accepted / to appear / …) plus a
       conference name, optionally with a year → ``"NeurIPS 2025"``.
    2. **Weak** — a bare conference name (e.g. a workshop or the journal_ref
       already being the venue name) → ``"CVPR"``.

    Returns None when neither is found.
    """
    text = " ".join(x for x in (journal_ref, comment) if x)
    if not text:
        return None

    # Strong signal: an acceptance phrase — pick the conference name that
    # appears nearest *after* the phrase (not merely the first whitelist
    # match in the whole text, which could be a different venue).
    accept = _ACCEPT_RE.search(text)
    if accept:
        window = text[accept.end(): accept.end() + 80]
        best: Optional[tuple[int, str]] = None
        for name in TOP_CONFERENCE_NAMES:
            m = re.search(rf"\b{re.escape(name)}\b\s*(20\d{{2}})?", window)
            if m:
                venue = name + (" " + m.group(1) if m.group(1) else "")
                if best is None or m.start() < best[0]:
                    best = (m.start(), venue)
        if best:
            return best[1]

    # Weak signal: a bare conference name (e.g. workshop, or journal_ref
    # already being the venue name).
    for name in TOP_CONFERENCE_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", text):
            return name
    return None


def extract_github_url(comment: Optional[str], abstract: Optional[str]) -> Optional[str]:
    """Extract a GitHub repository URL, preferring the arXiv comment.

    Many arXiv comments carry ``Code: https://github.com/owner/repo``. Falls
    back to the abstract (rarely used) and returns None when absent.

    ``GITHUB_URL_RE`` is greedy over the repo-name character class, so a
    sentence-final period — ``Code: https://github.com/owner/repo.`` — gets
    swallowed into the match; strip trailing dots so the extracted URL
    actually resolves (a ``.git`` suffix is unaffected since it ends in a
    letter).
    """
    for text in (comment, abstract):
        if not text:
            continue
        m = GITHUB_URL_RE.search(text)
        if m:
            return m.group(0).rstrip(".")
    return None


def exclude_withdrawn(papers: List[Paper]) -> List[Paper]:
    """Drop papers whose title/abstract/comment mention being withdrawn."""
    return [p for p in papers if not _withdrawn(p)]


def _withdrawn(p: Paper) -> bool:
    for text in (p.title, p.abstract, p.comment):
        if text and _WITHDRAWN_RE.search(text):
            return True
    return False


def reject_short_abstracts(papers: List[Paper], min_chars: int) -> List[Paper]:
    """Drop papers whose abstract is shorter than *min_chars*."""
    if min_chars <= 0:
        return papers
    return [p for p in papers if len(p.abstract or "") >= min_chars]


def _keyword_regex(keywords: List[str]) -> "re.Pattern[str]":
    """Build a case-insensitive word-boundary regex over a keyword list.

    A leading/trailing ``\\b`` keeps short acronyms (``ai``, ``rag``, ``llm``)
    from matching inside longer words (``said``, ``storage``, ``main``), while
    a trailing ``s?`` lets common plurals (``agents`` / ``transformers``)
    match. Phrases (``sentiment analysis``) work as-is.
    """
    return re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")s?\b",
        re.IGNORECASE,
    )


def apply_keyword_whitelist(papers: List[Paper], keywords: List[str]) -> List[Paper]:
    """Keep papers whose title/abstract matches at least one whitelist keyword.

    An empty keyword list disables the filter and returns papers unchanged.
    Matching is case-insensitive word-boundary matching so short acronyms
    (ai, rag, llm) don't false-positive inside longer English words.
    """
    if not keywords:
        return papers
    pattern = _keyword_regex(keywords)

    def matches(p: Paper) -> bool:
        combined = " ".join([p.title or "", p.abstract or ""])
        return bool(pattern.search(combined))

    return [p for p in papers if matches(p)]


def apply_keyword_blacklist(papers: List[Paper], keywords: List[str]) -> List[Paper]:
    """Drop papers whose title/abstract matches any blacklist keyword."""
    if not keywords:
        return papers
    pattern = _keyword_regex(keywords)

    return [
        p for p in papers
        if not pattern.search(" ".join([p.title or "", p.abstract or ""]))
    ]


def apply_venue_signals(papers: List[Paper]) -> List[Paper]:
    """Fill ``paper.venue`` from comment/journal_ref and sort venue-signal-first.

    Papers with a detected venue come first (stable order preserved within
    each group), so a later ``truncate()`` keeps the top-conference papers
    when the candidate pool is oversized.
    """
    for p in papers:
        p.venue = detect_venue(p.comment, p.journal_ref)
    return sorted(papers, key=lambda p: 0 if p.venue else 1)


def truncate(papers: List[Paper], limit: int) -> List[Paper]:
    """Keep the first *limit* papers (call after venue-signal sorting)."""
    return papers[:limit]
