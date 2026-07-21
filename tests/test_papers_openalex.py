from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import OpenAlexSourceConfig
from src.papers.models import Paper
from src.papers.seed_data import SeedPaper
from src.papers.sources.openalex import OpenAlexFetcher


def _work(**overrides) -> dict:
    defaults = dict(
        id="https://openalex.org/W1",
        doi="https://doi.org/10.1109/xyz",
        display_name="A Classic Paper",
        publication_date="2016-06-01",
        publication_year=2016,
        updated_date="2024-01-01T00:00:00.000000",
        cited_by_count=1000,
        is_retracted=False,
        citation_normalized_percentile={"value": 0.995},
        abstract_inverted_index={"An": [0], "abstract.": [1]},
        authorships=[{"author": {"display_name": "Alice Smith"}}],
        primary_location={
            "pdf_url": None,
            "landing_page_url": "https://example.org/w1",
            "source": {"display_name": "CVPR"},
        },
        best_oa_location={"pdf_url": None},
        open_access={"is_oa": True},
        topics=[{"display_name": "Some Topic"}],
    )
    defaults.update(overrides)
    return defaults


def _seed(**overrides) -> SeedPaper:
    defaults = dict(category="Machine Learning", title="A Classic Paper", expected_year=2016)
    defaults.update(overrides)
    return SeedPaper(**defaults)


def _search_response(results: list[dict]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"results": results}
    response.raise_for_status.return_value = None
    return response


def _work_response(work: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = work
    response.raise_for_status.return_value = None
    return response


def _client_returning(response) -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = response
    return client


def _fetcher() -> OpenAlexFetcher:
    return OpenAlexFetcher(OpenAlexSourceConfig())


def _sentinel_paper() -> Paper:
    now = datetime(2016, 1, 1, tzinfo=timezone.utc)
    return Paper(
        id="openalex:seed-fallback",
        source="openalex",
        native_id="A Classic Paper",
        title="A Classic Paper",
        authors=[],
        abstract="",
        url="",
        published_at=now,
        updated_at=now,
        fetched_at=now,
    )


# -- DOI present → accepted directly ---------------------------------------

def test_doi_present_accepted_without_corroboration() -> None:
    client = _client_returning(_search_response([_work()]))
    seed = _seed()

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "doi"
    assert isinstance(paper, Paper)


# -- arXiv-linked without DOI → accepted directly ---------------------------

def test_arxiv_linked_without_doi_accepted_without_corroboration() -> None:
    work = _work(
        doi=None,
        primary_location={"pdf_url": None, "landing_page_url": None, "source": {"display_name": "arXiv"}},
    )
    client = _client_returning(_search_response([work]))
    seed = _seed()

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "arxiv_id"


# -- Local title+year validation (no SS dependency) -------------------------

def test_local_title_year_validation_passes() -> None:
    """When a candidate has no DOI and is not arXiv-linked, it's validated
    locally (title similarity + year match). No external API calls."""
    work = _work(
        doi=None,
        publication_year=2016,
        authorships=[{"author": {"display_name": "Alice Smith"}}],
        primary_location={
            "pdf_url": None,
            "landing_page_url": "https://example.org/w1",
            "source": {"display_name": "Some Journal"},
        },
    )
    client = _client_returning(_search_response([work]))
    seed = _seed()

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "title_year_author"


# -- Title similarity below floor → unmatched --------------------------------

def test_no_candidates_above_similarity_floor_is_unmatched() -> None:
    work = _work(display_name="A Completely Unrelated Title About Gardening")
    client = _client_returning(_search_response([work]))
    seed = _seed()

    paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "unmatched"
    assert paper is not None  # bare-minimum paper still produced
    assert result.enrichment_status == "not_attempted"


# -- Retracted candidate excluded --------------------------------------------

def test_retracted_candidate_is_excluded_from_pool() -> None:
    work = _work(is_retracted=True)
    client = _client_returning(_search_response([work]))
    seed = _seed()

    paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "unmatched"


# -- openalex_id_override ---------------------------------------------------

def test_openalex_id_override_matches_directly() -> None:
    work = _work()
    client = _client_returning(_work_response(work))
    seed = _seed(openalex_id_override="W1")

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "override"


# -- DOI-based seed lookup --------------------------------------------------

def test_seed_with_doi_matches_by_doi_lookup() -> None:
    work = _work(doi="https://doi.org/10.1145/2939672.2939785")
    client = AsyncMock()
    # First call — DOI lookup returns the work
    client.get.return_value = _search_response([work])
    seed = _seed(doi="10.1145/2939672.2939785")

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "doi"


# -- arXiv ID-based seed lookup ---------------------------------------------

def test_seed_with_arxiv_id_matches_by_arxiv_lookup() -> None:
    work = _work(doi="https://doi.org/10.48550/arxiv.1506.02640")
    client = AsyncMock()
    # arXiv DOI form lookup
    client.get.return_value = _search_response([work])
    seed = _seed(arxiv_id="1506.02640")

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert result.match_method == "arxiv_id"


# -- Preprint/published duplicate collapse ----------------------------------

def test_preprint_and_published_duplicate_collapse_to_one_match() -> None:
    preprint = _work(
        id="https://openalex.org/W1",
        publication_year=2015,
        doi="https://doi.org/10.48550/arxiv.1512.03385",
        primary_location={"pdf_url": None, "landing_page_url": None, "source": {"display_name": "arXiv"}},
        cited_by_count=500,
    )
    published = _work(
        id="https://openalex.org/W2",
        publication_year=2016,
        doi="https://doi.org/10.1109/cvpr.2016.90",
        primary_location={
            "pdf_url": None,
            "landing_page_url": "https://example.org/w2",
            "source": {"display_name": "CVPR"},
        },
        cited_by_count=50000,
    )
    client = _client_returning(_search_response([preprint, published]))
    seed = _seed(expected_year=2015)

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "matched"
    assert paper.native_id == "W2"  # published (non-arXiv) record preferred


# -- Two distinct candidates → manual_review --------------------------------

def test_two_distinct_candidates_both_verified_is_manual_review() -> None:
    # Same (seed-matching) title, but far enough apart in year and both DOI-backed
    # that they're genuinely different papers, not a preprint/published pair.
    work_a = _work(id="https://openalex.org/WA", publication_year=2016, doi="https://doi.org/10.1/a")
    work_b = _work(id="https://openalex.org/WB", publication_year=2021, doi="https://doi.org/10.1/b")
    client = _client_returning(_search_response([work_a, work_b]))
    seed = _seed()

    with patch("src.papers.sources.openalex.enrich_paper", new=AsyncMock(return_value=(_sentinel_paper(), "complete"))):
        paper, result = asyncio.run(_fetcher()._match_seed(client, seed))

    assert result.match_status == "manual_review"
    assert "distinct candidates" in result.note
