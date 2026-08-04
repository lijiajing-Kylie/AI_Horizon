from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.models import AIConfig, ArxivSourceConfig, Config, PapersConfig
from src.papers import cli
from src.papers.weekly import WeeklyArxivResult
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


def _arxiv_config() -> Config:
    return Config.model_construct(
        ai=AIConfig.model_construct(provider="deepseek"),
        papers=PapersConfig(enabled=True, arxiv=ArxivSourceConfig(enabled=True)),
    )


def test_source_arxiv_runs_weekly_pipeline_only() -> None:
    result = WeeklyArxivResult(fetched=0, after_filter=0, scored=0, featured=[], saved_total=0)

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HuggingFaceFetcher"
    ) as MockHF, patch("src.papers.cli.HorizonDB"), patch(
        "src.papers.cli.create_ai_client"
    ), patch(
        "src.papers.cli.run_weekly_arxiv_all", AsyncMock(return_value={"arxiv": result})
    ) as mock_run:
        asyncio.run(cli.run(_arxiv_config(), only_source="arxiv", dry_run=True))

    mock_run.assert_awaited_once()
    MockOpenAlex.assert_not_called()
    MockHF.assert_not_called()


def test_arxiv_dry_run_does_not_write_db() -> None:
    result = WeeklyArxivResult(fetched=1, after_filter=1, scored=1, featured=[], saved_total=0)

    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch(
        "src.papers.cli.run_weekly_arxiv_all", AsyncMock(return_value={"arxiv": result})
    ):
        code = asyncio.run(cli.run(_arxiv_config(), only_source="arxiv", dry_run=True))

    MockDB.assert_not_called()
    assert code == 0


def test_arxiv_real_run_saves_and_sums_saved_total() -> None:
    result = WeeklyArxivResult(fetched=2, after_filter=2, scored=2, featured=[], saved_total=2)

    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch(
        "src.papers.cli.run_weekly_arxiv_all", AsyncMock(return_value={"arxiv": result})
    ) as mock_run:
        code = asyncio.run(cli.run(_arxiv_config(), only_source="arxiv", dry_run=False))

    MockDB.assert_called_once()
    mock_run.assert_awaited_once()
    assert code == 2


def _paper_row(paper_id: str, *, source: str = "arxiv", is_featured: bool,
               title_zh: str | None = None, ai_summary: object | None = None) -> dict:
    """A get_papers() row dict with the required Paper model fields."""
    return {
        "id": paper_id,
        "source": source,
        "native_id": paper_id.split(":", 1)[1],
        "title": f"Title {paper_id}",
        "authors": ["Alice"],
        "abstract": "An abstract about machine learning with enough length.",
        "url": f"https://arxiv.org/abs/{paper_id}",
        "published_at": "2026-08-03T00:00:00+00:00",
        "updated_at": "2026-08-03T00:00:00+00:00",
        "categories": ["cs.LG"],
        "fetched_at": "2026-08-03T00:00:00+00:00",
        "is_featured": is_featured,
        "title_zh": title_zh,
        "ai_summary": ai_summary,
    }


def test_enrich_existing_backfills_featured_missing_summary() -> None:
    rows = [
        _paper_row("arxiv:1", is_featured=True, ai_summary=None),
        _paper_row("arxiv:2", is_featured=True, ai_summary={"background": "背景"}),
        _paper_row("arxiv:3", is_featured=True, ai_summary={"one_sentence_summary": "新格式"}),
        _paper_row("arxiv:4", is_featured=False, ai_summary=None),
    ]
    mock_ai = AsyncMock()
    mock_ai.config = SimpleNamespace(analysis_concurrency=2)
    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client", return_value=mock_ai
    ), patch("src.papers.cli.enrich_featured", AsyncMock()) as mock_enrich, patch(
        "src.papers.cli.httpx.AsyncClient"
    ):
        db = MockDB.return_value
        db.get_papers.return_value = {"items": rows, "total": len(rows)}
        db.save_papers.return_value = 2

        code = asyncio.run(cli.run(_arxiv_config(), enrich_existing=True))

    assert code == 2
    # Featured papers with a missing OR stale (pre-monolingual) ai_summary are
    # re-enriched; current 11-layer summaries and non-featured rows are skipped.
    args = mock_enrich.call_args[0]
    enriched_papers = args[2]
    assert [p.id for p in enriched_papers] == ["arxiv:1", "arxiv:2"]
    db.save_papers.assert_called_once()


def test_enrich_existing_nothing_missing() -> None:
    rows = [
        _paper_row("arxiv:1", is_featured=True, ai_summary={"one_sentence_summary": "新格式"}),
    ]
    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch("src.papers.cli.enrich_featured", AsyncMock()) as mock_enrich:
        db = MockDB.return_value
        db.get_papers.return_value = {"items": rows, "total": len(rows)}

        code = asyncio.run(cli.run(_arxiv_config(), enrich_existing=True))

    assert code == 0
    mock_enrich.assert_not_called()


def test_translate_existing_only_featured() -> None:
    rows = [
        _paper_row("arxiv:1", is_featured=True, title_zh=None),
        _paper_row("arxiv:2", is_featured=True, title_zh="已翻译"),
        _paper_row("arxiv:3", is_featured=False, title_zh=None),
    ]
    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch("src.papers.cli.translate_papers", AsyncMock()) as mock_translate:
        db = MockDB.return_value
        db.get_papers.return_value = {"items": rows, "total": len(rows)}
        db.save_papers.return_value = 1

        code = asyncio.run(cli.run(_arxiv_config(), translate_existing=True))

    assert code == 1
    # Only the featured paper lacking a title_zh is translated.
    args = mock_translate.call_args[0]
    assert [p.id for p in args[1]] == ["arxiv:1"]
