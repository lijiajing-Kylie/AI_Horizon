from __future__ import annotations

from datetime import datetime, timezone

from src.papers.models import Paper
from src.storage.db import HorizonDB


def _paper(**overrides) -> Paper:
    defaults = dict(
        id="openalex:W1",
        source="openalex",
        native_id="W1",
        title="A Paper",
        authors=["Alice", "Bob"],
        abstract="An abstract.",
        url="https://openalex.org/W1",
        pdf_url="https://example.org/w1.pdf",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        publication_year=2026,
        categories=["Machine Learning"],
        category="Machine Learning",
        citation_count=1234,
        citation_percentile=0.995,
        open_access=True,
        raw_metadata={"id": "https://openalex.org/W1"},
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Paper(**defaults)


def test_save_and_get_paper_round_trip(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([_paper()])

    got = db.get_paper("openalex:W1")
    assert got is not None
    assert got["title"] == "A Paper"
    assert got["source"] == "openalex"
    assert got["native_id"] == "W1"
    assert got["authors"] == ["Alice", "Bob"]
    assert got["categories"] == ["Machine Learning"]
    assert got["category"] == "Machine Learning"
    assert got["publication_year"] == 2026
    assert got["citation_count"] == 1234
    assert got["citation_percentile"] == 0.995
    assert got["open_access"] is True
    assert got["raw_metadata"] == {"id": "https://openalex.org/W1"}


def test_get_paper_not_found(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    assert db.get_paper("does-not-exist") is None


def test_upsert_updates_existing_row(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([_paper()])
    db.save_papers([_paper(abstract="Updated abstract.")])

    assert db.get_papers()["total"] == 1
    assert db.get_paper("openalex:W1")["abstract"] == "Updated abstract."


def test_get_papers_pagination_and_sort(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([
        _paper(id="openalex:W1", native_id="W1", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _paper(id="openalex:W2", native_id="W2", published_at=datetime(2026, 1, 3, tzinfo=timezone.utc)),
        _paper(id="openalex:W3", native_id="W3", published_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ])

    result = db.get_papers(page=1, per_page=2)
    assert result["total"] == 3
    assert result["pages"] == 2
    assert [p["id"] for p in result["items"]] == ["openalex:W2", "openalex:W3"]


def test_get_papers_filter_by_source(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([
        _paper(id="openalex:W1", native_id="W1", source="openalex"),
        _paper(
            id="huggingface:2501.1",
            native_id="2501.1",
            source="huggingface",
            url="https://huggingface.co/papers/2501.1",
            category=None,
            citation_count=None,
            upvote_count=42,
        ),
    ])

    result = db.get_papers(source="huggingface")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "huggingface:2501.1"
    assert result["items"][0]["upvote_count"] == 42


def test_get_papers_filter_by_category(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([
        _paper(id="openalex:W1", native_id="W1", category="Machine Learning"),
        _paper(id="openalex:W2", native_id="W2", category="Computer Vision"),
    ])

    result = db.get_papers(category="Computer Vision")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "openalex:W2"


def test_get_papers_sort_by_citation_count(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([
        _paper(id="openalex:W1", native_id="W1", citation_count=10),
        _paper(id="openalex:W2", native_id="W2", citation_count=999),
    ])

    result = db.get_papers(sort="citation_count", order="desc")
    assert [p["id"] for p in result["items"]] == ["openalex:W2", "openalex:W1"]


def test_get_papers_filter_by_month(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_papers([
        _paper(
            id="openalex:W1",
            native_id="W1",
            published_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        ),
        _paper(
            id="openalex:W2",
            native_id="W2",
            published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
        _paper(
            id="openalex:W3",
            native_id="W3",
            published_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
        ),
    ])

    # Filter for January 2026
    result = db.get_papers(publication_month="2026-01")
    assert result["total"] == 2
    assert {p["id"] for p in result["items"]} == {"openalex:W1", "openalex:W3"}

    # Filter for February 2026
    result = db.get_papers(publication_month="2026-02")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "openalex:W2"

    # No filter returns all
    result = db.get_papers()
    assert result["total"] == 3
