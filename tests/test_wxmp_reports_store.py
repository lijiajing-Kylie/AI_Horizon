"""报告消费侧:wxmp 源走 collector 中间表 store 分支(无网络)。

覆盖:store 分支填 _article_cache 并返回 native_ids、fetch_detail 出 Report、
mark_reports_consumed 写回消费标记、窗口空/use_store=False 降级实时路径。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.models import WxMpConfig, WxMpSourceConfig, WxmpArticle
from src.reports.sources import wxmp as wxmp_mod
from src.reports.sources.wxmp import WxMpReportConfig, WxMpReportFetcher
from src.storage.db import HorizonDB

_NOW = datetime.now(timezone.utc)


def _article(native_id: str = "1") -> WxmpArticle:
    body = "正文段落。" + "这里是比较长的中文正文内容。" * 20  # >100 字符,避免 URL 回退
    return WxmpArticle(
        id=f"wechat:MP_WXS_001:{native_id}",
        feed_name="机器之心",
        weread_mp_id="MP_WXS_001",
        native_id=native_id,
        title=f"标题{native_id}",
        url=f"https://mp.weixin.qq.com/s/{native_id}",
        published_at=_NOW,
        raw_html=f"<div id=\"js_content\"><p>{body}</p></div>",
        display_html=f"<p>{body}</p>",
        content_text=body,
        content_hash="h",
    )


def _cfg(db: HorizonDB, *, use_store: bool = True) -> WxMpReportConfig:
    return WxMpReportConfig(
        account_names=["机器之心"],
        wxmp=WxMpConfig(
            feeds=[WxMpSourceConfig(name="机器之心", weread_mp_id="MP_WXS_001")]
        ),
        db=db,
        use_store=use_store,
    )


def test_store_fills_cache_and_returns_ids(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1"), _article("2")])
    fetcher = WxMpReportFetcher(_cfg(db))

    ids = asyncio.run(fetcher.fetch_native_ids(None))  # store 分支不用 client
    assert set(ids) == {"1", "2"}
    assert set(fetcher._article_cache) == {"1", "2"}
    assert fetcher._article_cache["1"]["link"] == "https://mp.weixin.qq.com/s/1"
    assert fetcher._article_cache["1"]["channel_name"] == "机器之心"
    # _store_consumed_ids 存完整 id,供 mark 匹配中间表 id 列
    assert fetcher._store_consumed_ids == ["wechat:MP_WXS_001:1", "wechat:MP_WXS_001:2"]


def test_fetch_detail_produces_report(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])
    fetcher = WxMpReportFetcher(_cfg(db))
    asyncio.run(fetcher.fetch_native_ids(None))

    report = asyncio.run(fetcher.fetch_detail(None, "1"))
    assert report is not None
    assert report.id == "wxmp:1"
    assert report.source == "wxmp"
    assert report.title == "标题1"
    assert report.institution == "机器之心"
    assert report.url == "https://mp.weixin.qq.com/s/1"
    assert "正文段落" in report.content_text


def test_mark_reports_consumed(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])
    fetcher = WxMpReportFetcher(_cfg(db))
    asyncio.run(fetcher.fetch_native_ids(None))

    fetcher.mark_reports_consumed()
    # 已消费 → 报告窗口(exclude_reports_consumed)不再返回
    rows = db.get_wxmp_articles_window(since_ts=0, exclude_reports_consumed=True)
    assert rows == []


def test_store_empty_falls_through_to_realtime(monkeypatch, tmp_path) -> None:
    """中间表空 → store 分支落到实时路径;未登录 fail-open 返回空(不崩溃)。"""
    db = HorizonDB(str(tmp_path / "t.db"))  # 空表
    fetcher = WxMpReportFetcher(_cfg(db))

    async def fake_ensure_login(client):
        return False

    monkeypatch.setattr(wxmp_mod, "ensure_login", fake_ensure_login)
    ids = asyncio.run(fetcher.fetch_native_ids(None))
    assert ids == []  # 未登录 → 跳过源(实时路径的旧行为)
    assert fetcher._article_cache == {}


def test_use_store_false_skips_store_even_with_data(monkeypatch, tmp_path) -> None:
    """use_store=False → 完全不走中间表,回到实时抓取(回滚验证)。"""
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_article("1")])  # 有数据但开关关闭
    fetcher = WxMpReportFetcher(_cfg(db, use_store=False))

    async def fake_ensure_login(client):
        return False

    monkeypatch.setattr(wxmp_mod, "ensure_login", fake_ensure_login)
    ids = asyncio.run(fetcher.fetch_native_ids(None))
    assert ids == []
    assert fetcher._article_cache == {}  # 没读中间表
