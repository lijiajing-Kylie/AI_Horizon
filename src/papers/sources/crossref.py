"""Crossref lookup: last resort in the fallback chain for filling gaps in
OpenAlex/Semantic Scholar/arXiv data — strong for DOI/venue metadata on
older, non-arXiv papers (e.g. pre-2000 journal/conference papers).
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

CROSSREF_API_URL = "https://api.crossref.org/works"


async def search(client: httpx.AsyncClient, title: str) -> Optional[Dict[str, Any]]:
    """Search Crossref by title, return the top result as a normalized
    partial-field dict, or None if the query errored or found nothing.
    """
    params = {"query.bibliographic": title, "rows": 1}
    try:
        response = await client.get(CROSSREF_API_URL, params=params, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Error searching Crossref (title=%r): %s", title, e)
        return None

    items = (response.json().get("message") or {}).get("items") or []
    if not items:
        return None
    return _normalize(items[0])


def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    titles = item.get("title") or []
    authors: List[str] = [
        " ".join(part for part in (a.get("given"), a.get("family")) if part)
        for a in (item.get("author") or [])
        if a.get("family")
    ]

    year = None
    date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
    if date_parts:
        year = date_parts[0]

    container = item.get("container-title") or []

    return {
        "title": titles[0] if titles else None,
        "authors": authors,
        "abstract": None,  # Crossref rarely returns abstracts
        "year": year,
        "doi": item.get("DOI"),
        "arxiv_id": None,
        "pdf_url": None,
        "venue": container[0] if container else None,
    }
