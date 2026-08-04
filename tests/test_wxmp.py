"""Unit tests for the bundled we-mp-rss WxMpScraper (process-internal)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.models import WxMpConfig, WxMpSourceConfig
from src.scrapers.wxmp import WxMpScraper, faker_id_from_feed_id


def _make_art(
    aid: str,
    title: str,
    published: datetime,
    content: str = "<p>内容</p>",
    digest: str | None = None,
) -> dict:
    art = {
        "id": aid,
        "mp_id": "MP_WXS_001",
        "title": title,
        "url": f"https://mp.weixin.qq.com/s/{aid}",
        "pic_url": f"https://mmbiz.qpic.cn/cover_{aid}",
        "content": content,
        "publish_time": published.timestamp(),
    }
    if digest:
        art["description"] = digest
    return art


_T1 = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)
_SINCE = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)


def _fake_get_articles(arts: list[dict]):
    """Return a stand-in for MpsWeb.get_Articles that fills self.articles."""

    def fake(self, faker_id="", Mps_id="", Mps_title="", CallBack=None, **kwargs):
        self.articles = []
        for a in arts:
            self.articles.append(a)
            if CallBack is not None:
                CallBack(a)

    return fake


def _scraper(config: WxMpConfig) -> WxMpScraper:
    return WxMpScraper(config, http_client=None)


def test_parse_articles_within_time_window(monkeypatch, tmp_path) -> None:
    arts = [
        _make_art("art_001", "AI 大模型最新进展", _T1),
        _make_art("art_002", "强化学习新方法", _T2),
        _make_art("art_003", "老文章", _T3),
    ]
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles(arts),
    )

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))

    titles = [i.title for i in items]
    assert "AI 大模型最新进展" in titles
    assert "强化学习新方法" in titles
    assert "老文章" not in titles
    assert len(items) == 2


def test_source_type_is_wechat(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].source_type.value == "wechat"


def test_high_content_quality_with_full_content(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1, content="<p>全文</p>")]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_content_quality == "high"
    assert items[0].content == "<p>全文</p>"


def test_full_html_content_derives_raw_and_display(monkeypatch, tmp_path) -> None:
    """微信正文 HTML 应保留到 raw_html/display_html（含图片），并给 AI 纯文本 raw_content。

    trafilatura 会丢弃微信 CDN 无扩展名的图片 URL，所以微信条目标记
    extraction_mode="skip"，由 scraper 直接产出 HTML 字段。
    """
    wechat_html = (
        "<section><h1>标题</h1><p>第一段正文</p>"
        '<p><img src="https://mmbiz.qpic.cn/szx/abc123/640"></p>'
        "<p>结尾</p></section>"
    )
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles(
            [_make_art("art_001", "AI", _T1, content=wechat_html)]
        ),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    item = asyncio.run(_scraper(config).fetch(_SINCE))[0]

    assert item.metadata["extraction_mode"] == "skip"
    assert item.content == wechat_html
    assert item.raw_html == wechat_html
    # AI 读到的是无标签的纯文本
    assert item.raw_content and "第一段正文" in item.raw_content
    assert "<p>" not in item.raw_content
    # 详情页渲染的 display_html 保留正文结构与微信图片
    assert item.display_html and "<p>" in item.display_html
    assert "https://mmbiz.qpic.cn/szx/abc123/640" in item.display_html
    # 封面
    assert item.cover_image == "https://mmbiz.qpic.cn/cover_art_001"


def test_no_content_leaves_html_fields_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1, content="")]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    item = asyncio.run(_scraper(config).fetch(_SINCE))[0]
    assert item.raw_content is None
    assert item.raw_html is None
    assert item.display_html is None
    assert item.content == ""


def test_low_content_quality_when_no_content(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1, content="")]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_content_quality == "low"
    assert items[0].content == ""


def test_metadata_populated(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(
                name="机器之心", feed_id="MP_WXS_001", category="wechat-account"
            )
        ],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    meta = items[0].metadata
    assert meta["feed_name"] == "机器之心"
    assert meta["feed_id"] == "MP_WXS_001"
    assert meta["category"] == "wechat-account"
    assert meta["pic_url"] == "https://mmbiz.qpic.cn/cover_art_001"


def test_author_is_feed_name(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].author == "机器之心"


def test_rss_summary_from_digest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles(
            [_make_art("art_001", "AI", _T1, digest="本文摘要内容")]
        ),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_summary == "本文摘要内容"


def test_empty_feed_returns_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_not_logged_in_returns_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: False)
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_disabled_feeds_are_skipped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001", enabled=False)],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_multiple_feeds(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001"),
            WxMpSourceConfig(name="量子位", feed_id="MP_WXS_002"),
        ],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert len(items) == 2


def test_feed_without_feed_id_is_skipped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.we_mp_rss.driver.success.CanGetToken", lambda: True)
    monkeypatch.setattr(
        "src.we_mp_rss.core.wx.model.web.MpsWeb.get_Articles",
        _fake_get_articles([_make_art("art_001", "AI", _T1)]),
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="未知的公众号")],  # no feed_id
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_faker_id_from_feed_id_roundtrip() -> None:
    import base64

    for feed_id in (
        "MP_WXS_3519073339",
        "MP_WXS_3554086560",
        "MP_WXS_3073282833",
        "MP_WXS_3236757533",
        "MP_WXS_3885737868",
    ):
        faker_id = faker_id_from_feed_id(feed_id)
        assert faker_id
        # round-trip: faker_id 解回原 feed_id
        decoded = base64.b64decode(faker_id).decode()
        assert feed_id == "MP_WXS_" + decoded


def test_faker_id_from_feed_id_special_feeds() -> None:
    assert faker_id_from_feed_id("MP_WXS_FEATURED_ARTICLES") is None
    assert faker_id_from_feed_id("") is None
    assert faker_id_from_feed_id(None) is None


def test_parse_publish_time() -> None:
    scraper = _scraper(WxMpConfig())
    # int unix seconds
    dt = scraper._parse_publish_time({"publish_time": _T1.timestamp()})
    assert dt is not None and dt.tzinfo is not None
    # string unix seconds
    dt2 = scraper._parse_publish_time({"publish_time": str(int(_T1.timestamp()))})
    assert dt2 is not None
    # missing / invalid
    assert scraper._parse_publish_time({}) is None
    assert scraper._parse_publish_time({"publish_time": "not-a-number"}) is None
