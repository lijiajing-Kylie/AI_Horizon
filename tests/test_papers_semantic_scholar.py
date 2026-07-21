from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.papers.sources import semantic_scholar


def _response(data: list[dict]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"data": data}
    response.raise_for_status.return_value = None
    return response


def test_search_returns_normalized_top_result() -> None:
    semantic_scholar.clear_cache()
    result_json = {
        "title": "A Classic Paper",
        "abstract": "An abstract.",
        "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
        "year": 2016,
        "externalIds": {"DOI": "10.1/x", "ArXiv": "1512.03385"},
        "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        "venue": "CVPR",
        "paperId": "S2Paper123",
    }
    client = AsyncMock()
    client.get.return_value = _response([result_json])

    result = asyncio.run(semantic_scholar.search(client, "A Classic Paper"))

    assert result["title"] == "A Classic Paper"
    assert result["authors"] == ["Alice Smith", "Bob Jones"]
    assert result["year"] == 2016
    assert result["doi"] == "10.1/x"
    assert result["arxiv_id"] == "1512.03385"
    assert result["pdf_url"] == "https://example.org/paper.pdf"
    assert result["venue"] == "CVPR"
    assert result["semantic_scholar_id"] == "S2Paper123"


def test_search_returns_none_when_no_results() -> None:
    semantic_scholar.clear_cache()
    client = AsyncMock()
    client.get.return_value = _response([])

    result = asyncio.run(semantic_scholar.search(client, "Nonexistent Paper"))

    assert result is None


def test_search_returns_none_on_http_error() -> None:
    semantic_scholar.clear_cache()
    client = AsyncMock()
    client.get.side_effect = httpx.HTTPError("boom")

    result = asyncio.run(semantic_scholar.search(client, "A Classic Paper"))

    assert result is None
