from __future__ import annotations

from datetime import datetime, timezone

from src.reports.models import Report
from src.storage.db import HorizonDB


def _report(**overrides) -> Report:
    defaults = dict(
        id="aliresearch:591792162400768000",
        source="aliresearch",
        native_id="591792162400768000",
        title="A Report",
        institution="阿里研究院",
        author="阿里巴巴",
        url="http://www.aliresearch.com/ch/presentation/presentiondetails?articleCode=591792162400768000",
        pdf_urls=[{"name": "report.pdf", "url": "https://oss.example.com/report.pdf"}],
        summary=None,
        content_text="Report body text.",
        categories=["新闻", "报告"],
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        view_count=100,
        download_count=10,
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Report(**defaults)


def test_save_and_get_report_round_trip(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([_report()])

    got = db.get_report("aliresearch:591792162400768000")
    assert got is not None
    assert got["title"] == "A Report"
    assert got["source"] == "aliresearch"
    assert got["native_id"] == "591792162400768000"
    assert got["categories"] == ["新闻", "报告"]
    assert got["pdf_urls"] == [{"name": "report.pdf", "url": "https://oss.example.com/report.pdf"}]


def test_get_report_not_found(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    assert db.get_report("does-not-exist") is None


def test_upsert_updates_existing_row(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([_report()])
    db.save_reports([_report(content_text="Updated body.")])

    assert db.get_reports()["total"] == 1
    assert db.get_report("aliresearch:591792162400768000")["content_text"] == "Updated body."


def test_get_reports_pagination_and_sort(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _report(id="aliresearch:2", native_id="2", published_at=datetime(2026, 1, 3, tzinfo=timezone.utc)),
        _report(id="aliresearch:3", native_id="3", published_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ])

    result = db.get_reports(page=1, per_page=2)
    assert result["total"] == 3
    assert result["pages"] == 2
    assert [r["id"] for r in result["items"]] == ["aliresearch:2", "aliresearch:3"]


def test_get_reports_filter_by_source(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", source="aliresearch"),
        _report(id="other:1", native_id="1", source="other"),
    ])

    result = db.get_reports(source="other")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "other:1"


def test_get_reports_filter_by_category(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", categories=["数字经济"]),
        _report(id="aliresearch:2", native_id="2", categories=["电商"]),
    ])

    result = db.get_reports(category="电商")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "aliresearch:2"


def test_get_reports_search_title(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", title="AI趋势报告"),
        _report(id="aliresearch:2", native_id="2", title="淘宝村研究"),
    ])

    result = db.get_reports(search="AI")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "aliresearch:1"
