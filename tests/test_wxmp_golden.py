"""Golden tests: real WeChat article HTML → cleaned output must not regress.

Locks the fixture captured during the spike (a genuine Tencent Research
article) so the WeRead-channel cleanup stays equivalent to the previous
rachelos pipeline (same body text kept, WeChat footer noise removed, images
preserved in display HTML).
"""

from __future__ import annotations

from pathlib import Path

from src.content_extractor import sanitize_article_html
from src.reports.sources.wxmp import WxMpReportFetcher
from src.scrapers.wxmp import _html_to_text, fix_wechat_images

FIXTURE = Path(__file__).parent / "fixtures" / "wx_article_tencent_research.html"

# WeChat footer / UI noise that the cleanup pipeline must strip.
_NOISE = ("微信扫一扫可打开此内容", "使用完整服务", "预览时标签不可点", "点个在看")
# A phrase from the article body that must be preserved.
_BODY_MARK = "波士顿动力"


def _fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_golden_news_html_to_text_keeps_body() -> None:
    text = _html_to_text(_fixture())
    assert len(text) > 500
    assert _BODY_MARK in text


def test_golden_reports_extract_text_keeps_body_no_footer() -> None:
    text = WxMpReportFetcher._extract_text(_fixture())
    assert len(text) > 500
    assert _BODY_MARK in text
    for marker in _NOISE:
        assert marker not in text


def test_golden_display_html_keeps_wechat_images() -> None:
    display = sanitize_article_html(_fixture())
    assert "mmbiz.qpic.cn" in display


def test_golden_fix_wechat_images_preserves_compact_html() -> None:
    assert fix_wechat_images("<p>hi</p>") == "<p>hi</p>"
    fixed = fix_wechat_images('<p><img data-src="https://mmbiz.qpic.cn/x"></p>')
    assert "https://mmbiz.qpic.cn/x" in fixed
    assert 'src="https://mmbiz.qpic.cn/x"' in fixed
