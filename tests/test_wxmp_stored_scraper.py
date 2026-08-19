"""新闻消费侧:WxmpStoredScraper 读中间表 + 空窗口 fallback + orchestrator 分支。

不碰网络:窗口读用真实中间表,fallback 与 orchestrator 分支用 monkeypatch
替换 scraper.fetch。
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.models import (
    AIConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
    WxMpConfig,
    WxMpSourceConfig,
    WxmpArticle,
)
from src.orchestrator import HorizonOrchestrator
from src.scrapers.wxmp import WxMpScraper, WxmpStoredScraper
from src.storage.db import HorizonDB

_NOW = datetime.now(timezone.utc)


def _article(native_id: str = "1", *, ts: datetime | None = None) -> WxmpArticle:
    return WxmpArticle(
        id=f"wechat:MP_WXS_001:{native_id}",
        feed_name="机器之心",
        weread_mp_id="MP_WXS_001",
        native_id=native_id,
        title=f"标题{native_id}",
        url=f"https://mp.weixin.qq.com/s/{native_id}",
        published_at=ts or (_NOW - timedelta(hours=1)),
        raw_html="<div id=\"js_content\"><p>正文段落</p></div>",
        display_html="<p>正文段落</p>",
        content_text="正文段落",
        content_hash="h",
    )


def _scraper(db: HorizonDB, run_date: str = "2026-08-16") -> WxmpStoredScraper:
    cfg = WxMpConfig(feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")])
    return WxmpStoredScraper(cfg, db, run_date)


def test_window_read_produces_content_item(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])
    scraper = _scraper(db)

    items = asyncio.run(scraper.fetch(_NOW - timedelta(hours=24)))
    assert len(items) == 1
    item = items[0]
    assert item.id == "wechat:MP_WXS_001:1"
    assert item.source_type == SourceType.WECHAT
    assert item.title == "标题1"
    assert str(item.url) == "https://mp.weixin.qq.com/s/1"
    assert item.raw_html == "<div id=\"js_content\"><p>正文段落</p></div>"
    assert item.display_html == "<p>正文段落</p>"
    assert item.raw_content == "正文段落"
    assert item.author == "机器之心"
    assert item.metadata["extraction_mode"] == "skip"
    assert item.metadata["feed_name"] == "机器之心"
    assert item.metadata["weread_mp_id"] == "MP_WXS_001"
    assert item.metadata["category"] == ""
    assert item.published_at is not None


def test_window_excludes_consumed_run_date(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])
    db.mark_wxmp_articles_consumed_news(["wechat:MP_WXS_001:1"], "2026-08-16")
    # 同 run_date → 不重复处理
    assert asyncio.run(_scraper(db).fetch(_NOW - timedelta(hours=24))) == []


def test_empty_window_falls_back_to_live(monkeypatch, tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    scraper = _scraper(db)
    called: list[datetime] = []

    async def fake_live_fetch(self, since):
        called.append(since)
        return []

    monkeypatch.setattr(WxMpScraper, "fetch", fake_live_fetch)
    since = _NOW - timedelta(hours=24)
    items = asyncio.run(scraper.fetch(since))
    assert items == []
    assert len(called) == 1  # 空窗口 → 降级实时抓取


def test_non_empty_window_does_not_fallback(monkeypatch, tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])
    scraper = _scraper(db)
    called: list[datetime] = []

    async def fake_live_fetch(self, since):
        called.append(since)
        return []

    monkeypatch.setattr(WxMpScraper, "fetch", fake_live_fetch)
    items = asyncio.run(scraper.fetch(_NOW - timedelta(hours=24)))
    assert len(items) == 1
    assert called == []  # 窗口非空 → 不走实时


# ── orchestrator.fetch_all_sources 分支选择 ──────────────────────────────
# use_collector + run_date → WxmpStoredScraper;live_wxmp 或 run_date=None → 实时。


def _config(*, use_collector: bool = True) -> Config:
    return Config(
        ai=AIConfig(provider="openai", model="test", api_key_env="TEST_API_KEY"),
        sources=SourcesConfig(
            wxmp=WxMpConfig(
                feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")],
                use_collector=use_collector,
            )
        ),
        filtering=FilteringConfig(),
    )


async def _collect_branch(
    monkeypatch, tmp_path, *, run_date="2026-08-16", live_wxmp=False,
    use_collector=True,
) -> dict[str, int]:
    """跑 fetch_all_sources,统计 wxmp 走了 stored 还是 live。"""
    orchestrator = HorizonOrchestrator(_config(use_collector=use_collector), SimpleNamespace())
    orchestrator.db = HorizonDB(str(tmp_path / "t.db"))  # 隔离,不碰真实库
    calls = {"stored": 0, "live": 0}

    async def fake_stored(self, since):
        calls["stored"] += 1
        return []

    async def fake_live(self, since):
        calls["live"] += 1
        return []

    async def fake_empty(self, since):
        return []

    monkeypatch.setattr(WxmpStoredScraper, "fetch", fake_stored)
    monkeypatch.setattr(WxMpScraper, "fetch", fake_live)
    # 默认启用的其他源(scraper fetch 返回空,不碰网络)
    for mod_name, cls_name in (
        ("hackernews", "HackerNewsScraper"),
        ("reddit", "RedditScraper"),
        ("telegram", "TelegramScraper"),
        ("ossinsight", "OSSInsightScraper"),
    ):
        mod = importlib.import_module(f"src.scrapers.{mod_name}")
        monkeypatch.setattr(getattr(mod, cls_name), "fetch", fake_empty)

    since = _NOW - timedelta(hours=24)
    await orchestrator.fetch_all_sources(since, run_date=run_date, live_wxmp=live_wxmp)
    return calls


def test_orchestrator_uses_stored_scraper(monkeypatch, tmp_path) -> None:
    calls = asyncio.run(_collect_branch(monkeypatch, tmp_path))
    assert calls == {"stored": 1, "live": 0}


def test_orchestrator_live_wxmp_uses_realtime(monkeypatch, tmp_path) -> None:
    calls = asyncio.run(_collect_branch(monkeypatch, tmp_path, live_wxmp=True))
    assert calls == {"stored": 0, "live": 1}


def test_orchestrator_without_run_date_uses_realtime(monkeypatch, tmp_path) -> None:
    calls = asyncio.run(_collect_branch(monkeypatch, tmp_path, run_date=None))
    assert calls == {"stored": 0, "live": 1}


def test_orchestrator_use_collector_false_uses_realtime(monkeypatch, tmp_path) -> None:
    """回滚验证:use_collector=False → 完全回到旧的实时抓取。"""
    calls = asyncio.run(_collect_branch(monkeypatch, tmp_path, use_collector=False))
    assert calls == {"stored": 0, "live": 1}
