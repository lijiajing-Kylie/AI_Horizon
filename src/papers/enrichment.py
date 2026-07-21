"""Fallback enrichment chain: fills gaps in a classic-library `Paper` record
by querying Semantic Scholar, then arXiv, then Crossref, in that order —
stopping as soon as every required field is present. Never overwrites a
field OpenAlex (or an earlier source in the chain) already populated.

Enrichment runs **after** matching and never affects ``match_status``.
Failures (429, timeouts, etc.) are reflected in ``enrichment_status`` only.

Required fields per the v1 spec: title, authors, abstract, publication year,
DOI, original-source URL, venue. PDF link is best-effort (not every paper has
one) so it's excluded from the required set.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .models import Paper
from .sources import arxiv, crossref, semantic_scholar

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["title", "authors", "abstract", "publication_year", "doi", "url", "journal_ref"]

# Order matters: Semantic Scholar first (best CS-paper coverage/abstracts),
# then arXiv (best for preprint PDF/abstract), then Crossref (last resort,
# strongest for DOI/venue on older non-arXiv papers).
#
# Stores modules, not bound `.search` functions: a module attribute is looked
# up fresh on every call (`module.search(...)`), so `unittest.mock.patch`ing
# e.g. `src.papers.sources.semantic_scholar.search` takes effect — capturing
# the function object into this list at import time would freeze in the
# pre-patch reference.
_FALLBACK_SOURCES: List[Tuple[str, Any]] = [
    ("semantic_scholar", semantic_scholar),
    ("arxiv", arxiv),
    ("crossref", crossref),
]


def missing_fields(paper: Paper) -> List[str]:
    """Which of ``REQUIRED_FIELDS`` are unset/empty on *paper*."""
    missing = []
    for field in REQUIRED_FIELDS:
        value = getattr(paper, field, None)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


async def enrich_paper(
    client: httpx.AsyncClient,
    paper: Paper,
    seed_title: str,
) -> Tuple[Paper, str]:
    """Fill *paper*'s missing required fields via the fallback chain.

    Returns ``(enriched_paper, enrichment_status)`` where enrichment_status is
    one of: ``"complete"``, ``"partial"``, ``"rate_limited"``, ``"failed"``.

    *seed_title* is used as the query for each fallback source (the seed's
    canonical title may differ slightly from the matched work's title).
    """
    fields = _paper_to_dict(paper)
    initial_missing = set(missing_fields(paper))
    if not initial_missing:
        return paper, "complete"

    had_rate_limit = False
    had_any_success = False

    for name, module in _FALLBACK_SOURCES:
        remaining = [f for f in REQUIRED_FIELDS if not fields.get(f)]
        if not remaining:
            break

        result = await module.search(client, seed_title)
        if result is None:
            # Distinguish rate-limit from genuine "not found"
            if _was_rate_limited(name):
                had_rate_limit = True
            continue

        had_any_success = True
        _merge(fields, result)

        # Carry over stable identifiers from enrichment sources
        if result.get("arxiv_id") and not paper.arxiv_id:
            paper.arxiv_id = result["arxiv_id"]
        if result.get("semantic_scholar_id") and not paper.semantic_scholar_id:
            paper.semantic_scholar_id = result["semantic_scholar_id"]

    # When the canonical version has no DOI but the paper carries a
    # reprint_doi, the enrichment chain may try to fill the empty doi slot
    # with the reprint DOI — block that: the primary doi MUST stay None.
    if paper.reprint_doi and not paper.canonical_doi:
        fields["doi"] = None

    remaining = [f for f in REQUIRED_FIELDS if not fields.get(f)]

    if not remaining:
        status = "complete"
    elif had_rate_limit and not had_any_success:
        status = "rate_limited"
    elif had_rate_limit:
        status = "rate_limited"  # partial with rate limiting
    elif not had_any_success:
        status = "failed"
    else:
        status = "partial"

    # Rebuild the paper with merged fields
    merged = _dict_to_paper(fields, paper)
    # Preserve any identifiers set above
    if paper.arxiv_id:
        merged.arxiv_id = paper.arxiv_id
    if paper.semantic_scholar_id:
        merged.semantic_scholar_id = paper.semantic_scholar_id

    return merged, status


def enrichment_status_for(paper: Paper) -> str:
    """Compute enrichment status for a paper without running the chain.
    Used when enrichment is skipped (e.g. unmatched seeds)."""
    mf = missing_fields(paper)
    if not mf:
        return "complete"
    return "not_attempted"


def _was_rate_limited(source_name: str) -> bool:
    """Check whether a specific enrichment source hit a rate limit during
    this session."""
    if source_name == "semantic_scholar":
        return semantic_scholar.had_rate_limit()
    return False


# -- internal helpers ---------------------------------------------------------

def _paper_to_dict(paper: Paper) -> Dict[str, Any]:
    return {
        "title": paper.title,
        "authors": list(paper.authors),
        "abstract": paper.abstract,
        "publication_year": paper.publication_year,
        "doi": paper.doi,
        "url": paper.url,
        "journal_ref": paper.journal_ref,
        "pdf_url": paper.pdf_url,
        "native_id": paper.native_id,
        "source": paper.source,
        "published_at": paper.published_at,
        "open_access": paper.open_access,
        "citation_count": paper.citation_count,
        "citation_percentile": paper.citation_percentile,
        "raw_metadata": paper.raw_metadata,
    }


def _merge(fields: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Fill gaps in *fields* from a normalized fallback-source *result* dict
    (as returned by ``semantic_scholar.search`` / ``arxiv.search`` /
    ``crossref.search``).
    """
    if not fields.get("title") and result.get("title"):
        fields["title"] = result["title"]
    if not fields.get("authors") and result.get("authors"):
        fields["authors"] = result["authors"]
    if not fields.get("abstract") and result.get("abstract"):
        fields["abstract"] = result["abstract"]
    if not fields.get("publication_year") and result.get("year"):
        fields["publication_year"] = result["year"]
    if not fields.get("doi") and result.get("doi"):
        fields["doi"] = result["doi"]
    if not fields.get("pdf_url") and result.get("pdf_url"):
        fields["pdf_url"] = result["pdf_url"]
    if not fields.get("journal_ref") and result.get("venue"):
        fields["journal_ref"] = result["venue"]
    if not fields.get("url"):
        if result.get("doi"):
            fields["url"] = f"https://doi.org/{result['doi']}"
        elif result.get("arxiv_id"):
            fields["url"] = f"https://arxiv.org/abs/{result['arxiv_id']}"


def _dict_to_paper(fields: Dict[str, Any], paper: Paper) -> Paper:
    """Rebuild a Paper from merged field dict, preserving the original paper's
    identity fields (id, source, native_id), stable identifiers, and canonical
    metadata (which must survive enrichment unchanged).
    """
    now = datetime.now(timezone.utc)
    published_at = fields.get("published_at") or paper.published_at
    title = fields.get("title") or paper.title

    return Paper(
        id=paper.id,
        source=paper.source,
        native_id=paper.native_id,
        title=title,
        authors=fields.get("authors") or [],
        abstract=fields.get("abstract") or "",
        url=fields.get("url") or paper.url,
        pdf_url=fields.get("pdf_url") or paper.pdf_url,
        published_at=published_at,
        updated_at=now,
        publication_year=fields.get("publication_year"),
        categories=list(paper.categories),
        category=paper.category,
        journal_ref=fields.get("journal_ref") or paper.journal_ref,
        doi=fields.get("doi") or paper.doi,
        # Canonical fields — must survive enrichment intact
        canonical_doi=paper.canonical_doi,
        reprint_doi=paper.reprint_doi,
        source_version_type=paper.source_version_type,
        openalex_id_override=paper.openalex_id_override,
        arxiv_id=paper.arxiv_id,
        semantic_scholar_id=paper.semantic_scholar_id,
        open_access=fields.get("open_access") or paper.open_access,
        citation_count=fields.get("citation_count") or paper.citation_count,
        citation_percentile=fields.get("citation_percentile") or paper.citation_percentile,
        raw_metadata=fields.get("raw_metadata") or paper.raw_metadata,
        fetched_at=now,
    )
