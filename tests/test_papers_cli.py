from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src.models import Config, PapersConfig
from src.papers import cli
from src.papers.models import ClassicFetchResult


def _config() -> Config:
    return Config.model_construct(papers=PapersConfig(enabled=True))


def test_dry_run_never_touches_the_database() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HuggingFaceFetcher"
    ) as MockHF, patch("src.papers.cli.HorizonDB") as MockDB:
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)
        MockHF.return_value.fetch = AsyncMock(return_value=[])

        asyncio.run(cli.run(_config(), dry_run=True))

    MockDB.assert_not_called()


def test_real_run_saves_papers() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HuggingFaceFetcher"
    ) as MockHF, patch("src.papers.cli.HorizonDB") as MockDB:
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)
        MockHF.return_value.fetch = AsyncMock(return_value=[])
        db_instance = MockDB.return_value
        db_instance.save_papers.return_value = 0

        asyncio.run(cli.run(_config(), dry_run=False))

    MockDB.assert_called_once()
    # OpenAlex with no matched papers skips save_papers (only matched papers
    # are persisted). HuggingFace always calls save_papers.
    assert db_instance.save_papers.call_count == 1
    db_instance.save_papers.assert_called_with([])


def test_only_source_openalex_skips_huggingface() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HuggingFaceFetcher"
    ) as MockHF, patch("src.papers.cli.HorizonDB"):
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)

        asyncio.run(cli.run(_config(), only_source="openalex", dry_run=True))

    MockHF.assert_not_called()
