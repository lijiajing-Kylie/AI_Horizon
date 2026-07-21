from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.papers.enrichment import REQUIRED_FIELDS, enrich_paper, enrichment_status_for, missing_fields
from src.papers.models import Paper


def _complete_paper(**overrides) -> Paper:
    now = datetime(2016, 1, 1, tzinfo=timezone.utc)
    defaults = dict(
        id="openalex:W1",
        source="openalex",
        native_id="W1",
        title="A Classic Paper",
        authors=["Alice Smith"],
        abstract="An abstract.",
        url="https://example.org/w1",
        published_at=now,
        updated_at=now,
        publication_year=2016,
        doi="https://doi.org/10.1/x",
        journal_ref="CVPR",
        fetched_at=now,
    )
    defaults.update(overrides)
    return Paper(**defaults)


def test_missing_fields_complete_paper_returns_empty() -> None:
    assert missing_fields(_complete_paper()) == []


def test_missing_fields_reports_only_blank_fields() -> None:
    paper = _complete_paper(doi=None, journal_ref="")
    assert set(missing_fields(paper)) == {"doi", "journal_ref"}


def test_enrich_paper_already_complete_returns_complete_status() -> None:
    paper = _complete_paper()
    client = AsyncMock()

    with patch("src.papers.enrichment.semantic_scholar.search", new=AsyncMock()) as mock_ss, patch(
        "src.papers.enrichment.arxiv.search", new=AsyncMock()
    ) as mock_arxiv, patch("src.papers.enrichment.crossref.search", new=AsyncMock()) as mock_crossref:
        result, status = asyncio.run(enrich_paper(client, paper, "A Classic Paper"))

    mock_ss.assert_not_called()
    mock_arxiv.assert_not_called()
    mock_crossref.assert_not_called()
    assert status == "complete"
    assert result.doi == paper.doi


def test_enrich_paper_first_source_fills_everything_skips_rest() -> None:
    paper = _complete_paper(doi=None)
    client = AsyncMock()
    ss_result = {
        "title": "A Classic Paper", "authors": ["Alice Smith"], "abstract": "An abstract.",
        "year": 2016, "doi": "10.1/from-ss", "arxiv_id": None, "pdf_url": None, "venue": "CVPR",
        "semantic_scholar_id": "S2Paper123",
    }

    with patch("src.papers.enrichment.semantic_scholar.search", new=AsyncMock(return_value=ss_result)), patch(
        "src.papers.enrichment.arxiv.search", new=AsyncMock()
    ) as mock_arxiv, patch("src.papers.enrichment.crossref.search", new=AsyncMock()) as mock_crossref:
        result, status = asyncio.run(enrich_paper(client, paper, "A Classic Paper"))

    assert result.doi == "10.1/from-ss"
    assert status == "complete"
    mock_arxiv.assert_not_called()
    mock_crossref.assert_not_called()


def test_enrich_paper_never_overwrites_existing_fields() -> None:
    paper = _complete_paper(doi=None)
    client = AsyncMock()
    ss_result = {
        "title": "A Different Title", "authors": ["Someone Else"], "abstract": "A different abstract.",
        "year": 1999, "doi": "10.1/from-ss", "arxiv_id": None, "pdf_url": None, "venue": "Some Other Venue",
    }

    with patch("src.papers.enrichment.semantic_scholar.search", new=AsyncMock(return_value=ss_result)):
        result, status = asyncio.run(enrich_paper(client, paper, "A Classic Paper"))

    # Only the field that was actually missing (doi) gets filled.
    assert result.doi == "10.1/from-ss"
    assert result.title == "A Classic Paper"
    assert result.authors == ["Alice Smith"]
    assert result.abstract == "An abstract."
    assert result.publication_year == 2016
    assert result.journal_ref == "CVPR"
    assert status == "complete"


def test_enrich_paper_falls_through_chain_when_earlier_sources_miss() -> None:
    paper = _complete_paper(doi=None)
    client = AsyncMock()
    arxiv_result = {
        "title": "A Classic Paper", "authors": ["Alice Smith"], "abstract": "An abstract.",
        "year": 2016, "doi": None, "arxiv_id": "1512.03385", "pdf_url": "https://arxiv.org/pdf/1512.03385",
        "venue": "arXiv",
    }
    crossref_result = {
        "title": "A Classic Paper", "authors": ["Alice Smith"], "abstract": None,
        "year": 2016, "doi": "10.1/from-crossref", "arxiv_id": None, "pdf_url": None, "venue": "CVPR",
    }

    with patch("src.papers.enrichment.semantic_scholar.search", new=AsyncMock(return_value=None)), patch(
        "src.papers.enrichment.arxiv.search", new=AsyncMock(return_value=arxiv_result)
    ), patch("src.papers.enrichment.crossref.search", new=AsyncMock(return_value=crossref_result)) as mock_crossref:
        result, status = asyncio.run(enrich_paper(client, paper, "A Classic Paper"))

    # arxiv filled pdf_url but not doi -> chain continues to crossref for doi.
    assert result.pdf_url == "https://arxiv.org/pdf/1512.03385"
    assert result.doi == "10.1/from-crossref"
    mock_crossref.assert_called_once()
    assert status == "complete"


def test_enrich_paper_all_sources_fail_returns_failed_status() -> None:
    paper = _complete_paper(doi=None, journal_ref=None)
    client = AsyncMock()

    with patch("src.papers.enrichment.semantic_scholar.search", new=AsyncMock(return_value=None)), patch(
        "src.papers.enrichment.arxiv.search", new=AsyncMock(return_value=None)
    ), patch("src.papers.enrichment.crossref.search", new=AsyncMock(return_value=None)):
        result, status = asyncio.run(enrich_paper(client, paper, "A Classic Paper"))

    assert status == "failed"


def test_enrichment_status_for_complete_paper() -> None:
    paper = _complete_paper()
    assert enrichment_status_for(paper) == "complete"


def test_enrichment_status_for_incomplete_paper() -> None:
    paper = _complete_paper(doi=None)
    assert enrichment_status_for(paper) == "not_attempted"
