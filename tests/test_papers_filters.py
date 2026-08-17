from __future__ import annotations

from datetime import datetime, timezone

from src.papers.filters import (
    TOP_CONFERENCE_NAMES,
    apply_keyword_blacklist,
    apply_keyword_whitelist,
    apply_venue_signals,
    detect_venue,
    exclude_withdrawn,
    extract_github_url,
    is_paper_failed,
    reject_short_abstracts,
    truncate,
)
from src.papers.models import Paper


def _paper(**overrides) -> Paper:
    defaults = dict(
        id="arxiv:2501.00001",
        source="arxiv",
        native_id="2501.00001",
        title="A Paper",
        authors=["Alice"],
        abstract="An abstract about machine learning.",
        url="https://arxiv.org/abs/2501.00001",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        categories=["cs.LG"],
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Paper(**defaults)


# ── detect_venue ────────────────────────────────────────────────────────────


def test_detect_venue_acceptance_phrase_with_year():
    assert detect_venue(None, "To appear at NeurIPS 2025") == "NeurIPS 2025"


def test_detect_venue_acceptance_phrase_in_comment():
    assert detect_venue("Accepted at ICML 2025", None) == "ICML 2025"


def test_detect_venue_case_insensitive_acceptance_phrase():
    assert detect_venue("accepted to ICLR 2024", None) == "ICLR 2024"


def test_detect_venue_weak_bare_conference_name():
    assert detect_venue("Workshop at CVPR", None) == "CVPR"


def test_detect_venue_strong_beats_weak():
    # "accepted at ECCV" is a strong signal for ECCV, even if ICLR also appears.
    text = "accepted at ECCV; earlier workshop at ICLR 2023"
    assert detect_venue(text, None) == "ECCV"


def test_detect_venue_none_when_no_signal():
    assert detect_venue(None, None) is None
    assert detect_venue("Code: https://github.com/foo/bar", None) is None


def test_detect_venue_all_whitelist_names_parse():
    for name in TOP_CONFERENCE_NAMES:
        assert detect_venue(f"Accepted to {name} 2026", None) == f"{name} 2026"


# ── extract_github_url ──────────────────────────────────────────────────────


def test_extract_github_url_from_comment():
    comment = "Code: https://github.com/openai/whisper and demo"
    assert extract_github_url(comment, None) == "https://github.com/openai/whisper"


def test_extract_github_url_falls_back_to_abstract():
    abstract = "Our code is at https://github.com/foo/bar.git"
    assert extract_github_url(None, abstract) == "https://github.com/foo/bar.git"


def test_extract_github_url_strips_trailing_sentence_period():
    # A period right after the repo name is sentence punctuation, not part of
    # the URL — including it would produce a 404.
    assert extract_github_url("Code: https://github.com/foo/bar.", None) == "https://github.com/foo/bar"


def test_extract_github_url_keeps_git_suffix_before_period():
    assert extract_github_url("Code: https://github.com/foo/bar.git.", None) == "https://github.com/foo/bar.git"


def test_extract_github_url_none_when_absent():
    assert extract_github_url("no link here", None) is None


# ── exclude_withdrawn ───────────────────────────────────────────────────────


def test_exclude_withdrawn_drops_withdrawn_papers():
    good = _paper(id="arxiv:a", title="Good paper")
    withdrawn_title = _paper(id="arxiv:b", title="This paper is withdrawn")
    withdrawn_abstract = _paper(id="arxiv:c", abstract="We have withdrawn this work.")
    kept = exclude_withdrawn([good, withdrawn_title, withdrawn_abstract])
    assert [p.id for p in kept] == ["arxiv:a"]


# ── reject_short_abstracts ──────────────────────────────────────────────────


def test_reject_short_abstracts():
    long = _paper(id="arxiv:a", abstract="x" * 200)
    short = _paper(id="arxiv:b", abstract="too short")
    kept = reject_short_abstracts([long, short], min_chars=100)
    assert [p.id for p in kept] == ["arxiv:a"]


def test_reject_short_abstracts_zero_disables():
    short = _paper(id="arxiv:b", abstract="too short")
    assert len(reject_short_abstracts([short], min_chars=0)) == 1


# ── keyword whitelist / blacklist ───────────────────────────────────────────


def test_keyword_whitelist_empty_is_noop():
    p = _paper()
    assert apply_keyword_whitelist([p], []) == [p]


def test_keyword_whitelist_matches_title_or_abstract():
    p1 = _paper(id="arxiv:a", title="Transformer reasoning analysis")
    p2 = _paper(id="arxiv:b", title="Unrelated vision stuff")
    kept = apply_keyword_whitelist([p1, p2], ["transformer", "reasoning"])
    assert [p.id for p in kept] == ["arxiv:a"]


def test_keyword_blacklist():
    p1 = _paper(id="arxiv:a", title="Great new method")
    p2 = _paper(id="arxiv:b", abstract="also mentions survey paper")
    kept = apply_keyword_blacklist([p1, p2], ["survey"])
    assert [p.id for p in kept] == ["arxiv:a"]


def test_keyword_whitelist_short_acronyms_are_word_boundary():
    """ai / rag must not match inside longer English words (said, storage)."""
    p1 = _paper(id="arxiv:a", title="said storage average migration main")  # 含子串但不含独立词
    p2 = _paper(id="arxiv:b", title="RAG pipeline with AI agents")
    kept = apply_keyword_whitelist([p1, p2], ["ai", "rag"])
    assert [p.id for p in kept] == ["arxiv:b"]


def test_keyword_whitelist_matches_plurals_and_phrases():
    """agents / transformers match, and multi-word phrases work."""
    p1 = _paper(id="arxiv:a", title="Agentic transformer agents")
    p2 = _paper(id="arxiv:b", title="stock return prediction sentiment analysis")
    kept = apply_keyword_whitelist(
        [p1, p2], ["agent", "sentiment analysis", "machine learning"]
    )
    assert [p.id for p in kept] == ["arxiv:a", "arxiv:b"]


def test_keyword_whitelist_does_not_match_substring_in_compound():
    """agent must not match agency (rating agency); ai not matched in main."""
    p1 = _paper(id="arxiv:a", title="rating agency regulation")
    p2 = _paper(id="arxiv:b", title="main risk factor")
    kept = apply_keyword_whitelist([p1, p2], ["agent", "ai"])
    assert kept == []


# ── apply_venue_signals / truncate ──────────────────────────────────────────


def test_apply_venue_signals_sorts_venue_first():
    top = _paper(id="arxiv:a", comment="Accepted at NeurIPS 2025")
    plain = _paper(id="arxiv:b")
    ordered = apply_venue_signals([plain, top])
    assert [p.id for p in ordered] == ["arxiv:a", "arxiv:b"]
    assert ordered[0].venue == "NeurIPS 2025"
    assert ordered[1].venue is None


def test_truncate():
    papers = [_paper(id=f"arxiv:{i}") for i in range(5)]
    assert [p.id for p in truncate(papers, 2)] == ["arxiv:0", "arxiv:1"]


# ── is_paper_failed ──────────────────────────────────────────────────────────


def _featured(**overrides) -> Paper:
    """A healthy featured paper: Chinese title + non-empty ai_summary."""
    base = dict(
        is_featured=True,
        title_zh="一篇论文",
        ai_summary={"one_sentence_summary": "一句话总结"},
    )
    base.update(overrides)
    return _paper(**base)


def test_scoring_failed_is_failed_regardless_of_featured():
    assert is_paper_failed(_paper(ai_reason="scoring failed")) is True
    assert is_paper_failed(_paper(is_featured=True, ai_reason="scoring failed")) is True


def test_featured_without_summary_is_failed():
    assert is_paper_failed(_featured(ai_summary=None)) is True


def test_partial_summary_is_not_failed():
    # partial 解读:ai_summary 非空,带 [enrich detail failed: partial: …] 标记
    paper = _featured(
        ai_summary={"one_sentence_summary": "一句话"},
        ai_reason="reason [enrich detail failed: partial: evaluation]",
    )
    assert is_paper_failed(paper) is False


def test_featured_missing_translation_failed_unless_no_translate():
    paper = _featured(title_zh=None)
    assert is_paper_failed(paper) is True
    assert is_paper_failed(paper, no_translate=True) is False


def test_healthy_featured_not_failed():
    assert is_paper_failed(_featured()) is False


def test_non_featured_never_failed():
    # 非 featured:打分成功未入选的候选、未翻译的候选都不算失败
    assert is_paper_failed(_paper(ai_summary=None, title_zh=None)) is False
    assert is_paper_failed(_paper(ai_reason="good", ai_relevance_score=7.0)) is False


def test_zh_origin_paper_not_failed():
    # 中文论文 title_zh=原文,非空,不算翻译失败
    assert is_paper_failed(_featured(title_zh="中文原文标题", original_language="zh")) is False
