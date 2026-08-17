"""Tests for WeReadClient against an httpx.MockTransport (no network)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.we_read.client import WeReadClient
from src.we_read.config import WeReadConfig
from src.we_read.errors import (
    WeReadAuthError,
    WeReadError400,
    WeReadRateLimitError,
    WeReadServerError,
)
from src.we_read.token_store import WeReadTokenStore


def asyncio_run(coro):
    return asyncio.run(coro)


def _cfg() -> WeReadConfig:
    return WeReadConfig(
        request_interval=0.0,
        jitter=0.0,
        article_interval=0.0,
        article_jitter=0.0,
    )


def _mk_client(tmp_path, handler, *, with_token: bool = True) -> WeReadClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        transport=transport, base_url="https://weread.111965.xyz"
    )
    store = WeReadTokenStore(tmp_path / "weread.json")
    if with_token:
        store.save("936597906", "tok123")
    return WeReadClient(
        _cfg(), store=store, http_client=http, probe_mp_id="MP_WXS_001"
    )


def _json_handler(path: str, payload):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path, request.url
        return httpx.Response(200, json=payload)

    return handler


def test_create_login_returns_uuid_and_scan_url(tmp_path) -> None:
    client = _mk_client(
        tmp_path,
        _json_handler(
            "/api/v2/login/platform",
            {"uuid": "u1", "scanUrl": "https://open.weixin.qq.com/confirm?uuid=u1"},
        ),
    )
    uuid, scan = asyncio_run(client.create_login())
    assert uuid == "u1"
    assert "open.weixin.qq.com" in scan


def test_poll_login_persists_token(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"message": "waiting"})
        return httpx.Response(
            200, json={"vid": 936597906, "token": "tok_new", "username": "植绒狗"}
        )

    client = _mk_client(tmp_path, handler)
    client.config = client.config  # keep
    session = asyncio_run(client.poll_login("u1", timeout=30))
    assert session.token == "tok_new"
    assert session.username == "植绒狗"
    assert client.store.get("token") == "tok_new"  # persisted


def test_resolve_share_maps_fields(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "name": "腾讯研究院",
                    "id": "MP_WXS_2399148061",
                    "cover": "http://wx.qlogo.cn/cover",
                    "intro": "腾讯公司设立的社会科学研究机构",
                    "updateTime": 1786352496,
                }
            ],
        )

    client = _mk_client(tmp_path, handler)
    infos = asyncio_run(client.resolve_share("https://mp.weixin.qq.com/s/abc"))
    assert len(infos) == 1
    assert infos[0].name == "腾讯研究院"
    assert infos[0].id == "MP_WXS_2399148061"
    assert infos[0].intro.startswith("腾讯公司")


def test_list_articles_returns_empty_as_list(tmp_path) -> None:
    client = _mk_client(tmp_path, _json_handler("/api/v2/platform/mps/MP_WXS_001/articles", []))
    arts = asyncio_run(client.list_articles("MP_WXS_001"))
    assert arts == []


def test_list_articles_maps_camel_case(tmp_path) -> None:
    client = _mk_client(
        tmp_path,
        _json_handler(
            "/api/v2/platform/mps/MP_WXS_001/articles",
            [
                {
                    "id": "EXvI9VdterDx6l71fOioJQ",
                    "title": "AI 标题",
                    "picUrl": "https://mmbiz.qpic.cn/cover",
                    "publishTime": 1786352496,
                    "url": "https://mp.weixin.qq.com/s/EXvI9VdterDx6l71fOioJQ",
                }
            ],
        ),
    )
    arts = asyncio_run(client.list_articles("MP_WXS_001"))
    assert arts[0].title == "AI 标题"
    assert arts[0].publish_time == 1786352496
    assert arts[0].pic_url.startswith("https://mmbiz")


def test_fetch_article_html_extracts_js_content(tmp_path) -> None:
    html = (
        "<html><body><div class='rich_media_content'><p>正文段落</p>"
        '<p><img data-src="https://mmbiz.qpic.cn/x"></p></div></body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    client = _mk_client(tmp_path, handler)
    body = asyncio_run(client.fetch_article_html("https://mp.weixin.qq.com/s/x"))
    assert "正文段落" in body
    assert "mmbiz.qpic.cn/x" in body


def test_fetch_article_html_follows_redirects(tmp_path) -> None:
    """微信文章 302 失效/风控 → 显式跟随重定向，拿到最终正文而不是 302 硬错误。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                302, headers={"Location": "https://mp.weixin.qq.com/s/target"}
            )
        return httpx.Response(
            200, text="<div id='js_content'><p>重定向后的正文</p></div>"
        )

    client = _mk_client(tmp_path, handler)
    body = asyncio_run(client.fetch_article_html("https://mp.weixin.qq.com/s/x"))
    assert "重定向后的正文" in body
    assert calls["n"] == 2


def test_error_mapping_400(tmp_path) -> None:
    client = _mk_client(
        tmp_path,
        _json_handler(
            "/api/v2/platform/mps/MP_WXS_BAD/articles",
            {"message": "id(1): WeReadError400", "statusCode": 500},
        ),
    )
    # 400 body is delivered with status 500 by the forwarding service
    client = _mk_client(
        tmp_path,
        lambda r: httpx.Response(500, json={"message": "WeReadError400"}),
    )
    with pytest.raises(WeReadError400):
        asyncio_run(client.list_articles("MP_WXS_BAD"))


def test_error_mapping_401(tmp_path) -> None:
    client = _mk_client(
        tmp_path, lambda r: httpx.Response(401, json={"message": "unauth"})
    )
    with pytest.raises(WeReadAuthError):
        asyncio_run(client.list_articles("MP_WXS_001"))


def test_error_mapping_429(tmp_path) -> None:
    client = _mk_client(
        tmp_path, lambda r: httpx.Response(429, json={"message": "slow down"})
    )
    with pytest.raises(WeReadRateLimitError):
        asyncio_run(client.list_articles("MP_WXS_001"))


def test_validate_token_401_means_invalid(tmp_path) -> None:
    client = _mk_client(
        tmp_path, lambda r: httpx.Response(401, json={})
    )
    assert asyncio_run(client.validate_token()) is False


def test_validate_token_200_means_valid(tmp_path) -> None:
    client = _mk_client(tmp_path, _json_handler("/api/v2/platform/mps/MP_WXS_001/articles", []))
    assert asyncio_run(client.validate_token()) is True


def test_validate_token_no_store_means_invalid(tmp_path) -> None:
    client = _mk_client(tmp_path, lambda r: httpx.Response(200, json=[]), with_token=False)
    assert asyncio_run(client.validate_token()) is False
