"""collector 的 sync_feed / run_daemon(once)测试——用 httpx.MockTransport 假 we_read。

覆盖:新文章 upsert、已存在 URL 跳过不抓正文、单篇正文失败保留文章、
max_age 窗口过滤、登录失效进入等待重登(超时停止 / 恢复后自动继续)。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.models import WxMpConfig, WxMpSourceConfig, WeReadConfigModel, WxmpArticle
from src.storage.db import HorizonDB
from src.we_read.client import WeReadClient
from src.we_read.config import WeReadConfig
from src.we_read.errors import WeReadAuthError
from src.we_read.token_store import WeReadTokenStore
from src.wxmp_collector.daemon import filter_feeds, run_daemon, sync_feed


def _mk_client(tmp_path, handler) -> WeReadClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://weread.111965.xyz")
    store = WeReadTokenStore(tmp_path / "weread.json")
    store.save("936597906", "tok123")
    return WeReadClient(
        WeReadConfig(
            request_interval=0.0,
            jitter=0.0,
            article_interval=0.0,
            article_jitter=0.0,
            token_store_path=str(tmp_path / "weread.json"),
        ),
        store=store,
        http_client=http,
        probe_mp_id="MP_WXS_001",
    )


_BODY = '<div id="js_content"><p>正文内容段落</p><img data-src="https://mmbiz.qpic.cn/x.jpg"></div>'


def _art(id_: str, url: str, *, ts: int | None = None) -> dict:
    return {
        "id": id_,
        "title": f"标题{id_}",
        "picUrl": f"https://cdn.example/{id_}.jpg",
        "publishTime": ts or int(time.time()),
        "url": url,
    }


def _handler(articles: list[dict], *, body: str = _BODY, body_calls: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/articles"):
            return httpx.Response(200, json=articles)
        if body_calls is not None:
            body_calls["n"] = body_calls.get("n", 0) + 1
        if isinstance(body, Exception):
            return httpx.Response(500, json={})
        return httpx.Response(200, text=body)

    return handler


def _feed(name: str = "机器之心", mp: str = "MP_WXS_001") -> WxMpSourceConfig:
    return WxMpSourceConfig(name=name, weread_mp_id=mp, enabled=True)


def _wxmp(feed: WxMpSourceConfig) -> WxMpConfig:
    # fake client 的节流由 WeReadConfig(0.0)控制,模型里的 pacing 字段不生效;
    # 空响应重试设为一次即弃,避免测试里意外空列表时真的 sleep 等待。
    return WxMpConfig(
        feeds=[feed],
        gather_content=True,
        weread=WeReadConfigModel(empty_retry_waits=[0.0], empty_max_retries=1),
    )


async def _close(client: WeReadClient) -> None:
    await client.aclose()


def test_sync_feed_upserts_new_articles(tmp_path) -> None:
    now = int(time.time())
    client = _mk_client(tmp_path, _handler([_art("1", "https://mp.weixin.qq.com/s/1", ts=now)]))
    feed = _feed()
    wxmp = _wxmp(feed)
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        n = asyncio.run(sync_feed(client, feed, db, wxmp))
        assert n == 1
        rows = {r["native_id"]: r for r in db.get_wxmp_articles_window(since_ts=0)}
        assert rows["1"]["id"] == "wechat:MP_WXS_001:1"
        assert rows["1"]["url"] == "https://mp.weixin.qq.com/s/1"
        assert "正文内容段落" in rows["1"]["raw_html"]
        # fix_wechat_images:data-src → src(懒加载图片修复)
        assert 'src="https://mmbiz.qpic.cn/x.jpg"' in rows["1"]["raw_html"]
        assert "data-src" not in rows["1"]["raw_html"]
        assert "正文内容段落" in rows["1"]["content_text"]
        assert rows["1"]["display_html"]  # 清洗后非空
        assert rows["1"]["cover_image"] == "https://cdn.example/1.jpg"
    finally:
        asyncio.run(_close(client))


def test_sync_feed_skips_existing_urls_and_body(tmp_path) -> None:
    now = int(time.time())
    existing = _art("0", "https://mp.weixin.qq.com/s/0", ts=now)
    new1 = _art("1", "https://mp.weixin.qq.com/s/1", ts=now)
    new2 = _art("2", "https://mp.weixin.qq.com/s/2", ts=now)
    body_calls: dict = {"n": 0}
    client = _mk_client(tmp_path, _handler([existing, new1, new2], body_calls=body_calls))
    feed = _feed()
    wxmp = _wxmp(feed)
    db = HorizonDB(str(tmp_path / "h.db"))
    # 预置已存在文章(与 existing 同 URL)
    db.upsert_wxmp_articles([
        WxmpArticle(
            id="wechat:MP_WXS_001:0", feed_name="机器之心", weread_mp_id="MP_WXS_001",
            native_id="0", title="旧文章", url=existing["url"],
            published_at=datetime.now(timezone.utc),
        )
    ])
    try:
        n = asyncio.run(sync_feed(client, feed, db, wxmp))
        assert n == 2  # 只新增 1、2
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert len(rows) == 3
        assert body_calls["n"] == 2  # 只抓两篇新文章的正文
    finally:
        asyncio.run(_close(client))


def test_sync_feed_body_failure_keeps_article(tmp_path) -> None:
    client = _mk_client(tmp_path, _handler(
        [_art("1", "https://mp.weixin.qq.com/s/1")], body=Exception("boom")
    ))
    feed = _feed()
    wxmp = _wxmp(feed)
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        n = asyncio.run(sync_feed(client, feed, db, wxmp))
        assert n == 1  # 单篇正文失败 → 文章保留、正文留空
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert len(rows) == 1
        assert rows[0]["title"] == "标题1"
        assert rows[0]["raw_html"] is None
        assert rows[0]["content_text"] is None
    finally:
        asyncio.run(_close(client))


def test_sync_feed_max_age_filters_old(tmp_path) -> None:
    now = int(time.time())
    client = _mk_client(tmp_path, _handler([
        _art("1", "https://mp.weixin.qq.com/s/1", ts=now),  # 新
        _art("2", "https://mp.weixin.qq.com/s/2", ts=now - 30 * 86400),  # 30 天前
    ]))
    feed = _feed()
    wxmp = _wxmp(feed)
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        n = asyncio.run(sync_feed(client, feed, db, wxmp, max_age_days=7))
        assert n == 1  # 老文章被窗口过滤
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert [r["native_id"] for r in rows] == ["1"]
    finally:
        asyncio.run(_close(client))


def test_run_daemon_auth_timeout_stops(tmp_path) -> None:
    """feed A 登录失效且等待重登超时 → 抛 WeReadAuthError,feed B 不再抓。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/articles"):
            mp = request.url.path.split("/")[-2]  # /mps/{mp}/articles
            if mp == "MP_A":
                return httpx.Response(401, json={})
            return httpx.Response(200, json=[
                _art("1", "https://mp.weixin.qq.com/s/b1")
            ])
        return httpx.Response(200, text=_BODY)

    client = _mk_client(tmp_path, handler)
    feed_a = _feed(name="登录失效号", mp="MP_A")
    feed_b = _feed(name="正常号", mp="MP_B")
    wxmp = _wxmp(feed_a)
    wxmp.feeds = [feed_a, feed_b]
    config = SimpleNamespace(sources=SimpleNamespace(wxmp=wxmp))
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        with pytest.raises(WeReadAuthError):
            asyncio.run(run_daemon(
                config,
                interval=(10, 20),
                once=True,
                db_path=str(tmp_path / "h.db"),
                state_path=str(tmp_path / "weread_sync.json"),
                client=client,
                inter_feed_jitter=(0, 0),  # 测试里跳过同轮到点号之间的打散睡眠
                auth_poll_sec=0.05,
                auth_max_wait_sec=0.2,  # 快速超时,模拟一直不扫码
            ))
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert len(rows) == 0  # B 未被抓 —— 等待超时后停止,不碰剩余号
    finally:
        asyncio.run(_close(client))


def test_run_daemon_auth_recovers_automatically(tmp_path) -> None:
    """feed A 登录失效 → 进入等待重登,探测到恢复后自动重试 A、继续抓 B,不抛错。"""
    calls: dict = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/articles"):
            mp = request.url.path.split("/")[-2]  # /mps/{mp}/articles
            calls["n"] += 1
            if mp == "MP_A" and calls["n"] == 1:  # 第一次请求 A → 401
                return httpx.Response(401, json={})
            if mp == "MP_A":  # 探测/重试 A → 200
                return httpx.Response(200, json=[
                    _art("a1", "https://mp.weixin.qq.com/s/a1")
                ])
            return httpx.Response(200, json=[
                _art("b1", "https://mp.weixin.qq.com/s/b1")
            ])
        return httpx.Response(200, text=_BODY)

    client = _mk_client(tmp_path, handler)
    feed_a = _feed(name="登录失效号", mp="MP_A")
    feed_b = _feed(name="正常号", mp="MP_B")
    wxmp = _wxmp(feed_a)
    wxmp.feeds = [feed_a, feed_b]
    config = SimpleNamespace(sources=SimpleNamespace(wxmp=wxmp))
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        asyncio.run(run_daemon(
            config,
            interval=(10, 20),
            once=True,
            db_path=str(tmp_path / "h.db"),
            state_path=str(tmp_path / "weread_sync.json"),
            client=client,
            inter_feed_jitter=(0, 0),
            auth_poll_sec=0.05,
            auth_max_wait_sec=60.0,  # 不超时:探测一次即恢复
        ))
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert {r["feed_name"] for r in rows} == {"登录失效号", "正常号"}  # A 重试成功,B 也入库
    finally:
        asyncio.run(_close(client))


def test_filter_feeds_matches_name_or_mp_id() -> None:
    feed_a = _feed(name="机器之心", mp="MP_A")
    feed_b = _feed(name="新智元", mp="MP_B")
    feeds = [feed_a, feed_b]
    assert filter_feeds(feeds, ["机器之心"]) == [feed_a]
    assert filter_feeds(feeds, ["MP_B"]) == [feed_b]
    assert filter_feeds(feeds, ["机器之心", "MP_B"]) == [feed_a, feed_b]
    assert filter_feeds(feeds, ["不存在的号"]) == []
    assert filter_feeds(feeds, []) == feeds
    assert filter_feeds(feeds, None) == feeds


def test_run_daemon_once_feed_filter_only_touches_selected(tmp_path) -> None:
    """once + feeds 子集 → 只抓选中的号,未选号不被触碰。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/articles"):
            mp = request.url.path.split("/")[-2]
            return httpx.Response(200, json=[
                _art(mp.lower(), f"https://mp.weixin.qq.com/s/{mp.lower()}")
            ])
        return httpx.Response(200, text=_BODY)

    client = _mk_client(tmp_path, handler)
    feed_a = _feed(name="机器之心", mp="MP_A")
    feed_b = _feed(name="新智元", mp="MP_B")
    wxmp = _wxmp(feed_a)
    wxmp.feeds = [feed_a, feed_b]
    config = SimpleNamespace(sources=SimpleNamespace(wxmp=wxmp))
    db = HorizonDB(str(tmp_path / "h.db"))
    try:
        asyncio.run(run_daemon(
            config,
            interval=(10, 20),
            feeds=[feed_a],  # 只抓机器之心
            once=True,
            db_path=str(tmp_path / "h.db"),
            state_path=str(tmp_path / "weread_sync.json"),
            client=client,
            inter_feed_jitter=(0, 0),
        ))
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert {r["feed_name"] for r in rows} == {"机器之心"}
    finally:
        asyncio.run(_close(client))


def test_cli_feed_arg_append_and_filter() -> None:
    from src.wxmp_collector.cli import _apply_feed_filter, _build_parser

    args = _build_parser().parse_args(
        ["once", "--feed", "机器之心", "--feed", "MP_WXS_3073282833"]
    )
    assert args.command == "once"
    assert args.feed == ["机器之心", "MP_WXS_3073282833"]

    feed = _feed(name="机器之心", mp="MP_A")
    assert _apply_feed_filter([feed], SimpleNamespace(feed=["机器之心"])) == [feed]
    assert _apply_feed_filter([feed], SimpleNamespace(feed=None)) == [feed]
    with pytest.raises(SystemExit):
        _apply_feed_filter([feed], SimpleNamespace(feed=["不存在的号"]))


def test_run_daemon_once_upserts_and_persists_schedule(tmp_path) -> None:
    """once 模式抓一轮全量,且 schedule 已重掷为未来时间。"""
    client = _mk_client(tmp_path, _handler([
        _art("1", "https://mp.weixin.qq.com/s/1")
    ]))
    feed = _feed()
    wxmp = _wxmp(feed)
    config = SimpleNamespace(sources=SimpleNamespace(wxmp=wxmp))
    db = HorizonDB(str(tmp_path / "h.db"))
    state_path = str(tmp_path / "weread_sync.json")
    try:
        asyncio.run(run_daemon(
            config,
            interval=(10, 20),
            once=True,
            db_path=str(tmp_path / "h.db"),
            state_path=state_path,
            client=client,
            inter_feed_jitter=(0, 0),
        ))
        rows = db.get_wxmp_articles_window(since_ts=0)
        assert len(rows) == 1
        from src.we_read.state import WeReadSyncState
        state = WeReadSyncState(state_path)
        # finally 里重掷为未来,且记录了成功同步
        assert state.feed_last_sync("MP_WXS_001") is not None
        assert state.feed_next_run("MP_WXS_001") > int(time.time())
    finally:
        asyncio.run(_close(client))
