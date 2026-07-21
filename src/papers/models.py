"""Data model for the standalone papers library.

Deliberately independent of `src.models.ContentItem` — papers carry no
AI scoring/enrichment fields since the papers pipeline never runs them
through the news pipeline's analyzer/enricher.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Paper(BaseModel):
    """A single paper from one configured source (OpenAlex, Hugging Face, ...)."""

    id: str               # f"{source}:{native_id}", e.g. "openalex:W2194775991"
    source: str            # short source key, e.g. "openalex", "huggingface"
    native_id: str          # the source's own id (OpenAlex work id, HF's arXiv id)
    title: str
    authors: List[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None  # not every work has an open-access PDF
    published_at: datetime
    updated_at: datetime
    publication_year: Optional[int] = None  # derived from published_at, kept for easy filtering
    categories: List[str] = []
    # For classic-library papers (source="openalex"), one of the fixed v1
    # taxonomy categories from `src.papers.seed_data` — never derived from
    # any API response. Unset for non-classic sources (e.g. Hugging Face).
    category: Optional[str] = None
    comment: Optional[str] = None
    journal_ref: Optional[str] = None
    doi: Optional[str] = None
    # Canonical metadata — when set from a human-curated seed, these ALWAYS
    # override API-fetched values. See SeedPaper.canonical_*.
    canonical_doi: Optional[str] = None     # DOI of the original version (not a reprint)
    reprint_doi: Optional[str] = None       # DOI of a later reprint (informational only)
    source_version_type: Optional[str] = None  # "original" | "journal_version" | "reprint" | "preprint"
    openalex_id_override: Optional[str] = None  # source OpenAlex ID used for matching (informational)
    arxiv_id: Optional[str] = None              # arXiv identifier, e.g. "1506.02640"
    semantic_scholar_id: Optional[str] = None   # Semantic Scholar paper id (CorpusId or S2PaperId)
    open_access: Optional[bool] = None
    citation_count: Optional[int] = None       # raw citation count (OpenAlex cited_by_count)
    citation_percentile: Optional[float] = None  # OpenAlex citation_normalized_percentile.value
    upvote_count: Optional[int] = None    # Hugging Face upvotes
    raw_metadata: Optional[Dict[str, Any]] = None  # full raw source JSON, for re-parsing later
    # ---- translations -------------------------------------------------------
    title_zh: Optional[str] = None          # AI-translated Chinese title
    abstract_zh: Optional[str] = None       # AI-translated Chinese abstract
    original_language: Optional[str] = None  # detected language: "zh" | "en" | "unknown"
    fetched_at: datetime


class SeedMatchResult(BaseModel):
    """Outcome of matching one `SeedPaper` (see `src.papers.seed_data`) to a
    real paper record. Surfaced by the CLI so non-"matched" seeds can be
    manually reviewed and, if needed, pinned via `SeedPaper.openalex_id_override`.

    Two independent status axes:

    ``match_status`` — how confidently we identified the canonical paper record:
        - ``matched``: exactly one distinct candidate passed verification
        - ``manual_review``: multiple genuinely distinct candidates passed; needs a human to pick
        - ``unmatched``: no candidate cleared the title-similarity floor

    ``enrichment_status`` — how well we populated the required metadata fields:
        - ``complete``: all required fields are present
        - ``partial``: some fields filled, some still missing
        - ``rate_limited``: one or more enrichment sources returned 429; fields may be incomplete
        - ``failed``: all enrichment sources errored; only OpenAlex fields present
        - ``not_attempted``: enrichment was skipped (e.g. unmatched seed)
    """

    seed_title: str
    category: str
    match_status: str   # "matched" | "manual_review" | "unmatched"
    match_method: Optional[str] = None  # "doi" | "arxiv_id" | "override" | "title_year_author" | None
    enrichment_status: str = "not_attempted"  # "complete" | "partial" | "rate_limited" | "failed" | "not_attempted"
    paper_id: Optional[str] = None
    matched_title: Optional[str] = None
    matched_year: Optional[int] = None
    expected_year: int
    note: str = ""


class ClassicFetchResult(BaseModel):
    """Result of one `OpenAlexFetcher.fetch_classic()` call."""

    papers: List[Paper]
    match_results: List[SeedMatchResult]
