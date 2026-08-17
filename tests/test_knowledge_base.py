"""Tests for exporting a single news item as Markdown for browser download."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.knowledge_base import build_item_markdown, build_markdown_filename
from src.models import ContentItem, SourceType
from src.storage.db import HorizonDB
from src.api.server import app


# ---------------------------------------------------------------------------
# Unit: build_item_markdown
# ---------------------------------------------------------------------------


def _item(**overrides) -> dict:
    base = {
        "id": "hn:top:1",
        "source_type": "hackernews",
        "title": "Attention Mechanisms in LLMs",
        "url": "https://example.com/alpha",
        "published_at": "2026-08-12T10:00:00+00:00",
        "ai_summary": "AI summary.",
        "ai_tags": ["AI", "tech"],
        "clean_content": "Para one.\n\nPara two.",
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_frontmatter_and_body_sections():
    md = build_item_markdown(_item())
    assert md.startswith("---\n")
    assert 'title: "Attention Mechanisms in LLMs"' in md
    assert "date: 2026-08-12" in md
    assert 'url: "https://example.com/alpha"' in md
    assert "  - \"AI\"" in md
    assert "  - \"tech\"" in md
    assert "## 摘要" in md
    assert "AI summary." in md
    assert "## 正文" in md
    assert "Para one." in md
    assert "Para two." in md
    assert md.endswith("\n")


def test_frontmatter_omits_source_and_horizon_id():
    md = build_item_markdown(_item())
    assert "source:" not in md
    assert "horizon_id:" not in md
    assert "hackernews" not in md
    assert "hn:top:1" not in md


def test_body_prefers_chinese_translated_html():
    md = build_item_markdown(_item(
        # 无翻译时 clean_content 是英文
        clean_content="English body text.",
        # 但有中文翻译的 HTML，应优先用中文正文
        display_html_zh="<h2>中文标题</h2><p>第一段中文。</p><p>第二段中文。</p>",
    ))
    assert "第一段中文。" in md
    assert "第二段中文。" in md
    assert "English body text." not in md


def test_body_falls_back_to_original_html_then_clean_content():
    # 无中文翻译，但有原语言 HTML → 用原语言正文
    md = build_item_markdown(_item(
        display_html="<p>Original html body.</p>",
        clean_content="Fallback clean text.",
    ))
    assert "Original html body." in md
    assert "Fallback clean text." not in md
    # 两者都无 HTML → 回退 clean_content
    md2 = build_item_markdown(_item(display_html=None, display_html_zh=None))
    assert "Para one." in md2


def test_prefers_chinese_title_and_summary():
    md = build_item_markdown(_item(metadata={
        "title_zh": "注意力机制",
        "detailed_summary_zh": "中文摘要内容。",
    }))
    assert 'title: "注意力机制"' in md
    assert "## 摘要" in md
    assert "中文摘要内容。" in md
    # 不应回退到英文原始字段
    assert "Attention Mechanisms in LLMs" not in md
    assert "AI summary." not in md


def test_special_chars_escaped_in_frontmatter():
    title = 'He said "hi":\nnext line'
    md = build_item_markdown(_item(title=title))
    # JSON 双引号字符串是合法 YAML 标量，换行/冒号/引号被转义
    assert f"title: {json.dumps(title, ensure_ascii=False)}" in md
    # frontmatter 在第二个 --- 处闭合，转义后的换行不会提前截断
    assert md.count("---") == 2


def test_published_at_accepts_datetime_and_iso_string():
    iso = build_item_markdown(_item(published_at="2026-08-12T10:00:00+00:00"))
    assert "date: 2026-08-12" in iso
    dt = build_item_markdown(_item(published_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)))
    assert "date: 2026-08-12" in dt


def test_empty_tags_render_empty_yaml_list():
    md = build_item_markdown(_item(ai_tags=[]))
    assert "tags:\n  []" in md


def test_note_appended_after_body_when_provided():
    md = build_item_markdown(_item(), note="我的想法")
    assert "## 我的笔记" in md
    assert "我的想法" in md
    assert md.index("## 我的笔记") > md.index("## 正文")
    assert md.endswith("\n")


def test_note_none_or_empty_keeps_output_identical():
    base = build_item_markdown(_item())
    assert build_item_markdown(_item(), note=None) == base
    assert build_item_markdown(_item(), note="") == base
    assert build_item_markdown(_item(), note="   ") == base
    assert "## 我的笔记" not in base


def test_note_multiline_and_markdown_passthrough():
    note = "第一行想法\n\n**加粗** 与 `code` 原样保留。"
    md = build_item_markdown(_item(), note=note)
    assert "第一行想法" in md
    assert "**加粗**" in md
    assert "`code`" in md
    assert "原样保留。" in md


# ---------------------------------------------------------------------------
# Unit: build_markdown_filename
# ---------------------------------------------------------------------------


def test_filename_derived_from_title():
    assert build_markdown_filename(_item()) == "Attention Mechanisms in LLMs.md"


def test_filename_prefers_chinese_title():
    name = build_markdown_filename(_item(metadata={"title_zh": "注意力机制"}))
    assert name == "注意力机制.md"


def test_filename_sanitizes_special_chars():
    name = build_markdown_filename(_item(title="a/b:c*d?"))
    for ch in "/:*?":
        assert ch not in name
    assert name.endswith(".md")


def test_filename_falls_back_on_empty_title():
    # 空标题回退到 item id（冒号被清洗）
    assert build_markdown_filename(_item(title="")) == "hn_top_1.md"
    # id 也为空时回退到占位名
    assert build_markdown_filename(_item(title="", id="")) == "horizon.md"


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def _seed_item(db: HorizonDB) -> None:
    item = ContentItem(
        id="hn:top:1",
        source_type=SourceType.HACKERNEWS,
        title="HN Article Alpha",
        url="https://example.com/alpha",
        content="Sample body text for alpha.",
        author="test-author",
        published_at=datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 6, 10, 5, 0, tzinfo=timezone.utc),
        ai_relevant=True,
        ai_score=9.0,
        ai_reason="Important.",
        ai_summary="Alpha summary.",
        ai_tags=["AI", "startups"],
    )
    db.save_items([item], run_date="2026-07-06", total_fetched=1)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient wired to a temp DB with one seeded item.

    We do NOT use ``with TestClient(app)`` — the lifespan shutdown runs
    ``db.close()`` in another thread, which SQLite rejects. Mirror test_api.py.
    """
    import src.api.server as server_module

    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    _seed_item(db)
    monkeypatch.setattr(server_module, "db", db)

    c = TestClient(app)
    yield c
    db.close()


def test_export_returns_markdown_and_filename(tmp_path: Path, client):
    r = client.post("/api/items/hn:top:1/export")
    assert r.status_code == 200
    data = r.json()
    assert data["filename"] == "HN Article Alpha.md"
    md = data["markdown"]
    assert 'url: "https://example.com/alpha"' in md
    assert "HN Article Alpha" in md
    assert "Alpha summary." in md
    assert "## 正文" in md
    assert "Sample body text for alpha." in md
    # 纯内容返回，不写任何 Markdown 文件（tmp_path 里只有测试 DB 本身）
    assert [p for p in tmp_path.iterdir() if p.suffix == ".md"] == []


def test_export_missing_item_404(client):
    r = client.post("/api/items/nonexistent/export")
    assert r.status_code == 404


def test_export_with_note_appends_note_module(client):
    r = client.post("/api/items/hn:top:1/export", json={"note": "我的笔记内容"})
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "## 我的笔记" in md
    assert "我的笔记内容" in md
    assert md.index("## 我的笔记") > md.index("## 正文")


def test_export_without_body_has_no_note_module(client):
    r = client.post("/api/items/hn:top:1/export")
    assert r.status_code == 200
    assert "## 我的笔记" not in r.json()["markdown"]


def test_export_whitespace_note_has_no_note_module(client):
    r = client.post("/api/items/hn:top:1/export", json={"note": "  "})
    assert r.status_code == 200
    assert "## 我的笔记" not in r.json()["markdown"]
