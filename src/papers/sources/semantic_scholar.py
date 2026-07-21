"""Semantic Scholar lookup: fills gaps in metadata and optionally corroborates
a title-search match. Runs as enrichment only (non-blocking for match_status).

Public Graph API — an API key grants higher rate limits. Without a key the
anonymous tier is ~1 req/s with bursts; with a key (from env
``SEMANTIC_SCHOLAR_API_KEY``) the limit is substantially higher.

Rate limiting (1 req/s), exponential backoff on 429, Retry-After header
support, and an in-memory per-session cache are all built in so transient
429s never cascade into match failures.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS = "title,abstract,authors,year,externalIds,openAccessPdf,venue,citationCount,publicationTypes"
_MAX_RETRIES = 3
_RATE_INTERVAL = 1.0  # seconds between requests (anonymous tier safe default)

# ---- per-session in-memory cache -------------------------------------------
# Keyed by normalized title; survives across calls within one CLI invocation.
_cache: Dict[str, Optional[Dict[str, Any]]] = {}
_last_request_time: float = 0.0
_had_rate_limit: bool = False


def clear_cache() -> None:
    """Clear the in-memory per-session cache. Useful for tests."""
    global _had_rate_limit
    _cache.clear()
    _had_rate_limit = False


def had_rate_limit() -> bool:
    """True if any call in this session hit a 429 response."""
    return _had_rate_limit


def _api_key_header() -> Dict[str, str]:
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


async def _rate_limit() -> None:
    """Ensure at least ``_RATE_INTERVAL`` seconds between requests."""
    global _last_request_time
    now = time.monotonic()
    wait = _last_request_time + _RATE_INTERVAL - now
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_time = time.monotonic()


def _cache_key(title: str) -> str:
    """Normalize a title string for cache lookup."""
    return title.strip().lower()


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any],
    timeout: float = 30.0,
) -> Optional[httpx.Response]:
    """GET *url* with rate limiting and exponential-backoff retry on 429."""
    headers = _api_key_header()
    for attempt in range(_MAX_RETRIES + 1):
        await _rate_limit()
        try:
            response = await client.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429:
                global _had_rate_limit
                _had_rate_limit = True
                retry_after = None
                ra = response.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        pass
                if retry_after is None:
                    retry_after = 2 ** attempt  # exponential backoff: 1, 2, 4
                logger.warning(
                    "Semantic Scholar 429 (attempt %d/%d); waiting %.0fs",
                    attempt + 1, _MAX_RETRIES + 1, retry_after,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(retry_after)
                    continue
                return None
            response.raise_for_status()
            return response
        except httpx.HTTPError as e:
            logger.warning("Semantic Scholar request error (attempt %d): %s", attempt + 1, e)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
                continue
            return None
    return None


async def search(client: httpx.AsyncClient, title: str) -> Optional[Dict[str, Any]]:
    """Search Semantic Scholar by title, return the top result as a normalized
    partial-field dict, or None if the query errored or found nothing.

    Results are cached in-memory per session — identical titles only hit the
    API once.
    """
    ck = _cache_key(title)
    if ck in _cache:
        logger.debug("Semantic Scholar cache hit for %r", title)
        return _cache[ck]

    params: Dict[str, Any] = {"query": title, "fields": _FIELDS, "limit": 1}
    response = await _get_with_retry(client, SEMANTIC_SCHOLAR_API_URL, params)
    if response is None:
        _cache[ck] = None
        return None

    data = response.json().get("data") or []
    if not data:
        _cache[ck] = None
        return None

    result = _normalize(data[0])
    _cache[ck] = result
    return result


async def search_batch(
    client: httpx.AsyncClient,
    titles: List[str],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch metadata for multiple titles via the bulk endpoint, which is far
    more efficient than per-title ``search()`` calls.

    Returns a dict mapping each *original* title to its normalized result
    (or None if not found / errored).
    """
    # Check cache first; only query uncached titles.
    uncached: List[str] = []
    results: Dict[str, Optional[Dict[str, Any]]] = {}
    for t in titles:
        ck = _cache_key(t)
        if ck in _cache:
            results[t] = _cache[ck]
        else:
            uncached.append(t)

    if not uncached:
        return results

    # Batch fetch — one POST per uncached title for now (the bulk endpoint
    # accepts a single query at a time in its simplest form).  For many titles
    # this is still bounded by rate limiting.
    for title in uncached:
        ck = _cache_key(title)
        if ck in _cache:  # double-checked (another batch caller may have filled it)
            results[title] = _cache[ck]
            continue

        # Use the bulk endpoint — POST with a JSON body.
        headers = _api_key_header()
        headers["Content-Type"] = "application/json"
        payload = {"query": title, "fields": _FIELDS, "limit": 1}

        for attempt in range(_MAX_RETRIES + 1):
            await _rate_limit()
            try:
                response = await client.post(
                    SEMANTIC_SCHOLAR_BATCH_URL,
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )
                if response.status_code == 429:
                    ra = response.headers.get("Retry-After")
                    retry_after = float(ra) if ra else 2 ** attempt
                    logger.warning(
                        "Semantic Scholar batch 429 (attempt %d); waiting %.0fs",
                        attempt + 1, retry_after,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(retry_after)
                        continue
                    _cache[ck] = None
                    results[title] = None
                    break
                response.raise_for_status()
                data = response.json().get("data") or []
                if not data:
                    _cache[ck] = None
                    results[title] = None
                else:
                    normalized = _normalize(data[0])
                    _cache[ck] = normalized
                    results[title] = normalized
                break
            except httpx.HTTPError as e:
                logger.warning("Semantic Scholar batch error (attempt %d): %s", attempt + 1, e)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
                    continue
                _cache[ck] = None
                results[title] = None
                break

    return results


def _normalize(result: Dict[str, Any]) -> Dict[str, Any]:
    external_ids = result.get("externalIds") or {}
    authors: List[str] = [a["name"] for a in (result.get("authors") or []) if a.get("name")]
    open_access_pdf = result.get("openAccessPdf") or {}

    return {
        "title": result.get("title"),
        "authors": authors,
        "abstract": result.get("abstract"),
        "year": result.get("year"),
        "doi": external_ids.get("DOI"),
        "arxiv_id": external_ids.get("ArXiv"),
        "semantic_scholar_id": result.get("paperId"),
        "pdf_url": open_access_pdf.get("url"),
        "venue": result.get("venue") or None,
        "citation_count": result.get("citationCount"),
    }
