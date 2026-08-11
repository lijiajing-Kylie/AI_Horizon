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
        keywords=["大模型应用", "Transformer", "行业趋势"],
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
    assert got["keywords"] == ["大模型应用", "Transformer", "行业趋势"]
    assert got["pdf_urls"] == [{"name": "report.pdf", "url": "https://oss.example.com/report.pdf"}]


def test_report_raw_html_round_trip(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    html = '<section><p>原始正文</p><img src="https://example.com/x.jpg"></section>'
    db.save_reports([
        _report(
            id="wxmp:123",
            source="wxmp",
            native_id="123",
            content_text="清洗后的纯文本",
            raw_html=html,
        )
    ])

    got = db.get_report("wxmp:123")
    assert got["raw_html"] == html
    assert got["content_text"] == "清洗后的纯文本"


def test_report_raw_html_defaults_to_none(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([_report()])

    got = db.get_report("aliresearch:591792162400768000")
    assert got["raw_html"] is None


def test_get_report_not_found(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    assert db.get_report("does-not-exist") is None


def test_upsert_updates_existing_row(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([_report()])
    db.save_reports([_report(content_text="Updated body.", keywords=["新关键词"])])

    assert db.get_reports()["total"] == 1
    got = db.get_report("aliresearch:591792162400768000")
    assert got["content_text"] == "Updated body."
    assert got["keywords"] == ["新关键词"]


def test_get_reports_pagination_and_sort(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc), fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _report(id="aliresearch:2", native_id="2", published_at=datetime(2026, 1, 3, tzinfo=timezone.utc), fetched_at=datetime(2026, 1, 3, tzinfo=timezone.utc)),
        _report(id="aliresearch:3", native_id="3", published_at=datetime(2026, 1, 2, tzinfo=timezone.utc), fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ])

    result = db.get_reports(page=1, per_page=2)
    assert result["total"] == 3
    assert result["pages"] == 2
    assert [r["id"] for r in result["items"]] == ["aliresearch:2", "aliresearch:3"]
    # 库级最近抓取时间与分页/排序无关，为全局 MAX(fetched_at)。
    assert result["latest_fetched_at"] == "2026-01-03T00:00:00+00:00"


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


def test_save_and_get_report_composite_scores_round_trip(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([_report(ai_relevance_score=4.0, composite_score=0.85)])

    got = db.get_report("aliresearch:591792162400768000")
    assert got["ai_relevance_score"] == 4.0
    assert got["composite_score"] == 0.85


def test_get_reports_sort_by_composite_score_nulls_last(tmp_path):
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _report(id="aliresearch:1", native_id="1", composite_score=0.3),
        _report(id="aliresearch:2", native_id="2", composite_score=0.9),
        _report(id="aliresearch:3", native_id="3", composite_score=None),
        _report(id="aliresearch:4", native_id="4", composite_score=0.6),
    ])

    result = db.get_reports(sort="composite_score", order="desc", per_page=10)
    # 高分在前，NULL（历史未 backfill）垫底。
    assert [r["id"] for r in result["items"]] == [
        "aliresearch:2", "aliresearch:4", "aliresearch:1", "aliresearch:3",
    ]


def test_reports_table_migration_adds_score_columns(tmp_path):
    import sqlite3

    # 手工构造旧版 reports 表（无 ai_relevance_score / composite_score 列）。
    db_path = str(tmp_path / "migrate.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE reports (
            id                  TEXT PRIMARY KEY,
            source              TEXT NOT NULL,
            native_id           TEXT NOT NULL,
            title               TEXT NOT NULL,
            institution         TEXT NOT NULL DEFAULT '',
            author              TEXT,
            url                 TEXT NOT NULL,
            pdf_urls_json       TEXT NOT NULL DEFAULT '[]',
            summary             TEXT,
            content_text        TEXT NOT NULL,
            raw_html            TEXT,
            categories_json     TEXT NOT NULL DEFAULT '[]',
            keywords_json       TEXT NOT NULL DEFAULT '[]',
            published_at        TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            view_count          INTEGER,
            download_count      INTEGER,
            fetched_at          TEXT NOT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_row_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

    db = HorizonDB(db_path=db_path)
    cols = {row["name"] for row in db.conn.execute("PRAGMA table_info(reports)")}
    assert "ai_relevance_score" in cols
    assert "composite_score" in cols

    # 迁移后 save/get 完整可用。
    db.save_reports([_report(ai_relevance_score=4.0, composite_score=0.8)])
    got = db.get_report("aliresearch:591792162400768000")
    assert got["ai_relevance_score"] == 4.0
    assert got["composite_score"] == 0.8
