from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pydantic
import pytest

from src.models import ArxivSourceConfig
from src.papers import weekly
from src.papers.models import Paper
from src.papers.prompts import (
    ARXIV_CONCEPT_SYSTEM,
    ARXIV_DETAIL_SYSTEM,
    ARXIV_SCORE_SYSTEM,
)
from src.storage.db import HorizonDB


def _paper(**overrides) -> Paper:
    defaults = dict(
        id="arxiv:2501.00001",
        source="arxiv",
        native_id="2501.00001",
        title="A Paper",
        authors=["Alice"],
        abstract="An abstract about machine learning with enough length to pass filters.",
        url="https://arxiv.org/abs/2501.00001",
        published_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        categories=["cs.LG"],
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Paper(**defaults)


def _config(**overrides) -> ArxivSourceConfig:
    values = dict(
        enabled=True,
        categories=["cs.LG"],
        max_results_per_category=10,
        window_days=2,
        min_abstract_chars=10,
        target_candidates=50,
        featured_count=5,
    )
    values.update(overrides)
    return ArxivSourceConfig(**values)


_DETAIL_JSON = {
    "keywords": ["transformer", "attention"],
    "one_sentence_summary": "一句话总结",
    "why_it_matters": "为什么值得关注",
    "background": "背景",
    "previous_problem": "过去方法的不足",
    "core_idea": "核心创新",
    "how_it_works": "如何实现",
    "technical_details": "技术细节",
    "experimental_evidence": "实验证据",
    "real_world_impact": "实际影响",
    "limitations": "局限",
    "innovation_level": {"level": "significant_improvement", "reason": "相比已有方法明显提升"},
}


def _score_json(overall: int, reason: str) -> str:
    """New multi-dimension score JSON, derived so breakdown is predictable."""
    return json.dumps({
        "innovation": overall,
        "technical_quality": overall - 1,
        "impact_potential": overall - 2,
        "relevance": overall - 1,
        "overall_score": overall,
        "reason": reason,
    })


class _FakeAI:
    """AIClient stand-in that dispatches on the system prompt and counts calls."""

    def __init__(self, score_map: dict[str, int] | None = None, fail_detail: bool = False):
        self.config = SimpleNamespace(analysis_concurrency=2)
        self.score_map = score_map or {}
        self.fail_detail = fail_detail
        self.score_calls = 0
        self.detail_calls = 0
        self.translation_calls = 0
        self.last_detail_user = ""

    async def complete(self, system: str, user: str, **kwargs):
        if system.startswith("You are a translator"):
            self.translation_calls += 1
            title = user.split("Title: ", 1)[1].splitlines()[0].strip()
            return json.dumps({"title_zh": f"中文-{title}", "abstract_zh": "中文摘要"})
        if system == ARXIV_SCORE_SYSTEM:
            self.score_calls += 1
            for title, score in self.score_map.items():
                if title in user:
                    return _score_json(score, f"r-{title}")
            return _score_json(5, "default")
        if system == ARXIV_CONCEPT_SYSTEM:
            return json.dumps({"queries": []})
        if system == ARXIV_DETAIL_SYSTEM:
            self.detail_calls += 1
            self.last_detail_user = user
            if self.fail_detail:
                raise RuntimeError("detail failed")
            return json.dumps(_DETAIL_JSON)
        raise AssertionError(f"unexpected system: {system[:40]}")


@pytest.mark.anyio
async def test_run_weekly_arxiv_full_flow() -> None:
    papers = [
        _paper(id="arxiv:a", title="Paper A"),
        _paper(id="arxiv:b", title="Paper B"),
        _paper(id="arxiv:c", title="Paper C"),
        _paper(id="arxiv:d", title="Paper D"),
        _paper(id="arxiv:e", title="Paper E"),
        _paper(id="arxiv:f", title="Paper F"),
        _paper(id="arxiv:g", title="Paper G"),
    ]
    ai = _FakeAI(score_map={
        "Paper A": 9, "Paper B": 7, "Paper C": 4,
        "Paper D": 8, "Paper E": 6, "Paper F": 3, "Paper G": 2,
    })
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=None)

    assert result.fetched == 7
    assert result.after_filter == 7
    assert result.scored == 7
    assert len(result.featured) == 5  # featured_count
    assert [p.id for p in result.featured] == ["arxiv:a", "arxiv:d", "arxiv:b", "arxiv:e", "arxiv:c"]

    top = result.featured[0]
    assert top.is_featured is True
    assert top.featured_date is not None
    assert top.ai_relevance_score == 9.0
    assert top.ai_reason == "r-Paper A"
    assert top.ai_score_breakdown == {
        "innovation": 9.0, "technical_quality": 8.0,
        "impact_potential": 7.0, "relevance": 8.0,
    }
    assert top.keywords == ["transformer", "attention"]
    assert top.ai_summary["background"] == "背景"
    assert top.ai_summary["core_idea"] == "核心创新"
    assert top.ai_summary["innovation_level"] == {
        "level": "significant_improvement", "reason": "相比已有方法明显提升",
    }

    # Non-selected candidates keep is_featured=False.
    non_selected = [p for p in papers if p.id in ("arxiv:f", "arxiv:g")]
    assert all(p.is_featured is False for p in non_selected)


@pytest.mark.anyio
async def test_run_weekly_arxiv_saves_papers_when_db_given(tmp_path) -> None:
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9})
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=db)

    assert result.saved_total == 1
    got = db.get_papers(source="arxiv", featured=True)
    assert got["total"] == 1
    assert got["items"][0]["is_featured"] is True
    assert got["items"][0]["keywords"] == ["transformer", "attention"]


@pytest.mark.anyio
async def test_detail_enrichment_failure_degrades_gracefully() -> None:
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9}, fail_detail=True)
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=None)

    # Paper stays featured but AI fields are empty.
    assert len(result.featured) == 1
    p = result.featured[0]
    assert p.is_featured is True
    assert p.keywords == []
    assert p.ai_summary is None


@pytest.mark.anyio
async def test_fetch_recent_window_filter() -> None:
    now = datetime.now(timezone.utc)
    papers = [
        _paper(id="arxiv:new", published_at=now - timedelta(hours=1)),
        _paper(id="arxiv:old", published_at=now - timedelta(days=5)),
    ]
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.fetch_recent(
            client=None, categories=[], max_results_per_category=1, window_days=2,
        )
    assert [p.id for p in result] == ["arxiv:new"]


def test_merge_existing_state_restores_featured_and_scores(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    stored = _paper(
        id="arxiv:a", title="Paper A",
        is_featured=True, featured_date=yesterday,
        ai_relevance_score=9.0, ai_score_breakdown={
            "innovation": 9.0, "technical_quality": 8.0,
            "impact_potential": 7.0, "relevance": 8.0,
        },
        ai_reason="old",
        title_zh="论文甲", abstract_zh="摘要甲", original_language="en",
    )
    db.save_papers([stored])

    # A fresh refetch has empty AI/featured/translation fields; merge must
    # restore them so the full-field UPSERT doesn't clobber the DB.
    candidate = _paper(id="arxiv:a", title="Paper A", is_featured=False)
    weekly._merge_existing_state(db, [candidate])

    assert candidate.is_featured is True
    assert candidate.featured_date.date() == yesterday.date()
    assert candidate.ai_relevance_score == 9.0
    assert candidate.ai_score_breakdown == {
        "innovation": 9.0, "technical_quality": 8.0,
        "impact_potential": 7.0, "relevance": 8.0,
    }
    assert candidate.ai_reason == "old"
    assert candidate.title_zh == "论文甲"
    assert candidate.abstract_zh == "摘要甲"
    assert candidate.original_language == "en"


def test_merge_existing_state_noop_when_db_none() -> None:
    """dry-run path: no db → nothing read, nothing changed."""
    p = _paper(id="arxiv:a", is_featured=False)
    weekly._merge_existing_state(None, [p])
    assert p.is_featured is False
    assert p.ai_relevance_score is None


def test_parse_featured_date_handles_bad_and_naive_values() -> None:
    assert weekly._parse_featured_date(None) is None
    assert weekly._parse_featured_date("") is None
    assert weekly._parse_featured_date("not-a-date") is None

    aware = weekly._parse_featured_date("2026-07-20T00:00:00+00:00")
    assert aware is not None and aware.tzinfo is not None
    assert aware.utcoffset() == timedelta(0)

    # Naive stored value is normalized to aware UTC.
    naive = weekly._parse_featured_date("2026-07-31")
    assert naive is not None and naive.tzinfo is not None
    assert naive.utcoffset() == timedelta(0)


def test_config_constraints() -> None:
    assert ArxivSourceConfig(featured_count=20).featured_count == 20
    assert ArxivSourceConfig(featured_count=30).featured_count == 30
    assert ArxivSourceConfig(window_days=7).window_days == 7
    with pytest.raises(pydantic.ValidationError):
        ArxivSourceConfig(featured_count=0)
    with pytest.raises(pydantic.ValidationError):
        ArxivSourceConfig(featured_count=31)
    with pytest.raises(pydantic.ValidationError):
        ArxivSourceConfig(window_days=14)


@pytest.mark.anyio
async def test_already_scored_not_rescored(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    stored = _paper(id="arxiv:a", title="Paper A", ai_relevance_score=9.0, ai_reason="old")
    db.save_papers([stored])

    # Refetch returns the same paper with empty score fields.
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 7})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=db)

    assert ai.score_calls == 0          # score dedup → no AI scoring calls
    assert result.scored == 1           # has a usable score (read back)
    assert result.scored_new == 0       # none newly scored
    assert result.featured[0].ai_relevance_score == 9.0  # old score kept
    assert result.featured[0].ai_reason == "old"


@pytest.mark.anyio
async def test_already_featured_not_reselected(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    w1 = datetime(2026, 7, 20, tzinfo=timezone.utc)
    stored = _paper(
        id="arxiv:x", title="Paper X",
        is_featured=True, featured_date=w1, ai_relevance_score=9.0,
    )
    db.save_papers([stored])

    papers = [_paper(id="arxiv:x", title="Paper X")]
    ai = _FakeAI(score_map={"Paper X": 9})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=db)

    assert ai.score_calls == 0
    assert ai.detail_calls == 0          # no re-enrichment
    assert result.featured == []         # not re-selected
    got = db.get_papers(source="arxiv", featured=True)
    assert got["total"] == 1
    assert got["items"][0]["featured_date"].startswith("2026-07-20")  # original batch kept


@pytest.mark.anyio
async def test_ai_and_translation_fields_preserved(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    # Non-featured paper with translations (from --translate-existing).
    stored_a = _paper(
        id="arxiv:a", title="Paper A",
        title_zh="论文甲", abstract_zh="摘要甲", original_language="en",
    )
    # Already-featured paper with AI enrichment.
    w1 = datetime(2026, 7, 20, tzinfo=timezone.utc)
    stored_x = _paper(
        id="arxiv:x", title="Paper X",
        is_featured=True, featured_date=w1, ai_relevance_score=8.0,
        keywords=["k1"], ai_summary={"zh": {"background": "背景"}},
    )
    db.save_papers([stored_a, stored_x])

    papers = [_paper(id="arxiv:a", title="Paper A"), _paper(id="arxiv:x", title="Paper X")]
    ai = _FakeAI(score_map={"Paper A": 9, "Paper X": 8})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=db)

    got_a = db.get_paper("arxiv:a")
    # Paper A is newly featured this run, so its stored translation is
    # refreshed by the featured-set translation step (same mechanism as the
    # classic/HF sources), not preserved verbatim.
    assert got_a["title_zh"] == "中文-Paper A"
    assert got_a["abstract_zh"] == "中文摘要"
    assert got_a["original_language"] == "en"
    assert got_a["is_featured"] is True                  # newly selected this run
    assert got_a["keywords"] == ["transformer", "attention"]  # fresh enrichment

    got_x = db.get_paper("arxiv:x")
    assert got_x["is_featured"] is True                  # stays featured
    assert got_x["featured_date"].startswith("2026-07-20")
    assert got_x["keywords"] == ["k1"]                   # AI fields not clobbered
    assert got_x["ai_summary"]["zh"]["background"] == "背景"


@pytest.mark.anyio
async def test_two_week_overlap_integration(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    cfg = _config(featured_count=5)

    # Run 1: A-E all featured.
    run1 = [_paper(id=f"arxiv:{i}", title=f"Paper {i}") for i in "ABCDE"]
    ai1 = _FakeAI(score_map={f"Paper {i}": 8 for i in "ABCDE"})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=run1)):
        r1 = await weekly.run_weekly_arxiv(ai1, http_client=None, cfg=cfg, db=db)
    assert len(r1.featured) == 5
    run1_date = db.get_papers(source="arxiv", featured=True)["items"][0]["featured_date"]

    # Run 2: A-C overlap (already featured), F/G/H new with high scores.
    run2 = [_paper(id=f"arxiv:{i}", title=f"Paper {i}") for i in "ABCFGH"]
    ai2 = _FakeAI(score_map={f"Paper {i}": 9 for i in "FGH"})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=run2)):
        r2 = await weekly.run_weekly_arxiv(ai2, http_client=None, cfg=cfg, db=db)

    assert [p.id for p in r2.featured] == ["arxiv:F", "arxiv:G", "arxiv:H"]
    assert r2.scored_new == 3            # only F/G/H newly scored
    assert r2.scored == 6                # F/G/H new + A/B/C read back

    featured = db.get_papers(source="arxiv", featured=True)
    assert featured["total"] == 8         # A-E (run1) + F/G/H (run2)
    # A/C kept their original batch date.
    dates = {p["id"]: p["featured_date"] for p in featured["items"]}
    assert dates["arxiv:A"].startswith(run1_date[:10])
    assert dates["arxiv:C"].startswith(run1_date[:10])


# ── AI+Finance split / multi-channel ────────────────────────────────────────

def test_split_by_finance_separates_by_qfin_category() -> None:
    fin = _paper(id="arxiv:f1", categories=["q-fin.ST", "cs.LG"])
    gen1 = _paper(id="arxiv:g1", categories=["cs.LG"])
    gen2 = _paper(id="arxiv:g2", categories=["cs.CV"])
    general, finance = weekly.split_by_finance(
        [fin, gen1, gen2], ["q-fin.ST", "q-fin.GN"],
    )
    assert finance == [fin]
    assert general == [gen1, gen2]


def test_split_by_finance_empty_categories_returns_all_general() -> None:
    papers = [
        _paper(id="arxiv:a", categories=["q-fin.ST"]),
        _paper(id="arxiv:b"),
    ]
    general, finance = weekly.split_by_finance(papers, [])
    assert general == papers
    assert finance == []


def test_rekey_source_renamespaces_paper() -> None:
    p = _paper(id="arxiv:2501.00001", native_id="2501.00001")
    out = weekly._rekey_source(p, weekly.FINANCE_SOURCE)
    assert out is p                     # mutated in place
    assert p.source == "arxiv_fin"
    assert p.id == "arxiv_fin:2501.00001"


@pytest.mark.anyio
async def test_run_weekly_arxiv_all_splits_and_runs_both_groups() -> None:
    papers = [
        _paper(id="arxiv:a", native_id="a", title="LLM for trading",
               categories=["q-fin.TR", "cs.LG"]),
        _paper(id="arxiv:b", native_id="b", title="Paper B", categories=["cs.LG"]),
        _paper(id="arxiv:c", native_id="c", title="Neural risk forecasting",
               categories=["q-fin.RM"]),
        _paper(id="arxiv:d", native_id="d", title="Pure econometrics",
               categories=["q-fin.EC"]),
    ]
    ai = _FakeAI(score_map={
        "LLM for trading": 9,
        "Neural risk forecasting": 7,
        "Paper B": 8,
        "Pure econometrics": 3,
    })
    cfg = _config(
        finance_enabled=True,
        finance_categories=["q-fin.TR", "q-fin.RM", "q-fin.EC"],
        finance_keyword_whitelist=["llm", "neural"],
        finance_featured_count=2,
    )
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        results = await weekly.run_weekly_arxiv_all(ai, http_client=None, cfg=cfg, db=None)

    assert set(results.keys()) == {"arxiv", "arxiv_fin"}

    # Finance group: a & c pass the AI keyword whitelist; "Pure econometrics"
    # (no AI keyword) is dropped by the whitelist before scoring.
    fin = results["arxiv_fin"]
    assert fin.fetched == 3
    assert fin.after_filter == 2
    assert [p.id for p in fin.featured] == ["arxiv_fin:a", "arxiv_fin:c"]
    assert all(p.source == "arxiv_fin" for p in fin.featured)

    # General group keeps non-finance papers only.
    gen = results["arxiv"]
    assert [p.id for p in gen.featured] == ["arxiv:b"]
    assert gen.featured[0].source == "arxiv"


@pytest.mark.anyio
async def test_run_weekly_arxiv_all_persists_finance_under_arxiv_fin(tmp_path) -> None:
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    papers = [
        _paper(id="arxiv:a", native_id="a", title="LLM for trading",
               categories=["q-fin.TR", "cs.LG"]),
        _paper(id="arxiv:b", native_id="b", title="Paper B", categories=["cs.LG"]),
        _paper(id="arxiv:c", native_id="c", title="Neural risk forecasting",
               categories=["q-fin.RM"]),
    ]
    ai = _FakeAI(score_map={
        "LLM for trading": 9, "Paper B": 8, "Neural risk forecasting": 7,
    })
    cfg = _config(
        finance_enabled=True,
        finance_categories=["q-fin.TR", "q-fin.RM"],
        finance_keyword_whitelist=["llm", "neural"],
        finance_featured_count=1,
    )
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        results = await weekly.run_weekly_arxiv_all(ai, http_client=None, cfg=cfg, db=db)

    assert results["arxiv"].saved_total == 1
    assert results["arxiv_fin"].saved_total == 2

    general = db.get_papers(source="arxiv")
    assert general["total"] == 1
    assert general["items"][0]["id"] == "arxiv:b"

    fin_all = db.get_papers(source="arxiv_fin")
    assert fin_all["total"] == 2
    assert {p["id"] for p in fin_all["items"]} == {"arxiv_fin:a", "arxiv_fin:c"}

    fin_featured = db.get_papers(source="arxiv_fin", featured=True)
    assert fin_featured["total"] == 1
    assert fin_featured["items"][0]["id"] == "arxiv_fin:a"


@pytest.mark.anyio
async def test_run_weekly_arxiv_all_finance_disabled_only_general() -> None:
    papers = [
        _paper(id="arxiv:a", native_id="a", title="LLM for trading",
               categories=["q-fin.TR", "cs.LG"]),
        _paper(id="arxiv:b", native_id="b", title="Paper B", categories=["cs.LG"]),
    ]
    ai = _FakeAI(score_map={"LLM for trading": 9, "Paper B": 8})
    # finance_categories set but finance_enabled False → nothing is split out,
    # every paper stays in the general pool.
    cfg = _config(
        finance_enabled=False,
        finance_categories=["q-fin.TR"],
        finance_keyword_whitelist=["llm"],
    )
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        results = await weekly.run_weekly_arxiv_all(ai, http_client=None, cfg=cfg, db=None)

    assert set(results.keys()) == {"arxiv"}
    assert {p.id for p in results["arxiv"].featured} == {"arxiv:a", "arxiv:b"}


# ── Featured-set translation (same mechanism as classic/HF sources) ──────────

@pytest.mark.anyio
async def test_featured_translated_non_featured_not() -> None:
    papers = [
        _paper(id="arxiv:a", title="Paper A"),
        _paper(id="arxiv:f", title="Paper F"),
    ]
    ai = _FakeAI(score_map={"Paper A": 9, "Paper F": 3})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(
            ai, http_client=None, cfg=_config(featured_count=1), db=None,
        )

    assert len(result.featured) == 1
    top = result.featured[0]
    assert top.title_zh == "中文-Paper A"
    assert top.abstract_zh == "中文摘要"
    assert top.original_language == "en"

    # Non-featured candidates are not translated.
    non_selected = next(p for p in papers if p.id == "arxiv:f")
    assert non_selected.title_zh is None
    assert non_selected.abstract_zh is None
    assert non_selected.original_language is None


@pytest.mark.anyio
async def test_no_translate_skips_featured_translation() -> None:
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(
            ai, http_client=None, cfg=_config(), db=None, no_translate=True,
        )

    assert ai.translation_calls == 0
    assert len(result.featured) == 1
    assert result.featured[0].title_zh is None
    assert result.featured[0].abstract_zh is None
    assert result.featured[0].original_language is None


@pytest.mark.anyio
async def test_finance_group_featured_translated() -> None:
    papers = [
        _paper(id="arxiv:a", native_id="a", title="LLM for trading",
               categories=["q-fin.TR", "cs.LG"]),
        _paper(id="arxiv:b", native_id="b", title="Paper B", categories=["cs.LG"]),
    ]
    ai = _FakeAI(score_map={"LLM for trading": 9, "Paper B": 8})
    cfg = _config(
        finance_enabled=True,
        finance_categories=["q-fin.TR"],
        finance_keyword_whitelist=["llm"],
        finance_featured_count=1,
    )
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        results = await weekly.run_weekly_arxiv_all(ai, http_client=None, cfg=cfg, db=None)

    fin = results["arxiv_fin"]
    assert len(fin.featured) == 1
    assert fin.featured[0].source == "arxiv_fin"
    assert fin.featured[0].title_zh == "中文-LLM for trading"
    assert fin.featured[0].abstract_zh == "中文摘要"
    assert fin.featured[0].original_language == "en"

    gen = results["arxiv"]
    assert gen.featured[0].title_zh == "中文-Paper B"


# ── Full-text fetch (_fetch_paper_full_text) ────────────────────────────────

@pytest.mark.anyio
async def test_fetch_paper_full_text_empty_without_client() -> None:
    """Dry-run mode passes http_client=None → no network, no crash."""
    assert await weekly._fetch_paper_full_text(None, _paper()) == ""


@pytest.mark.anyio
async def test_fetch_paper_full_text_falls_back_to_ar5iv() -> None:
    """arxiv.org/html fails → ar5iv fallback succeeds → text returned."""
    client = AsyncMock()
    client.get.side_effect = [
        RuntimeError("boom"),
        SimpleNamespace(
            text="<html><body>paper body</body></html>",
            raise_for_status=lambda: None,
        ),
    ]
    with patch(
        "src.papers.weekly.trafilatura.extract",
        return_value="The full paper text. " * 300,
    ):
        text = await weekly._fetch_paper_full_text(client, _paper())

    assert "The full paper text." in text
    urls = [c.args[0] for c in client.get.call_args_list]
    assert urls[0].startswith("https://arxiv.org/html/")
    assert urls[1].startswith("https://ar5iv.labs.arxiv.org/html/")


@pytest.mark.anyio
async def test_fetch_paper_full_text_arxiv_html_404_falls_back_quietly(caplog) -> None:
    """arxiv.org/html 404 (no HTML rendering) → ar5iv fallback, no scary log."""
    client = AsyncMock()
    client.get.side_effect = [
        httpx.Response(404, request=httpx.Request("GET", "https://arxiv.org/html/x")),
        SimpleNamespace(
            text="<html><body>paper body</body></html>",
            raise_for_status=lambda: None,
        ),
    ]
    with caplog.at_level(logging.WARNING, logger="src.papers.weekly"):
        with patch(
            "src.papers.weekly.trafilatura.extract",
            return_value="The full paper text. " * 300,
        ):
            text = await weekly._fetch_paper_full_text(client, _paper())

    assert "The full paper text." in text
    urls = [c.args[0] for c in client.get.call_args_list]
    assert urls[0].startswith("https://arxiv.org/html/")
    assert urls[1].startswith("https://ar5iv.labs.arxiv.org/html/")
    # The expected 404 must not surface as an alarming traceback warning.
    assert "Full-text fetch failed" not in caplog.text


@pytest.mark.anyio
async def test_fetch_paper_full_text_skips_short_extractions() -> None:
    """Extracted text below the length threshold is treated as a failure."""
    client = AsyncMock()
    client.get.return_value = SimpleNamespace(
        text="<html><body>tiny</body></html>",
        raise_for_status=lambda: None,
    )
    with patch("src.papers.weekly.trafilatura.extract", return_value="tiny"):
        assert await weekly._fetch_paper_full_text(client, _paper()) == ""


@pytest.mark.anyio
async def test_enrich_injects_full_text_into_user_prompt() -> None:
    """Full text fetched from the paper is passed into the detail prompt."""
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9})
    full_text = "The real paper body with methods and results. " * 40
    with (
        patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)),
        patch("src.papers.weekly._fetch_paper_full_text", AsyncMock(return_value=full_text)) as ft,
    ):
        result = await weekly.run_weekly_arxiv(
            ai, http_client=None, cfg=_config(), db=None,
        )

    ft.assert_awaited_once()
    assert full_text in ai.last_detail_user
    assert "**论文全文（节选）：**" in ai.last_detail_user
    top = result.featured[0]
    assert top.ai_summary["how_it_works"] == "如何实现"


@pytest.mark.anyio
async def test_run_weekly_arxiv_reports_enrich_and_translate_counts() -> None:
    """Featured papers are enriched and translated; counts are surfaced."""
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=None)

    assert len(result.featured) == 1
    assert result.enriched_new == 1
    assert result.enrich_failed == 0
    assert result.translated_new == 1
    assert result.translate_failed == 0
    assert result.featured[0].title_zh == "中文-Paper A"
    assert result.featured[0].ai_summary["background"] == "背景"


@pytest.mark.anyio
async def test_detail_enrichment_failure_marks_reason_and_counts() -> None:
    """A failed detail enrichment records a visible marker and counts."""
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9}, fail_detail=True)
    # complete_with_retry retries with real sleeps; neutralize them for speed.
    with (
        patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)),
        patch("src.papers.weekly.asyncio.sleep", AsyncMock()),
    ):
        result = await weekly.run_weekly_arxiv(ai, http_client=None, cfg=_config(), db=None)

    assert result.enrich_failed == 1
    assert result.enriched_new == 0
    p = result.featured[0]
    assert p.ai_summary is None
    assert p.ai_reason is not None
    assert "[enrich detail failed:" in p.ai_reason


@pytest.mark.anyio
async def test_run_weekly_arxiv_counts_translate_failure() -> None:
    """When translation is skipped (--no-translate), counts reflect it."""
    papers = [_paper(id="arxiv:a", title="Paper A")]
    ai = _FakeAI(score_map={"Paper A": 9})
    with patch("src.papers.weekly._arxiv_fetch_recent", AsyncMock(return_value=papers)):
        result = await weekly.run_weekly_arxiv(
            ai, http_client=None, cfg=_config(), db=None, no_translate=True,
        )

    assert result.translated_new == 0
    assert result.translate_failed == 0
    assert result.featured[0].title_zh is None
