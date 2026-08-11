"""Tests for WeChat MP report body-text cleaning.

Covers the block-level-aware extraction (``_block_level_text``) that stops
inline ``<span>/<em>/<strong>`` wrappers from shredding paragraphs, the
WeChat footer truncation, and the ``backfill-wxmp-text`` CLI path that
re-cleans stored reports from ``raw_html``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.reports.cli import backfill_wxmp_text
from src.reports.models import Report
from src.reports.sources.wxmp import WxMpReportFetcher
from src.storage.db import HorizonDB


def _wxmp_report(**overrides) -> Report:
    defaults = dict(
        id="wxmp:123",
        source="wxmp",
        native_id="123",
        title="某公众号报告",
        institution="某公众号",
        url="https://mp.weixin.qq.com/s/abc",
        content_text="旧正文",
        raw_html="<p>旧正文</p>",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Report(**defaults)


def test_inline_tags_do_not_shred_paragraph():
    """A parenthetical wrapped in <span> stays inside the same paragraph."""
    html = (
        '<p>现有理论可能因方法论偏好'
        '<span>（易研究"做什么"而非"是什么"）</span>'
        '而系统性忽视<b>肉身</b>的必要性。</p>'
    )
    text = WxMpReportFetcher._extract_text(html)
    assert "偏好\n（易研究" not in text
    assert "（易研究" in text
    assert "忽视肉身" in text  # <b> unwrapped seamlessly
    assert text.count("\n") == 0


def test_inline_punctuation_not_on_own_line():
    """A run of single comma <span>s must not become comma-per-line."""
    html = "<p>正文<span>，</span><span>，</span><span>，</span>继续</p>"
    text = WxMpReportFetcher._extract_text(html)
    assert text == "正文，，，继续"


def test_tag_separator_whitespace_does_not_break_lines():
    """Indentation/newlines between tags must not become line breaks."""
    html = (
        "<p>自主实验室\n"
        "<span>（</span>\n"
        "<span>SDL</span>\n"
        "<span>）</span>\n"
        "推理时计算<span>（in</span><span>ference-time compute）</span></p>"
    )
    text = WxMpReportFetcher._extract_text(html)
    assert text == "自主实验室（SDL）推理时计算（inference-time compute）"
    assert "\n" not in text


def test_br_becomes_newline_within_paragraph():
    html = "<p>这是第二段。<br>带换行的同一段。</p>"
    text = WxMpReportFetcher._extract_text(html)
    assert text == "这是第二段。\n带换行的同一段。"


def test_nested_blocks_collapse_blank_lines():
    html = "<div><p>第一段</p></div><div><p>第二段</p></div>"
    text = WxMpReportFetcher._extract_text(html)
    assert text == "第一段\n第二段"


def test_merge_text_fragments_rejoins_shredded_parens():
    """Re-joins parentheticals the old extractor split onto their own lines."""
    text = (
        "自主实验室\n（\nSDL\n）\n的商业化开始兑现。\n"
        "推理时计算\n（\nin\nference-time compute）\n成了新发力点。\n"
        "任务完成率\n（TCR）\n正在取代DAU。\n"
        "个体公司化\n（美国单人创办的新公司占比从23.7%升至36.3%）\n"
        "、组织合伙人化、按贡献定价替代按时间付薪。"
    )
    merged = WxMpReportFetcher._merge_text_fragments(text)
    assert "自主实验室（SDL）的商业化开始兑现。" in merged
    assert "推理时计算（inference-time compute）" in merged
    assert "任务完成率（TCR）" in merged
    assert "个体公司化（美国单人创办的新公司占比从23.7%升至36.3%）、组织合伙人化、按贡献定价替代按时间付薪。" in merged


def test_merge_text_fragments_leaves_clean_paragraphs_alone():
    """A cleanly separated paragraph must not be merged away."""
    text = "这是第一段完整内容。\n这是第二段完整内容。\n"
    assert WxMpReportFetcher._merge_text_fragments(text) == "这是第一段完整内容。\n这是第二段完整内容。"


def test_wechat_footer_truncated():
    """Known footer markers are truncated away."""
    html = (
        "<p>真正的正文结尾。</p>"
        "<p>如若您期待获得《互联网前沿》杂志，可扫码或点击链接填写问卷。</p>"
        "<p>推荐阅读</p><p>腾讯研究院：<span>《协同进化》</span></p>"
    )
    text = WxMpReportFetcher._extract_text(html)
    assert text == "真正的正文结尾。"
    assert "推荐阅读" not in text
    assert "腾讯研究院" not in text


def test_backfill_wxmp_text_recleans_from_raw_html(tmp_path):
    """backfill-wxmp-text re-runs the current cleaner over stored raw_html."""
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    dirty_html = (
        "<p>正文第一段<span>（括号内容）</span>。"
        + ("这是一段足够长的正文内容，用来满足 100 字符的回退阈值。" * 3)
        + "</p>"
        + "<p>推荐阅读</p><p>腾讯研究院：<span>《协同进化》</span></p>"
    )
    db.save_reports([
        _wxmp_report(
            id="wxmp:1",
            native_id="1",
            content_text="旧的脏正文（含噪声）",
            raw_html=dirty_html,
        ),
        # No raw_html → skipped by backfill.
        _wxmp_report(id="wxmp:2", native_id="2", raw_html=None),
    ])

    cfg = SimpleNamespace(reports=SimpleNamespace(enabled=True))
    changed = asyncio.run(backfill_wxmp_text(cfg, source="wxmp", db=db))

    assert changed == 1
    got = db.get_report("wxmp:1")
    assert "（括号内容）" in got["content_text"]
    assert "推荐阅读" not in got["content_text"]
    assert "腾讯研究院" not in got["content_text"]
    # 无 raw_html 的报告保持原值（本次只处理了 1 条）。
    assert db.get_report("wxmp:2")["content_text"] == "旧正文"


def test_backfill_wxmp_text_cleans_plain_text_without_raw_html(tmp_path):
    """无 raw_html 的旧报告也对现有纯文本做二次清洗（footer 截断 + UI 噪声行）。"""
    db = HorizonDB(db_path=str(tmp_path / "test.db"))
    db.save_reports([
        _wxmp_report(
            id="wxmp:1",
            native_id="1",
            content_text="真正的正文结尾。\n推荐阅读\n腾讯研究院：\n《协同进化》\n👇 点个\n在看",
            raw_html=None,
        ),
    ])

    cfg = SimpleNamespace(reports=SimpleNamespace(enabled=True))
    changed = asyncio.run(backfill_wxmp_text(cfg, source="wxmp", db=db))

    assert changed == 1
    assert db.get_report("wxmp:1")["content_text"] == "真正的正文结尾。"
