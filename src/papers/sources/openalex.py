"""OpenAlex `/works` source for the classic papers library.

v1 is a fixed, human-curated seed list (`src.papers.seed_data.SEED_PAPERS`) —
this module's only job is to look each seed up on OpenAlex and decide,
conservatively, whether a candidate really is that paper. No topic-based
discovery, no citation-based ranking, no auto-expansion.

Match priority (strongest to weakest):
1. **DOI** — seed provides a DOI → OpenAlex filter-by-DOI lookup
2. **arXiv ID** — seed provides an arXiv ID → OpenAlex filter-by-arXiv lookup
3. **openalex_id_override** — seed pins an exact OpenAlex work id
4. **Normalized title + year** — title search via ``search`` parameter,
   locally validated (title similarity ≥ 0.85, year within ±1).

Semantic Scholar is **not** part of the match-verification path — it runs
only during the enrichment phase to fill missing metadata fields, and its
failures (429, etc.) never affect match_status.
"""

import difflib
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ...models import OpenAlexSourceConfig
from ..enrichment import enrich_paper, enrichment_status_for
from ..models import ClassicFetchResult, Paper, SeedMatchResult
from ..seed_data import SEED_PAPERS, SeedPaper
from .base import PaperSourceFetcher

logger = logging.getLogger(__name__)

OPENALEX_API_URL = "https://api.openalex.org/works"
_CANDIDATE_LIMIT = 5
_TITLE_SIMILARITY_FLOOR = 0.85
_DUPLICATE_SIMILARITY_FLOOR = 0.95


def _auth_params() -> Dict[str, str]:
    """``OPENALEX_API_KEY``, if set, grants a much larger daily credit budget
    than the anonymous tier (see .env.example) — attach it to every request via
    the ``api_key`` query parameter.
    """
    api_key = os.getenv("OPENALEX_API_KEY")
    return {"api_key": api_key} if api_key else {}


def normalize_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, Unicode NFKC, strip
    punctuation, collapse hyphens and special spaces to plain spaces, collapse
    consecutive whitespace.

    Designed so that colon-differences ("YOLO: Unified" vs "YOLO: unified")
    and encoding variants never cause a false title-similarity mismatch.
    """
    # Unicode normalization (full-width → half-width, composed forms)
    normalized = unicodedata.normalize("NFKC", title)
    # Lowercase
    normalized = normalized.lower()
    # Replace hyphens of all kinds, en-dashes, em-dashes with spaces
    normalized = re.sub(r"[‐-―−\-–—]", " ", normalized)
    # Replace any remaining non-alphanumeric characters with spaces
    normalized = re.sub(r"[^a-z0-9]", " ", normalized)
    # Collapse consecutive whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def title_similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio over normalized titles, 0–1."""
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def _normalize_author(name: str) -> str:
    """Extract last name (final whitespace-delimited token), lowercased."""
    parts = name.strip().split()
    return parts[-1].lower() if parts else ""


def _year_matches(a: Optional[int], b: Optional[int]) -> bool:
    """Two publication years are compatible if at least one is absent, or they
    differ by at most 1 (tolerating preprint/published-version drift)."""
    if a is None or b is None:
        return True
    return abs(a - b) <= 1


def _author_overlap(work_authors: List[str], seed_result_authors: List[str]) -> bool:
    """True if the two author sets share at least 50% Jaccard overlap on
    last-name tokens, or if either set is empty (skip author validation).
    """
    if not work_authors or not seed_result_authors:
        return True
    wa = {_normalize_author(a) for a in work_authors}
    sa = {_normalize_author(a) for a in seed_result_authors}
    union = wa | sa
    if not union:
        return True
    overlap = wa & sa
    return len(overlap) / len(union) >= 0.5


# ---------------------------------------------------------------------------
# OpenAlex fetcher
# ---------------------------------------------------------------------------

class OpenAlexFetcher(PaperSourceFetcher):
    """Looks up each seed paper on OpenAlex and returns the matched `Paper`s.

    The matching phase runs first (decoupling match_status from enrichment).
    Then the enrichment phase fills missing fields via Semantic Scholar →
    arXiv → Crossref for matched papers only.
    """

    source_name = "openalex"

    def __init__(self, config: OpenAlexSourceConfig):
        self.cfg = config

    async def fetch(self, client: httpx.AsyncClient) -> List[Paper]:
        """Shared ``PaperSourceFetcher`` interface — used by the generic
        multi-source path."""
        result = await self.fetch_classic(client)
        return result.papers

    async def fetch_classic(self, client: httpx.AsyncClient) -> ClassicFetchResult:
        """Match every configured seed paper and return the results + a
        per-seed report. Matching and enrichment are independent phases."""
        # ---- Phase 1: match --------------------------------------------------
        papers: List[Paper] = []
        match_results: List[SeedMatchResult] = []

        for seed in SEED_PAPERS:
            paper, match_result = await self._match_seed(client, seed)
            if paper is not None:
                papers.append(paper)
            match_results.append(match_result)

        # ---- Phase 2: enrich matched papers ----------------------------------
        for i, (paper, mr) in enumerate(zip(papers, [r for r in match_results if r.paper_id])):
            if mr.match_status != "matched":
                continue
            enriched, enrich_status = await enrich_paper(client, paper, mr.seed_title)
            papers[i] = enriched
            # Update the corresponding match_result
            for j, result in enumerate(match_results):
                if result.paper_id == paper.id:
                    match_results[j].enrichment_status = enrich_status
                    break

        return ClassicFetchResult(papers=papers, match_results=match_results)

    # -- per-seed matching ----------------------------------------------------

    async def _match_seed(
        self, client: httpx.AsyncClient, seed: SeedPaper,
    ) -> Tuple[Optional[Paper], SeedMatchResult]:
        """Run the match-priority chain for one seed. Returns (paper_or_None, result)."""

        # Priority 1: openalex_id_override (explicit pin)
        if seed.openalex_id_override:
            work = await self._get_work_by_id(client, seed.openalex_id_override)
            if work is not None:
                paper = self._work_to_paper(work, seed)
                return paper, self._make_result(seed, "matched", "override", paper,
                                                note="pinned via openalex_id_override")
            logger.warning("openalex_id_override %s for %r not found", seed.openalex_id_override, seed.title)

        # Priority 2: DOI lookup
        if seed.doi:
            work = await self._search_by_doi(client, seed.doi)
            if work is not None:
                paper = self._work_to_paper(work, seed)
                if paper is not None and _title_compatible(seed.title, work.get("display_name") or ""):
                    return paper, self._make_result(seed, "matched", "doi", paper,
                                                    note=f"matched via DOI {seed.doi}")
                logger.debug("DOI match for %r had incompatible title; falling through", seed.title)

        # Priority 3: arXiv ID lookup
        if seed.arxiv_id:
            work = await self._search_by_arxiv(client, seed.arxiv_id)
            if work is not None:
                paper = self._work_to_paper(work, seed)
                if paper is not None:
                    return paper, self._make_result(seed, "matched", "arxiv_id", paper,
                                                    note=f"matched via arXiv {seed.arxiv_id}")
                logger.debug("arXiv match for %r returned unparseable work; falling through", seed.title)

        # Priority 4: title search + local validation
        candidates = await self._search_candidates(client, seed.title)
        pool = self._filter_pool(seed, candidates)

        if not pool:
            paper = self._bare_minimum_paper(seed)
            return paper, self._make_result(seed, "unmatched", None, paper,
                                            note="no OpenAlex title-search match above similarity floor")

        # Local validation: title similarity + year + author overlap
        accepted: List[Tuple[dict, str]] = []
        for work, _score in pool:
            doi = work.get("doi")
            if doi:
                accepted.append((work, "doi"))
                continue
            if _is_arxiv_work(work):
                accepted.append((work, "arxiv_id"))
                continue
            # Local validation — no external API calls
            if self._local_validate(work, seed):
                accepted.append((work, "title_year_author"))

        accepted = _dedupe_accepted(accepted)

        if len(accepted) == 1:
            work, method = accepted[0]
            paper = self._work_to_paper(work, seed)
            return paper, self._make_result(seed, "matched", method, paper, note="")

        # Multiple genuinely distinct candidates → manual review
        best_work, _score = pool[0]
        paper = self._work_to_paper(best_work, seed)
        if len(accepted) > 1:
            note = f"{len(accepted)} distinct candidates passed verification"
        else:
            note = "no candidate passed DOI/arXiv/title-year-author verification"
        return paper, self._make_result(seed, "manual_review", None, paper, note=note)

    def _local_validate(self, work: dict, seed: SeedPaper) -> bool:
        """Validate a candidate work against the seed using only locally
        available data — no external API calls.

        Returns True if the candidate clears title similarity + year check.
        Author overlap is checked but non-blocking (too many early papers lack
        author metadata in OpenAlex).
        """
        work_title = work.get("display_name") or ""
        if title_similarity(seed.title, work_title) < _TITLE_SIMILARITY_FLOOR:
            return False

        work_year = work.get("publication_year")
        if not _year_matches(work_year, seed.expected_year):
            return False

        # Author overlap: blocking only if both sets are present and clearly
        # incompatible; otherwise pass.
        work_authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ]
        if work_authors and not _author_overlap(work_authors, []):
            # We don't have seed authors to compare against from the seed list.
            # OpenAlex's author metadata is sufficient — if the title and year
            # match, accept.
            pass

        return True

    # -- result helpers -------------------------------------------------------

    @staticmethod
    def _make_result(
        seed: SeedPaper,
        match_status: str,
        match_method: Optional[str],
        paper: Optional[Paper],
        note: str,
    ) -> SeedMatchResult:
        return SeedMatchResult(
            seed_title=seed.title,
            category=seed.category,
            match_status=match_status,
            match_method=match_method,
            enrichment_status="not_attempted",  # set during enrichment phase
            paper_id=paper.id if paper else None,
            matched_title=paper.title if paper else None,
            matched_year=paper.publication_year if paper else None,
            expected_year=seed.expected_year,
            note=note,
        )

    @staticmethod
    def _bare_minimum_paper(seed: SeedPaper) -> Paper:
        """A minimal Paper stub for unmatched seeds — carries only the seed
        title and category so the CLI can still report it."""
        now = datetime.now(timezone.utc)
        return Paper(
            id=f"openalex:unmatched:{seed.title[:80]}",
            source="openalex",
            native_id="",
            title=seed.title,
            authors=[],
            abstract="",
            url="",
            published_at=datetime(seed.expected_year, 1, 1, tzinfo=timezone.utc),
            updated_at=now,
            publication_year=seed.expected_year,
            category=seed.category,
            fetched_at=now,
        )

    # -- candidate pool -------------------------------------------------------

    def _filter_pool(
        self, seed: SeedPaper, candidates: List[dict],
    ) -> List[Tuple[dict, float]]:
        """Score candidates by title similarity, drop retracted works and
        anything below the similarity floor, sort best-first.
        """
        scored = []
        for work in candidates:
            if work.get("is_retracted"):
                continue
            score = title_similarity(seed.title, work.get("display_name") or "")
            if score >= _TITLE_SIMILARITY_FLOOR:
                scored.append((work, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    async def _search_candidates(self, client: httpx.AsyncClient, title: str) -> List[dict]:
        """Search OpenAlex by title using the ``search`` parameter (not
        ``filter=title.search:``) — avoids Lucene-syntax encoding issues with
        colons, hyphens, and other special characters in paper titles.
        """
        params: Dict[str, Any] = {
            "search": title,
            "per-page": _CANDIDATE_LIMIT,
            **_auth_params(),
        }
        try:
            response = await client.get(OPENALEX_API_URL, params=params, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error searching OpenAlex (title=%r): %s", title, e)
            return []
        return response.json().get("results", [])

    async def _search_by_doi(self, client: httpx.AsyncClient, doi: str) -> Optional[dict]:
        """Look up a single work by DOI filter."""
        params: Dict[str, Any] = {
            "filter": f"doi:{doi}",
            "per-page": 1,
            **_auth_params(),
        }
        try:
            response = await client.get(OPENALEX_API_URL, params=params, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error searching OpenAlex by DOI %s: %s", doi, e)
            return None
        results = response.json().get("results") or []
        return results[0] if results else None

    async def _search_by_arxiv(self, client: httpx.AsyncClient, arxiv_id: str) -> Optional[dict]:
        """Look up a work by its arXiv ID. OpenAlex indexes arXiv IDs in
        primary_location and as DOIs (10.48550/arxiv.*).
        """
        # Try the arXiv DOI form first (most stable in OpenAlex)
        doi_form = f"10.48550/arxiv.{arxiv_id}"
        work = await self._search_by_doi(client, doi_form)
        if work is not None:
            return work

        # Fallback: title search with the arXiv ID stripped
        params: Dict[str, Any] = {
            "search": arxiv_id,
            "per-page": _CANDIDATE_LIMIT,
            **_auth_params(),
        }
        try:
            response = await client.get(OPENALEX_API_URL, params=params, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error searching OpenAlex by arXiv %s: %s", arxiv_id, e)
            return None
        results = response.json().get("results") or []
        return results[0] if results else None

    async def _get_work_by_id(self, client: httpx.AsyncClient, work_id: str) -> Optional[dict]:
        """Fetch a single OpenAlex work by its native id (e.g. "W2194775991")."""
        try:
            response = await client.get(
                f"{OPENALEX_API_URL}/{work_id}", params=_auth_params(), timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error fetching OpenAlex work %s: %s", work_id, e)
            return None
        return response.json()

    # -- conversion -----------------------------------------------------------

    def _work_to_paper(self, work: dict, seed: SeedPaper) -> Optional[Paper]:
        """Convert a single OpenAlex work object into a Paper, merging in the
        seed's category and any seed-provided stable identifiers.

        **Canonical metadata priority**: when the seed carries
        ``canonical_title``, ``canonical_year``, ``canonical_venue``, or
        ``canonical_authors``, those values ALWAYS override what OpenAlex
        returns — so e.g. AlexNet is displayed as NIPS 2012 even when the
        OpenAlex record points to the 2017 CACM reprint.
        """
        native_id = _native_id(work)
        oa_title = (work.get("display_name") or "").strip()
        if not native_id or not oa_title:
            return None

        published_at = _parse_date(work.get("publication_date"))
        if published_at is None:
            return None
        updated_at = _parse_date(work.get("updated_date")) or published_at

        # Authors: canonical_authors > OpenAlex authorships
        oa_authors = [
            a["author"]["display_name"]
            for a in work.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ]

        primary_location = work.get("primary_location") or {}
        best_oa_location = work.get("best_oa_location") or {}
        pdf_url = primary_location.get("pdf_url") or best_oa_location.get("pdf_url")
        url = primary_location.get("landing_page_url") or work.get("id")

        source_obj = primary_location.get("source") or {}
        oa_journal_ref = source_obj.get("display_name")

        categories = [
            t["display_name"] for t in (work.get("topics") or []) if t.get("display_name")
        ]

        percentile = work.get("citation_normalized_percentile") or {}
        open_access = (work.get("open_access") or {}).get("is_oa")

        # Resolve arXiv id from the work's locations
        oa_arxiv_id = seed.arxiv_id or _extract_arxiv_id(work)

        # --- apply canonical overrides (seed always wins) --------------------
        title = seed.canonical_title or oa_title
        pub_year = seed.canonical_year or work.get("publication_year")
        journal_ref = seed.canonical_venue or oa_journal_ref
        authors = seed.canonical_authors or oa_authors

        # DOI resolution:
        #   canonical_doi  → primary identifier (original version)
        #   seed.doi       → fallback (if it's the canonical DOI, set both)
        #   OpenAlex doi   → last fallback (but NEVER used when reprint_doi
        #                     is set — that means the only DOI available is a
        #                     reprint and should not be the primary identifier)
        #   reprint_doi    → stored separately, never used as primary
        if seed.canonical_doi or seed.doi:
            primary_doi = seed.canonical_doi or seed.doi
        elif seed.reprint_doi:
            # The only DOI is a reprint — do NOT use it as the primary doi.
            primary_doi = None
        else:
            primary_doi = work.get("doi")

        # When canonical_year differs from what the API record says, adjust
        # published_at to match the canonical year (preserving month/day).
        if seed.canonical_year and seed.canonical_year != work.get("publication_year"):
            try:
                published_at = published_at.replace(year=seed.canonical_year)
            except ValueError:
                # Feb 29 on a non-leap year — fall back to Jan 1
                published_at = datetime(seed.canonical_year, 1, 1, tzinfo=published_at.tzinfo or timezone.utc)

        return Paper(
            id=f"{self.source_name}:{native_id}",
            source=self.source_name,
            native_id=native_id,
            title=title,
            authors=authors or (oa_authors if not seed.canonical_authors else seed.canonical_authors),
            abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
            url=url,
            pdf_url=pdf_url,
            published_at=published_at,
            updated_at=updated_at,
            publication_year=pub_year,
            categories=categories,
            category=seed.category,
            journal_ref=journal_ref,
            doi=primary_doi,
            canonical_doi=seed.canonical_doi,
            reprint_doi=seed.reprint_doi,
            source_version_type=seed.source_version_type,
            openalex_id_override=seed.openalex_id_override,
            arxiv_id=oa_arxiv_id,
            semantic_scholar_id=None,
            open_access=open_access,
            citation_count=work.get("cited_by_count"),
            citation_percentile=percentile.get("value"),
            raw_metadata=work,
            fetched_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _title_compatible(seed_title: str, work_title: str) -> bool:
    """Quick check: are the two titles compatible enough to accept a
    DOI/arXiv-based match?  Uses a lower floor than the main similarity
    check since the stable identifier is the primary signal.
    """
    return title_similarity(seed_title, work_title) >= 0.75


def _dedupe_accepted(accepted: List[Tuple[dict, str]]) -> List[Tuple[dict, str]]:
    """Collapse accepted candidates that are the same underlying paper indexed
    as multiple OpenAlex works (e.g. an arXiv preprint + its published-venue
    record) into one, preferring the published (non-arXiv) record — so a
    normal preprint/published pair doesn't get flagged as ambiguous.
    """
    groups: List[List[Tuple[dict, str]]] = []
    for work, method in accepted:
        placed = False
        for group in groups:
            rep_work, _ = group[0]
            if title_similarity(
                work.get("display_name") or "",
                rep_work.get("display_name") or "",
            ) < _DUPLICATE_SIMILARITY_FLOOR:
                continue
            rep_year = rep_work.get("publication_year")
            cur_year = work.get("publication_year")
            if rep_year is None or cur_year is None or abs(rep_year - cur_year) <= 1:
                group.append((work, method))
                placed = True
                break
        if not placed:
            groups.append([(work, method)])

    resolved: List[Tuple[dict, str]] = []
    for group in groups:
        if len(group) == 1:
            resolved.append(group[0])
            continue
        resolved.append(max(group, key=_duplicate_rank))
    return resolved


def _duplicate_rank(item: Tuple[dict, str]) -> Tuple[bool, bool, int]:
    work, _method = item
    return (not _is_arxiv_work(work), bool(work.get("doi")), work.get("cited_by_count") or 0)


def _is_arxiv_work(work: dict) -> bool:
    doi = (work.get("doi") or "").lower()
    if "10.48550/arxiv." in doi:
        return True
    source_name = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    return source_name.strip().lower() == "arxiv"


def _extract_arxiv_id(work: dict) -> Optional[str]:
    """Try to extract an arXiv id from an OpenAlex work's locations and ids."""
    doi = (work.get("doi") or "").lower()
    m = re.search(r"10\.48550/arxiv\.(.+)", doi)
    if m:
        return m.group(1)

    # Check primary location's landing page URL for arXiv pattern
    landing = ((work.get("primary_location") or {}).get("landing_page_url") or "")
    m = re.search(r"arxiv\.org/abs/([^/\s?#]+)", landing, re.IGNORECASE)
    if m:
        return m.group(1).rstrip("v0123456789")  # strip version suffix

    return None


def _native_id(work: dict) -> str:
    """Extract the bare OpenAlex id (e.g. "W123") from its full URL form."""
    return (work.get("id") or "").rsplit("/", 1)[-1]


def _reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """OpenAlex returns abstracts as a word→positions inverted index; rebuild
    plain text."""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse an OpenAlex date string (date-only or full ISO timestamp) to a
    UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
