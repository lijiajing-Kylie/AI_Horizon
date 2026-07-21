from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.models import PapersConfig
from src.papers.fetcher import fetch_all_papers
from src.papers.models import Paper


def _paper(id_: str, published_at: datetime) -> Paper:
    return Paper(
        id=id_,
        source=id_.split(":")[0],
        native_id=id_.split(":")[1],
        title=f"Paper {id_}",
        authors=["Someone"],
        abstract="An abstract.",
        url="https://example.org",
        published_at=published_at,
        updated_at=published_at,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetcher_returning(papers: list[Paper]) -> AsyncMock:
    fetcher = AsyncMock()
    fetcher.fetch.return_value = papers
    return fetcher


def test_fetch_all_papers_merges_and_sorts_by_published_at() -> None:
    openalex_papers = [_paper("openalex:W1", datetime(2020, 1, 1, tzinfo=timezone.utc))]
    hf_papers = [_paper("huggingface:2501.1", datetime(2026, 6, 1, tzinfo=timezone.utc))]

    with patch("src.papers.fetcher.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.fetcher.HuggingFaceFetcher"
    ) as MockHF:
        MockOpenAlex.return_value = _fetcher_returning(openalex_papers)
        MockHF.return_value = _fetcher_returning(hf_papers)

        config = PapersConfig(enabled=True)
        papers = asyncio.run(fetch_all_papers(config, client=None))

    assert [p.id for p in papers] == ["huggingface:2501.1", "openalex:W1"]


def test_disabled_source_is_not_fetched() -> None:
    config = PapersConfig(enabled=True)
    config.huggingface.enabled = False

    with patch("src.papers.fetcher.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.fetcher.HuggingFaceFetcher"
    ) as MockHF:
        MockOpenAlex.return_value = _fetcher_returning([])
        asyncio.run(fetch_all_papers(config, client=None))

    MockHF.assert_not_called()


def test_only_source_restricts_to_one_fetcher() -> None:
    config = PapersConfig(enabled=True)

    with patch("src.papers.fetcher.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.fetcher.HuggingFaceFetcher"
    ) as MockHF:
        MockOpenAlex.return_value = _fetcher_returning([])
        asyncio.run(fetch_all_papers(config, client=None, only_source="openalex"))

    MockOpenAlex.assert_called_once()
    MockHF.assert_not_called()
