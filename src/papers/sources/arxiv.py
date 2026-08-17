"""arXiv lookup: fills gaps in OpenAlex/Semantic Scholar data for papers that
have an arXiv preprint, and provides the daily-category listing used by the
arXiv weekly-featured pipeline. Uses the public Atom-feed API (no key required).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import httpx

from ..latex import latex_to_unicode
from ..models import Paper

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"  # arXiv redirects http -> https; go direct
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# arXiv API returns at most ~100 results per page; use 50 for safer batch
# size to reduce the chance of triggering server-side limits.
_BATCH_SIZE = 50
# arXiv's terms: "no more than one request per three seconds"
_INTER_BATCH_DELAY = 3.1
# Spacing between category-listing requests (fetch_recent). arXiv soft-throttles
# bursts of category queries: 11-12 categories at 3.1s spacing empirically came
# back as empty feeds, while 6.0s spacing returned data for every category.
# Listing is the burst-heavy path, so it gets its own (larger) delay; id lookups
# keep the documented minimum.
_CATEGORY_LISTING_DELAY = 6.0
# Per-category fetch retry budget for 429 / transient transport errors. arXiv
# throttles bursts of category queries (a run may fetch 10+ categories), and a
# reset/truncated connection currently surfaces as an empty feed — retrying with
# backoff keeps those categories from silently dropping out.
_MAX_CATEGORY_RETRIES = 3


async def search(client: httpx.AsyncClient, title: str) -> Optional[Dict[str, Any]]:
    """Search arXiv by title, return the top result as a normalized
    partial-field dict, or None if the query errored or found nothing.
    """
    escaped = title.replace('"', "")
    params = {"search_query": f'ti:"{escaped}"', "start": 0, "max_results": 1}
    try:
        response = await client.get(ARXIV_API_URL, params=params, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Error searching arXiv (title=%r): %s", title, e)
        return None

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as e:
        logger.warning("Error parsing arXiv response (title=%r): %s", title, e)
        return None

    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        return None
    return _normalize(entry)


async def lookup_by_ids(
    client: httpx.AsyncClient,
    arxiv_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Batch-lookup papers by arXiv ID. Returns a dict keyed by arXiv ID (without
    version suffix), each value a normalized partial-field dict like `_normalize`
    produces. Handles paging automatically when more than ~100 IDs are passed.
    """
    if not arxiv_ids:
        return {}

    # The API accepts comma-separated IDs via `id_list`. If the list is
    # extremely long the response may be truncated, so batch it.
    # Respect arXiv's rate limit with a delay between batches.
    results: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(arxiv_ids), _BATCH_SIZE):
        batch = arxiv_ids[i : i + _BATCH_SIZE]
        batch_results = await _lookup_batch(client, batch)
        results.update(batch_results)
        if i + _BATCH_SIZE < len(arxiv_ids):
            await asyncio.sleep(_INTER_BATCH_DELAY)
    return results


async def _lookup_batch(
    client: httpx.AsyncClient,
    arxiv_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Fetch a single batch of arXiv IDs, retrying with smaller sub-batches on 429."""
    if not arxiv_ids:
        return {}

    id_list = ",".join(arxiv_ids)
    params: Dict[str, str] = {
        "id_list": id_list,
        "max_results": str(len(arxiv_ids)),
    }
    try:
        response = await client.get(ARXIV_API_URL, params=params, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429 and len(arxiv_ids) > 1:
            retry_after = int(e.response.headers.get("Retry-After", "3"))
            logger.warning(
                "arXiv 429 on %d ids, splitting and retrying after %ds",
                len(arxiv_ids), retry_after,
            )
            await asyncio.sleep(retry_after)
            # Split into two halves and retry each half recursively
            mid = len(arxiv_ids) // 2
            left = await _lookup_batch(client, arxiv_ids[:mid])
            if left:
                await asyncio.sleep(_INTER_BATCH_DELAY)
            right = await _lookup_batch(client, arxiv_ids[mid:])
            result: Dict[str, Dict[str, Any]] = {}
            if left:
                result.update(left)
            if right:
                result.update(right)
            return result
        else:
            logger.warning("Error looking up arXiv batch (%d ids): %s", len(arxiv_ids), e)
            return {}
    except httpx.HTTPError as e:
        logger.warning("Error looking up arXiv batch (%d ids): %s", len(arxiv_ids), e)
        return {}

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as e:
        logger.warning("Error parsing arXiv batch response: %s", e)
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    for entry in root.findall(f"{_ATOM_NS}entry"):
        normalized = _normalize(entry)
        aid = normalized.get("arxiv_id")
        if aid:
            results[aid] = normalized
    return results


def _normalize(entry: ElementTree.Element) -> Dict[str, Any]:
    entry_title = _text(entry, "title")
    summary = _text(entry, "summary")
    published = _text(entry, "published")  # e.g. "2015-12-10T00:00:00Z"
    year = int(published[:4]) if published and published[:4].isdigit() else None

    authors: List[str] = [
        _text(a, "name") for a in entry.findall(f"{_ATOM_NS}author") if _text(a, "name")
    ]

    arxiv_id = None
    entry_id = _text(entry, "id")  # e.g. "http://arxiv.org/abs/1512.03385v1"
    if entry_id:
        match = re.search(r"abs/([^v]+)", entry_id)
        if match:
            arxiv_id = match.group(1)

    pdf_url = None
    for link in entry.findall(f"{_ATOM_NS}link"):
        if link.get("title") == "pdf":
            pdf_url = link.get("href")
            break
    if pdf_url is None and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    # arXiv-specific metadata (namespace: http://arxiv.org/schemas/atom)
    journal_ref = _arxiv_text(entry, "journal_ref")
    comment = _arxiv_text(entry, "comment")

    # Categories: standard Atom <category term="..."> plus the primary category
    categories: List[str] = []
    for cat in entry.findall(f"{_ATOM_NS}category"):
        term = cat.get("term")
        if term:
            categories.append(term)

    primary_category: Optional[str] = None
    primary_el = entry.find(f"{_ARXIV_NS}primary_category")
    if primary_el is not None:
        primary_category = primary_el.get("term")

    return {
        "title": entry_title,
        "authors": authors,
        "abstract": summary.strip() if summary else None,
        "year": year,
        "doi": None,
        "arxiv_id": arxiv_id,
        "pdf_url": pdf_url,
        "venue": "arXiv" if arxiv_id else None,
        "journal_ref": journal_ref,
        "comment": comment,
        "categories": categories,
        "primary_category": primary_category,
        "published_at": published,  # full ISO timestamp, e.g. "2015-12-10T00:00:00Z"
        "updated_at": _text(entry, "updated"),
    }


def _text(element: ElementTree.Element, tag: str) -> Optional[str]:
    child = element.find(f"{_ATOM_NS}{tag}")
    return child.text.strip() if child is not None and child.text else None


def _arxiv_text(element: ElementTree.Element, tag: str) -> Optional[str]:
    """Extract text from an element in the arXiv namespace."""
    child = element.find(f"{_ARXIV_NS}{tag}")
    return child.text.strip() if child is not None and child.text else None


def _parse_dt(iso: Optional[str]) -> Optional[datetime]:
    """Parse an arXiv ISO timestamp to an aware UTC datetime.

    Accepts trailing ``Z`` (Python 3.11+ ``fromisoformat`` handles it).
    Returns None for missing/unparseable input.
    """
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def fetch_recent(
    client: httpx.AsyncClient,
    categories: List[str],
    max_results_per_category: int = 50,
) -> List[Paper]:
    """Fetch the newest papers per arXiv category and return them as ``Paper``s.

    Queries ``search_query=cat:{cat}`` sorted by submission date descending.
    Requests are serial across categories and rate-limited (≥3.1 s apart) to
    respect arXiv's terms of use; 429 responses are retried with the
    ``Retry-After`` header.

    Cross-category duplicates are merged by arXiv id, keeping the entry that
    lists the most categories. Papers without an id/title are skipped.
    """
    if not categories:
        return []

    merged: Dict[str, Paper] = {}
    for i, cat in enumerate(categories):
        if i > 0:
            await asyncio.sleep(_CATEGORY_LISTING_DELAY)
        entries = await _fetch_category(client, cat, max_results_per_category)
        for normalized in entries:
            paper = _entry_to_paper(normalized)
            if paper is None:
                continue
            existing = merged.get(paper.id)
            if existing is None or len(paper.categories) > len(existing.categories):
                merged[paper.id] = paper

    return sorted(
        merged.values(),
        key=lambda p: p.published_at,
        reverse=True,
    )


async def _fetch_category(
    client: httpx.AsyncClient,
    category: str,
    max_results: int,
    _attempts: int = 0,
) -> List[Dict[str, Any]]:
    """Fetch one category's newest entries, retrying on throttling failures.

    arXiv throttles bursts of category queries (a run may fetch 10+ categories);
    failures surface as 429s, reset/truncated connections, or 200 responses with
    no entries. Every failure retries with an increasing backoff (429s also halve
    the batch) within the ``_MAX_CATEGORY_RETRIES`` budget, so a flaky category
    degrades gracefully instead of silently dropping out of the combined fetch.
    """
    params: Dict[str, str] = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
        "start": "0",
    }
    retry_after: Optional[int] = None
    error: Optional[str] = None
    try:
        response = await client.get(ARXIV_API_URL, params=params, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429 and max_results > 1:
            retry_after = int(e.response.headers.get("Retry-After", "3"))
            error = f"429 (retry in {retry_after}s)"
        else:
            error = str(e)
    except httpx.HTTPError as e:
        error = str(e)

    entries: List[Dict[str, Any]] = []
    if error is None:
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as e:
            error = f"parse error: {e}"
        else:
            entries = [_normalize(entry) for entry in root.findall(f"{_ATOM_NS}entry")]

    # Retry failures and empty feeds with backoff. An empty feed is treated as
    # throttling — a category that normally has thousands of papers returning
    # zero within a recent window is far more likely throttled than genuinely
    # empty, and retrying it costs only backoff time.
    if error is not None or not entries:
        if _attempts < _MAX_CATEGORY_RETRIES:
            backoff = retry_after if retry_after is not None else _CATEGORY_LISTING_DELAY * (_attempts + 1)
            logger.warning(
                "Retrying arXiv cat=%s after %s (attempt %d/%d) in %.1fs",
                category, error or "empty feed", _attempts + 1, _MAX_CATEGORY_RETRIES, backoff,
            )
            await asyncio.sleep(backoff)
            next_batch = max_results // 2 if retry_after is not None else max_results
            return await _fetch_category(client, category, next_batch, _attempts + 1)
        logger.warning("Error fetching arXiv cat=%s: %s", category, error or "empty feed")
        return []

    return entries


def _entry_to_paper(normalized: Dict[str, Any]) -> Optional[Paper]:
    """Convert a ``_normalize`` output dict into a ``Paper`` (source="arxiv")."""
    arxiv_id = normalized.get("arxiv_id")
    title = latex_to_unicode((normalized.get("title") or "").strip())
    if not arxiv_id or not title:
        return None

    published_dt = _parse_dt(normalized.get("published_at")) or datetime.now(timezone.utc)
    updated_dt = _parse_dt(normalized.get("updated_at")) or published_dt

    return Paper(
        id=f"arxiv:{arxiv_id}",
        source="arxiv",
        native_id=arxiv_id,
        title=title,
        authors=normalized.get("authors") or [],
        abstract=latex_to_unicode((normalized.get("abstract") or "").strip()),
        url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=normalized.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}",
        published_at=published_dt,
        updated_at=updated_dt,
        publication_year=published_dt.year,
        categories=normalized.get("categories") or [],
        category=normalized.get("primary_category"),
        comment=normalized.get("comment"),
        journal_ref=normalized.get("journal_ref"),
        arxiv_id=arxiv_id,
        fetched_at=datetime.now(timezone.utc),
        raw_metadata=normalized,
    )
