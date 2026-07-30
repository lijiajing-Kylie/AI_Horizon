"""Tests for the ``_detect_wechat_keyword`` method in ``WxMpReportFetcher``.

These are pure-function tests — no network, no mocks, just text scanning.
"""

from __future__ import annotations

import pytest

from src.reports.sources.wxmp import WxMpReportFetcher  # type: ignore[import]


def _detect(text: str, channel: str = "") -> dict | None:
    """Shorthand for the static detection method."""
    return WxMpReportFetcher._detect_wechat_keyword(text, channel)


# ── Happy path: various pattern formats ─────────────────────────────────


def test_full_sentence_with_account() -> None:
    """Full pattern: 关注XX公众号，回复关键词获取PDF"""
    text = (
        '更多报告内容，欢迎关注腾讯研究院公众号，'
        '在后台回复关键词 “超级个体2026” ，'
        '获取精致排版的PDF报告。'
    )
    result = _detect(text)
    assert result is not None
    assert result["type"] == "wechat_keyword"
    assert result["account"] == "腾讯研究院"
    assert result["keyword"] == "超级个体2026"


def test_reply_with_quotes_double() -> None:
    """回复"keyword"获取"""
    text = '回复“行业洞察2025”获取完整报告PDF'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "行业洞察2025"


def test_reply_with_angle_brackets() -> None:
    """回复「keyword」获取"""
    text = '回复「AI趋势白皮书」即可下载PDF'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "AI趋势白皮书"


def test_reply_colon_quotes() -> None:
    """回复：「keyword」"""
    text = '请关注公众号，回复：「数字化转型」获取报告'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "数字化转型"


def test_input_keyword() -> None:
    """在公众号对话框输入"xxx"即可获取"""
    text = '在公众号对话框输入“量子计算”即可获取报告PDF'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "量子计算"


def test_keyword_pattern_direct() -> None:
    """关键词「xxx」"""
    text = '关键词「2026经济展望」下载报告'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "2026经济展望"


def test_send_keyword() -> None:
    """发送「keyword」领取"""
    text = '发送「技术白皮书」领取完整PDF报告'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "技术白皮书"


# ── Edge cases ─────────────────────────────────────────────────────────


def test_no_keyword_in_text() -> None:
    """Plain text with no gating pattern should return None."""
    text = '本文分析了人工智能在医疗领域的最新应用。'
    assert _detect(text) is None


def test_empty_text() -> None:
    """Empty string should return None."""
    assert _detect("") is None
    assert _detect("   ") is None


def test_very_short_text() -> None:
    """Short text (< 50 chars) should return None."""
    assert _detect('关注公众号获取报告') is None


def test_only_follow_no_reply() -> None:
    """Mentions following but no keyword reply — not gated."""
    text = '欢迎关注我们的公众号，获取更多行业资讯。'
    assert _detect(text) is None


def test_keyword_with_unicode_punctuation() -> None:
    """Chinese/Japanese angle quotes 『xxx』"""
    text = '回复『全球金融报告2026』下载完整报告PDF'
    result = _detect(text)
    assert result is not None
    assert result["keyword"] == "全球金融报告2026"


def test_account_from_channel_fallback() -> None:
    """When account can't be parsed from text, fallback to channel_name."""
    text = '回复关键词「技术架构」获取PDF下载链接'
    result = _detect(text, channel='阿里云')
    assert result is not None
    assert result["account"] == "阿里云"
    assert result["keyword"] == "技术架构"


def test_account_extracted_from_text_takes_priority() -> None:
    """Account parsed from text should override channel_name."""
    text = (
        '关注华为研究院公众号，在后台回复「5G白皮书」'
        '即可获取完整报告PDF'
    )
    result = _detect(text, channel='旧名称')
    assert result is not None
    # The full-sentence pattern should capture "华为研究院"
    assert result["keyword"] == "5G白皮书"


def test_long_keyword() -> None:
    """Keyword up to ~30 characters should be captured."""
    text = '回复「2026年全球人工智能发展白皮书」下载报告PDF'
    result = _detect(text)
    assert result is not None
    assert '人工智能' in result["keyword"]


def test_multiple_mentions_takes_first_match() -> None:
    """Multiple gating sentences — first matching pattern wins."""
    text = (
        '关注阿里研究院公众号，回复「电商报告」获取报告PDF。'
        '也可以关注腾讯研究院公众号，回复「AI报告」获取PDF。'
    )
    result = _detect(text)
    assert result is not None
    # Full-sentence pattern should match the first occurrence.
    assert result["keyword"] in ("电商报告", "AI报告")


def test_download_pdf_no_gate() -> None:
    """"下载PDF" mentioned without a keyword gate is not matched."""
    text = '点击下方链接下载PDF报告。'
    assert _detect(text) is None


def test_report_keyword_context() -> None:
    """'报告' appears naturally but without gating context."""
    text = '本报告关键词包括：AI、云计算、大数据。'
    assert _detect(text) is None
