"""Unit tests for the bundled we-mp-rss WxMpReportFetcher."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from src.models import WxMpConfig, WxMpSourceConfig
from src.reports.sources.wxmp import WxMpReportConfig, WxMpReportFetcher


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


_LONG_BODY = "这是报告正文内容，" + "详细分析段落" * 20 + "。"


def _make_art(
    aid: str,
    title: str,
    published_ts: float,
    content: str = f"<p>{_LONG_BODY}</p>",
) -> dict:
    return {
        "id": aid,
        "mp_id": "MP_WXS_001",
        "title": title,
        "url": f"https://mp.weixin.qq.com/s/{aid}",
        "pic_url": "https://mmbiz.qpic.cn/cover",
        "content": content,
        "publish_time": published_ts,
        "description": "摘要",
    }


def _patch_gather(monkeypatch, arts: list[dict]) -> None:
    def fake_get_articles(self, faker_id="", Mps_id="", Mps_title="", CallBack=None, **kwargs):
        self.articles = []
        for a in arts:
            self.articles.append(a)
            if CallBack is not None:
                CallBack(a)

    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        fake_get_articles,
    )
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)


def _fetcher(data_dir: str) -> WxMpReportFetcher:
    wc = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
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
    fresh = _make_art("art_001", "最新报告", _now_ts())
    old = _make_art("art_002", "过期报告", _now_ts() - timedelta(days=10).total_seconds())
    _patch_gather(monkeypatch, [fresh, old])

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    assert ids == ["art_001"]
    assert "art_001" in fetcher._article_cache


def test_fetch_detail_returns_report(monkeypatch, tmp_path) -> None:
    art = _make_art("art_001", "腾讯研究院报告", _now_ts())
    _patch_gather(monkeypatch, [art])

    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), ids[0]))

    assert report is not None
    assert report.source == "wxmp"
    assert report.title == "腾讯研究院报告"
    assert report.institution == "机器之心"
    assert "报告正文内容" in report.content_text
    assert report.id == "wxmp:art_001"


def test_fetch_detail_unknown_id_returns_none(monkeypatch, tmp_path) -> None:
    _patch_gather(monkeypatch, [])
    fetcher = _fetcher(str(tmp_path))
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), "missing"))
    assert report is None


def test_not_logged_in_returns_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: False)
    fetcher = _fetcher(str(tmp_path))
    ids = asyncio.run(fetcher.fetch_native_ids(AsyncMock()))
    assert ids == []


def test_keyword_gated_pdf_detection() -> None:
    art = {
        "id": "art_kw",
        "title": "报告：关注公众号回复关键词获取PDF",
        "description": "",
        "content": (
            f"<p>本报告为付费内容。关注某机构公众号，"
            f"回复「下载报告」即可获取PDF。{_LONG_BODY}</p>"
        ),
        "link": "https://mp.weixin.qq.com/s/art_kw",
        "channel_name": "某机构",
        "updated": _now_ts(),
        "image": "",
        "is_featured": False,
    }
    fetcher = WxMpReportFetcher(WxMpReportConfig())
    fetcher._article_cache["art_kw"] = art
    report = asyncio.run(fetcher.fetch_detail(AsyncMock(), "art_kw"))

    assert report is not None
    assert any(p["type"] == "wechat_keyword" for p in report.pdf_urls)
    kw_entry = next(p for p in report.pdf_urls if p["type"] == "wechat_keyword")
    assert kw_entry["keyword"] == "下载报告"
    assert kw_entry["account"] == "某机构"


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
