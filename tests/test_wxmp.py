"""Unit tests for the WeRead-channel WxMpScraper (mock we_read client)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.models import WxMpConfig, WxMpSourceConfig, WeReadConfigModel
from src.scrapers.wxmp import WxMpScraper
from src.we_read.errors import WeReadAuthError, WeReadServerError
from src.we_read.model import WeReadArticle


def _make_art(
    aid: str,
    title: str,
    published: datetime,
    html: str = "<p>内容</p>",
    url: str | None = None,
) -> tuple[WeReadArticle, str]:
    """Return (WeReadArticle, article-HTML) pair for the fake client."""
    return (
        WeReadArticle(
            id=aid,
            title=title,
            url=url or f"https://mp.weixin.qq.com/s/{aid}",
            pic_url=f"https://mmbiz.qpic.cn/cover_{aid}",
            publish_time=int(published.timestamp()),
        ),
        html,
    )


_T1 = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)
_SINCE = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)


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
    """Stand-in for WeReadClient: fixed article list + html-per-url map."""

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


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(
        "src.scrapers.wxmp.build_client_from_wxmp_config",
        lambda cfg, http_client=None: client,
    )


def _scraper(config: WxMpConfig) -> WxMpScraper:
    return WxMpScraper(config, http_client=None)


def test_parse_articles_within_time_window(monkeypatch, tmp_path) -> None:
    a1, h1 = _make_art("art_001", "AI 大模型最新进展", _T1)
    a2, h2 = _make_art("art_002", "强化学习新方法", _T2)
    a3, _ = _make_art("art_003", "老文章", _T3)
    client = _FakeClient([a1, a2, a3], html_by_url={a1.url: h1, a2.url: h2})
    _patch_client(monkeypatch, client)

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))

    titles = [i.title for i in items]
    assert "AI 大模型最新进展" in titles
    assert "强化学习新方法" in titles
    assert "老文章" not in titles
    assert len(items) == 2


def test_source_type_is_wechat(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].source_type.value == "wechat"


def test_high_content_quality_with_full_content(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1, html="<p>全文</p>")
    _patch_client(monkeypatch, _FakeClient([a1], html_by_url={a1.url: "<p>全文</p>"}))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_content_quality == "high"
    assert "<p>全文</p>" in items[0].content


def test_full_html_content_derives_raw_and_display(monkeypatch, tmp_path) -> None:
    """微信正文 HTML 应保留到 raw_html/display_html（含图片），并给 AI 纯文本 raw_content。"""
    wechat_html = (
        "<section><h1>标题</h1><p>第一段正文</p>"
        '<p><img src="https://mmbiz.qpic.cn/szx/abc123/640"></p>'
        "<p>结尾</p></section>"
    )
    a1, _ = _make_art("art_001", "AI", _T1, html=wechat_html)
    _patch_client(
        monkeypatch, _FakeClient([a1], html_by_url={a1.url: wechat_html})
    )
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    item = asyncio.run(_scraper(config).fetch(_SINCE))[0]

    assert item.metadata["extraction_mode"] == "skip"
    assert item.raw_html and "第一段正文" in item.raw_html
    # AI 读到的是无标签的纯文本
    assert item.raw_content and "第一段正文" in item.raw_content
    assert "<p>" not in item.raw_content
    # 详情页渲染的 display_html 保留正文结构与微信图片（图片走 weserv 代理）
    assert item.display_html
    assert "https://images.weserv.nl/?url=" in item.display_html
    assert "mmbiz.qpic.cn" in item.display_html
    # 封面
    assert item.cover_image == "https://mmbiz.qpic.cn/cover_art_001"


def test_no_content_leaves_html_fields_empty(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1, html="")
    _patch_client(monkeypatch, _FakeClient([a1], html_by_url={a1.url: ""}))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    item = asyncio.run(_scraper(config).fetch(_SINCE))[0]
    assert item.raw_content is None
    assert item.raw_html is None
    assert item.display_html is None
    assert item.content == ""


def test_article_html_failure_keeps_item(monkeypatch, tmp_path) -> None:
    """单篇正文抓取失败(302) → 文章保留(content="", quality=low)，不拖垮 feed。"""
    a1, _ = _make_art("art_001", "AI", _T1, html="<p>正文</p>")

    class _FlakyHtml(_FakeClient):
        async def fetch_article_html(self, url: str) -> str:
            raise WeReadServerError("正文抓取被拒 status=302")

    _patch_client(monkeypatch, _FlakyHtml([a1]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert len(items) == 1
    assert items[0].title == "AI"
    assert items[0].content == ""
    assert items[0].rss_content_quality == "low"


def test_low_content_quality_when_no_content(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1, html="")
    _patch_client(monkeypatch, _FakeClient([a1], html_by_url={a1.url: ""}))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_content_quality == "low"
    assert items[0].content == ""


def test_metadata_populated(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(
                name="机器之心", weread_mp_id="MP_WXS_001", category="wechat-account"
            )
        ],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    meta = items[0].metadata
    assert meta["feed_name"] == "机器之心"
    assert meta["weread_mp_id"] == "MP_WXS_001"
    assert meta["category"] == "wechat-account"
    assert meta["pic_url"] == "https://mmbiz.qpic.cn/cover_art_001"


def test_author_is_feed_name(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].author == "机器之心"


def test_rss_summary_empty_from_weread(monkeypatch, tmp_path) -> None:
    """we-read 文章不含 description 摘要，rss_summary 为空（数据源差异）。"""
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items[0].rss_summary == ""


def test_empty_feed_returns_empty(monkeypatch, tmp_path) -> None:
    """list_articles 返回空 → 空重试(短 waits) → 抛错被 catch → 空结果。"""
    _patch_client(monkeypatch, _FakeClient([]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
        weread=WeReadConfigModel(empty_retry_waits=[0.001, 0.002]),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_not_logged_in_returns_empty(monkeypatch, tmp_path) -> None:
    _patch_client(monkeypatch, _FakeClient([], store_present=False))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_auth_failure_triggers_relogin_and_retries(monkeypatch, tmp_path) -> None:
    """首次 list_articles 抛 401 → ensure_login(force=True) → 重试全部 feed。"""
    calls = {"n": 0}

    class _FlakyClient(_FakeClient):
        async def list_articles(self, mp_id: str, page: int = 1):
            calls["n"] += 1
            if calls["n"] == 1:
                raise WeReadAuthError("微信读书登录失效(401)")
            return self.articles

    a1, h1 = _make_art("art_001", "AI 大模型", _T1)
    _patch_client(monkeypatch, _FlakyClient([a1], html_by_url={a1.url: h1}))

    relogin = {"calls": 0}

    async def _ensure_login(client, *, print_fn=print, timeout=120.0, force=False):
        relogin["calls"] += 1
        return True  # 模拟扫码成功

    monkeypatch.setattr("src.scrapers.wxmp.ensure_login", _ensure_login)

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert len(items) == 1
    assert items[0].title == "AI 大模型"
    # fetch 开头一次 + 401 后 force 重登一次
    assert relogin["calls"] == 2


def test_auth_failure_fails_open_when_relogin_fails(monkeypatch, tmp_path) -> None:
    """401 后重登失败 → 跳过微信源（fail-open），不无限重试。"""
    async def _flaky_list(self, mp_id: str = "", page: int = 1):
        raise WeReadAuthError("微信读书登录失效(401)")

    monkeypatch.setattr(_FakeClient, "list_articles", _flaky_list)
    _patch_client(monkeypatch, _FakeClient([]))

    relogin = {"calls": 0}

    async def _ensure_login(client, *, print_fn=print, timeout=120.0, force=False):
        relogin["calls"] += 1
        # 开头 token 有效 → True；401 后的 force 重登 → False（扫码失败）
        return not force

    monkeypatch.setattr("src.scrapers.wxmp.ensure_login", _ensure_login)

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []
    # 只重登一次就 fail-open，没有无限循环
    assert relogin["calls"] == 2


def test_disabled_feeds_are_skipped(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(
                name="机器之心", weread_mp_id="MP_WXS_001", enabled=False
            )
        ],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


def test_multiple_feeds(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001"),
            WxMpSourceConfig(name="量子位", weread_mp_id="MP_WXS_002"),
        ],
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert len(items) == 2


def test_feed_without_weread_mp_id_is_skipped(monkeypatch, tmp_path) -> None:
    a1, _ = _make_art("art_001", "AI", _T1)
    _patch_client(monkeypatch, _FakeClient([a1]))
    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="未知的公众号")],  # no weread_mp_id
        data_dir=str(tmp_path),
    )
    items = asyncio.run(_scraper(config).fetch(_SINCE))
    assert items == []


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
