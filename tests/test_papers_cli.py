from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.models import AIConfig, ArxivSourceConfig, Config, PapersConfig
from src.papers import cli
from src.papers.weekly import AI_SUMMARY_VERSION, WeeklyArxivResult
from src.papers.models import ClassicFetchResult, Paper, SeedMatchResult


def _config() -> Config:
    return Config.model_construct(papers=PapersConfig(enabled=True))


def test_dry_run_never_touches_the_database() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HorizonDB"
    ) as MockDB:
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)

        asyncio.run(cli.run(_config(), dry_run=True))

    MockDB.assert_not_called()


def test_real_run_with_no_matched_papers_skips_save() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HorizonDB"
    ) as MockDB:
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)
        db_instance = MockDB.return_value
        db_instance.save_papers.return_value = 0

        asyncio.run(cli.run(_config(), dry_run=False))

    MockDB.assert_called_once()
    # OpenAlex with no matched papers skips save_papers (only matched papers
    # are persisted).
    assert db_instance.save_papers.call_count == 0


def test_only_source_restricts_to_openalex() -> None:
    empty_result = ClassicFetchResult(papers=[], match_results=[])

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.run_weekly_arxiv_all"
    ) as MockArxiv, patch("src.papers.cli.HorizonDB"):
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=empty_result)

        asyncio.run(cli.run(_arxiv_config(), only_source="openalex", dry_run=True))

    MockArxiv.assert_not_called()
    MockOpenAlex.assert_called_once()


def _arxiv_config() -> Config:
    return Config.model_construct(
        ai=AIConfig.model_construct(provider="deepseek"),
        papers=PapersConfig(enabled=True, arxiv=ArxivSourceConfig(enabled=True)),
    )


def test_source_arxiv_runs_weekly_pipeline_only() -> None:
    result = WeeklyArxivResult(fetched=0, after_filter=0, scored=0, featured=[], saved_total=0)

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HorizonDB"
    ), patch(
        "src.papers.cli.create_ai_client"
    ), patch(
        "src.papers.cli.run_weekly_arxiv_all", AsyncMock(return_value={"arxiv": result})
    ) as mock_run:
        asyncio.run(cli.run(_arxiv_config(), only_source="arxiv", dry_run=True))

    mock_run.assert_awaited_once()
    MockOpenAlex.assert_not_called()


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
        _paper_row("arxiv:3", is_featured=True, ai_summary={
            "one_sentence_summary": "新格式",
            "core_idea": "核心",
            "technical_details": "细节",
            "experimental_evidence": "证据",
            "limitations": "局限",
            "interpretation_version": AI_SUMMARY_VERSION,
        }),
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
        _paper_row("arxiv:1", is_featured=True, ai_summary={
            "one_sentence_summary": "新格式",
            "core_idea": "核心",
            "technical_details": "细节",
            "experimental_evidence": "证据",
            "limitations": "局限",
            "interpretation_version": AI_SUMMARY_VERSION,
        }),
    ]
    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch("src.papers.cli.enrich_featured", AsyncMock()) as mock_enrich:
        db = MockDB.return_value
        db.get_papers.return_value = {"items": rows, "total": len(rows)}

        code = asyncio.run(cli.run(_arxiv_config(), enrich_existing=True))

    assert code == 0
    mock_enrich.assert_not_called()


def test_ai_summary_stale_versions() -> None:
    """_ai_summary_stale 判定兼容矩阵：缺失/双语/旧单层/旧版本/版本达标但缺
    核心字段（分段失败）为 stale，完整且当前版本为 fresh。"""
    stale_cases = [
        None,
        "not-a-dict",
        {"zh": {"one_sentence_summary": "..."}, "en": {"one_sentence_summary": "..."}},
        {"background": "旧单层"},
        # 现网行（无版本号 → 默认 0 < AI_SUMMARY_VERSION），需 --enrich-existing 重生成。
        {"one_sentence_summary": "新格式"},
        {"one_sentence_summary": "新格式", "interpretation_version": 1},
        # 版本达标但缺核心字段：某分段失败被整体丢弃（如 4096 token 预算 bug 的产物）。
        {"one_sentence_summary": "新格式", "interpretation_version": AI_SUMMARY_VERSION},
        {
            "one_sentence_summary": "新格式",
            "why_it_matters": "x",
            "background_problem": "y",
            "interpretation_version": AI_SUMMARY_VERSION,
        },
    ]
    for raw in stale_cases:
        assert cli._ai_summary_stale(raw), f"expected stale: {raw!r}"
    fresh = {
        "one_sentence_summary": "新格式",
        "why_it_matters": "x",
        "background_problem": "y",
        "core_idea": "c",
        "how_it_works": "h",
        "technical_details": "t",
        "experimental_evidence": "e",
        "real_world_impact": "r",
        "limitations": "l",
        "interpretation_version": AI_SUMMARY_VERSION,
    }
    assert not cli._ai_summary_stale(fresh)


def test_enrich_existing_single_paper_id_forces_regen() -> None:
    """--paper-id 强制重生成指定论文，即使它已是当前版本。"""
    rows = [
        _paper_row("arxiv:1", is_featured=True, ai_summary={
            "one_sentence_summary": "新格式",
            "core_idea": "核心",
            "technical_details": "细节",
            "experimental_evidence": "证据",
            "limitations": "局限",
            "interpretation_version": AI_SUMMARY_VERSION,
        }),
        _paper_row("arxiv:2", is_featured=True, ai_summary={"one_sentence_summary": "旧", "interpretation_version": 1}),
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
        db.save_papers.return_value = 1

        code = asyncio.run(cli.run(_arxiv_config(), enrich_existing=True, paper_id="arxiv:1"))

    assert code == 1
    args = mock_enrich.call_args[0]
    assert [p.id for p in args[2]] == ["arxiv:1"]
    db.save_papers.assert_called_once()


def test_enrich_existing_paper_id_not_found() -> None:
    """--paper-id 指定的论文不存在时，直接返回 0 且不调用富化。"""
    rows = [_paper_row("arxiv:1", is_featured=True, ai_summary=None)]
    with patch("src.papers.cli.HorizonDB") as MockDB, patch(
        "src.papers.cli.create_ai_client"
    ), patch("src.papers.cli.enrich_featured", AsyncMock()) as mock_enrich:
        db = MockDB.return_value
        db.get_papers.return_value = {"items": rows, "total": len(rows)}

        code = asyncio.run(cli.run(_arxiv_config(), enrich_existing=True, paper_id="arxiv:999"))

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


# ── OpenAlex 翻译失败不入库 ──────────────────────────────────────────────────


def _openalex_result() -> ClassicFetchResult:
    now = datetime.now(timezone.utc)

    def _p(nid: str, title: str) -> Paper:
        return Paper(
            id=f"openalex:{nid}", source="openalex", native_id=nid, title=title,
            authors=[], abstract="abstract", url=f"https://openalex.org/{nid}",
            published_at=now, updated_at=now, categories=[], fetched_at=now,
        )

    papers = [_p("W1", "Paper One"), _p("W2", "Paper Two")]
    mrs = [
        SeedMatchResult(seed_title="s1", category="c", match_status="matched", expected_year=2026),
        SeedMatchResult(seed_title="s2", category="c", match_status="matched", expected_year=2026),
    ]
    return ClassicFetchResult(papers=papers, match_results=mrs)


def _openalex_config() -> Config:
    """OpenAlex-only config; extract_keywords off so only the translate path runs."""
    return Config.model_construct(
        ai=AIConfig.model_construct(provider="deepseek"),
        papers=PapersConfig(enabled=True, extract_keywords=False),
    )


def test_openalex_translate_failed_paper_not_saved() -> None:
    """翻译后 title_zh 为 None 的 OpenAlex 论文不写入数据库。"""

    async def _fake_translate(ai_client, papers):  # noqa: ARG001
        for p in papers:
            if p.native_id == "W1":
                p.title_zh = "论文一"
                p.abstract_zh = "摘要一"
            # W2 保持 title_zh=None → 模拟翻译失败

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HorizonDB"
    ) as MockDB, patch("src.papers.cli.create_ai_client"), patch(
        "src.papers.cli.translate_papers", AsyncMock(side_effect=_fake_translate)
    ):
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=_openalex_result())
        db = MockDB.return_value
        db.save_papers.return_value = 1

        asyncio.run(cli.run(_openalex_config(), only_source="openalex", dry_run=False))

    saved = db.save_papers.call_args[0][0]
    assert [p.id for p in saved] == ["openalex:W1"]


def test_openalex_no_translate_keeps_all_papers() -> None:
    """no_translate 模式下不过滤,所有 matched 论文原样保存。"""

    with patch("src.papers.cli.OpenAlexFetcher") as MockOpenAlex, patch(
        "src.papers.cli.HorizonDB"
    ) as MockDB, patch("src.papers.cli.translate_papers", AsyncMock()) as mock_translate:
        MockOpenAlex.return_value.fetch_classic = AsyncMock(return_value=_openalex_result())
        db = MockDB.return_value
        db.save_papers.return_value = 2

        asyncio.run(cli.run(_openalex_config(), only_source="openalex", dry_run=False, no_translate=True))

    mock_translate.assert_not_called()
    saved = db.save_papers.call_args[0][0]
    assert [p.id for p in saved] == ["openalex:W1", "openalex:W2"]
