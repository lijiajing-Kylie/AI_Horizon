"""Unit tests for the WeRead-channel WxMpReportFetcher (mock we_read client)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.models import WxMpConfig, WxMpSourceConfig
from src.reports.sources.wxmp import WxMpReportConfig, WxMpReportFetcher
from src.we_read.errors import WeReadServerError
from src.we_read.model import WeReadArticle


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


_LONG_BODY = "这是报告正文内容，" + "详细分析段落" * 20 + "。"


@pytest.fixture(autouse=True)
def _non_interactive(monkeypatch):
    """Keep every test off the interactive QR-prompt branch."""
    monkeypatch.setattr("src.we_read.is_interactive", lambda: False)


class _FakeStore:
    def __init__(self, present: bool = True) -> None:
        self.present = present

    def is_present(self) -> bool:
        return self.present


class _FakeClient:
    """Stand-in for WeReadClient used by the reports fetcher."""

    def __init__(
        self,
        articles: list[WeReadArticle],
        store_present: bool = True,
        html_by_url: dict | None = None,
    ) -> None:
        self.articles = articles
        self.store = _FakeStore(store_present)
        self.html_by_url = html_by_url or {}

    async def list_articles(self, mp_id: str, page: int = 1) -> list[WeReadArticle]:
        return self.articles

    async def fetch_article_html(self, url: str) -> str:
        return self.html_by_url.get(url, "")


def _make_art(
    aid: str,
    title: str,
    published_ts: float,
    html: str | None = None,
) -> tuple[WeReadArticle, str]:
    return (
        WeReadArticle(
            id=aid,
            title=title,
            url=f"https://mp.weixin.qq.com/s/{aid}",
            pic_url="https://mmbiz.qpic.cn/cover",
            publish_time=int(published_ts),
        ),
        html or f"<p>{_LONG_BODY}</p>",
    )


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(
        "src.reports.sources.wxmp.build_client_from_wxmp_config",
        lambda cfg, http_client=None: client,
    )


def _fetcher(data_dir: str) -> WxMpReportFetcher:
    wc = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=data_dir,
    )
    cfg = WxMpReportConfig(
        account_names=["机器之心"],
        known_feeds={"机器之心": "MP_WXS_001"},
        wxmp=wc,
        data_dir=data_dir,
    )
    return WxMpReportFetcher(cfg)


def test_fetch_native_ids_gathers_articles(monkeypatch, tmp_path) -> None:
    fresh, h1 = _make_art("art_001", "最新报告", _now_ts())
    old, _ = _make_art(
        "art_002", "过期报告", _now_ts() - timedelta(days=10).total_seconds()
    )
    _patch_client(
        monkeypatch, _FakeClient([fresh, old], html_by_url={fresh.url: h1})
    )

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    assert ids == ["art_001"]
    assert "art_001" in fetcher._article_cache


def test_fetch_detail_returns_report(monkeypatch, tmp_path) -> None:
    art, h = _make_art("art_001", "腾讯研究院报告", _now_ts())
    _patch_client(monkeypatch, _FakeClient([art], html_by_url={art.url: h}))

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), ids[0]))

    assert report is not None
    assert report.source == "wxmp"
    assert report.title == "腾讯研究院报告"
    assert report.institution == "机器之心"
    assert "报告正文内容" in report.content_text
    assert report.id == "wxmp:art_001"
    # display_html 由 raw_html 清洗生成，保留段落结构
    assert report.display_html
    assert "<p" in report.display_html


def test_article_html_failure_keeps_report(monkeypatch, tmp_path) -> None:
    """单篇正文抓取失败(302) → 报告仍纳入，不拖垮整个报告源。"""
    art, _ = _make_art("art_001", "腾讯研究院报告", _now_ts())

    class _FlakyHtml(_FakeClient):
        async def fetch_article_html(self, url: str) -> str:
            raise WeReadServerError("正文抓取被拒 status=302")

    _patch_client(monkeypatch, _FlakyHtml([art]))

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    assert ids == ["art_001"]


def test_fetch_detail_display_html_preserves_table(monkeypatch, tmp_path) -> None:
    # 正文足够长（提取文本 >100 字符），避免触发 URL 回退，走主路径。
    html = (
        "<p>标题</p>"
        '<table border="1"><tr><td colspan="2" '
        'style="border:1px solid">数据</td></tr></table>'
        "<p>" + "这是一段足够长的正文说明文字" * 10 + "</p>"
    )
    art, _ = _make_art("art_002", "含表格报告", _now_ts(), html)
    _patch_client(monkeypatch, _FakeClient([art], html_by_url={art.url: html}))

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), ids[0]))

    assert report is not None
    assert "<table" in report.display_html
    assert "<td" in report.display_html
    assert 'colspan="2"' in report.display_html
    assert "style=" not in report.display_html
    assert "数据" in report.display_html


def test_fetch_detail_fallback_sets_display_html_none(monkeypatch, tmp_path) -> None:
    # 缓存 HTML 过短（<100 字符）触发 URL 回退 → display_html 置 None
    short_html = "<p>短</p>"
    art, _ = _make_art("art_003", "回退报告", _now_ts(), short_html)
    _patch_client(
        monkeypatch, _FakeClient([art], html_by_url={art.url: short_html})
    )

    async def fake_fetch(client, url):
        return "来自URL回退的" + "长正文内容" * 20

    monkeypatch.setattr(
        WxMpReportFetcher,
        "_fetch_content_from_url",
        staticmethod(fake_fetch),
    )

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), ids[0]))

    assert report is not None
    assert report.display_html is None
    assert "来自URL回退" in report.content_text


def test_fetch_detail_unknown_id_returns_none(tmp_path) -> None:
    fetcher = _fetcher(str(tmp_path))
    fetcher._article_cache = {}
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), "missing"))
    assert report is None


def test_not_logged_in_returns_empty(monkeypatch, tmp_path) -> None:
    _patch_client(monkeypatch, _FakeClient([], store_present=False))
    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    assert ids == []


def test_clean_article_text_removes_noise() -> None:
    text = (
        "报告正文内容\n"
        "关注该公众号\n"
        "推荐阅读\n"
        "其他内容\n"
        "微信扫一扫可打开此内容"
    )
    cleaned = WxMpReportFetcher._clean_article_text(text)
    # "关注该公众号" 与 "微信扫一扫可打开此内容" 是噪声行/结束标记
    assert "关注该公众号" not in cleaned
    assert "微信扫一扫可打开此内容" not in cleaned
    assert "报告正文内容" in cleaned
