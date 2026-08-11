"""Rule-based paper topic classification — word-boundary keyword matching.

Regression coverage for the fix that switched Step-3 keyword matching from
bare substring checks (``kw in title_abs``) to word-boundary regexes, so
short tokens like ``gan`` / ``serving`` no longer match inside longer words
like ``organization`` / ``preserving``.
"""

from datetime import datetime, timezone

from src.papers.models import Paper
from src.papers.topics import classify_paper_topics


def _paper(title: str, abstract: str = "", categories: list[str] | None = None) -> Paper:
    now = datetime.now(timezone.utc)
    return Paper(
        id="arxiv:2501.00001",
        source="arxiv",
        native_id="2501.00001",
        title=title,
        authors=["Alice"],
        abstract=abstract,
        url="https://arxiv.org/abs/2501.00001",
        published_at=now,
        updated_at=now,
        fetched_at=now,
        categories=categories or [],
    )


def _slugs(paper: Paper) -> list[str]:
    return [t["slug"] for t in classify_paper_topics(paper)]


def test_word_boundary_prevents_substring_false_positives() -> None:
    # "gan" inside "organization", "serving" inside "preserving" must not match.
    paper = _paper(
        "An optimization-path organization framework preserving transfer",
        abstract="We organize heterogeneous tasks under a fixed budget.",
    )
    slugs = _slugs(paper)
    assert "image-video-generation" not in slugs
    assert "ai-systems" not in slugs


def test_standalone_keyword_still_matches() -> None:
    # A genuine standalone "gan" still lands in image-video-generation.
    paper = _paper("Improving GAN training stability with spectral normalization")
    assert "image-video-generation" in _slugs(paper)


def test_plural_keywords_match() -> None:
    # "autonomous agents" (plural) matches agent-multi-agent via the s? suffix.
    paper = _paper("Coordination protocols for autonomous agents")
    assert "agent-multi-agent" in _slugs(paper)


def test_arxiv_category_mapping_unchanged() -> None:
    paper = _paper("LoRA for heterogeneous tasks", categories=["cs.LG"])
    assert "machine-learning" in _slugs(paper)


def test_realistic_llm_finetuning_paper_gets_only_sensible_topics() -> None:
    # Regression: the Multi-Policy PEFT paper used to pick up
    # image-video-generation ("orGANization") and ai-systems ("preSERVING").
    paper = _paper(
        "The Parts Are Greater Than the Sum: Automated Task Sequencing for "
        "Efficient Training of Multi-Policy LLMs",
        abstract=(
            "Parameter-Efficient Fine-Tuning (PEFT) commonly adapts large language "
            "models using a single shared Low-Rank Adapter (LoRA). We propose an "
            "optimization-path organization framework implemented as automatic "
            "multi-policy PEFT, grouping tasks while preserving positive transfer."
        ),
        categories=["cs.LG"],
    )
    slugs = _slugs(paper)
    assert "machine-learning" in slugs      # cs.LG category mapping
    assert "nlp-llm" in slugs               # "language model"
    assert "llm" in slugs                   # "large language model"
    assert "image-video-generation" not in slugs
    assert "ai-systems" not in slugs
