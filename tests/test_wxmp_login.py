"""登录态（token 读写 / 状态判断）测试。"""

from __future__ import annotations

import time

import src.we_mp_rss
from src.we_mp_rss.driver import success, token


def _login_data(remaining: int = 3600) -> dict:
    return {
        "token": "tok_abc",
        "cookies_str": "slave_sid=xxx; bizuin=yyy",
        "fingerprint": "fp_1",
        "expiry": {
            "expiry_time": "2026-08-02 00:00:00",
            "remaining_seconds": remaining,
            "expiry_timestamp": time.time() + remaining,
        },
    }


def test_set_token_and_get(tmp_path) -> None:
    src.we_mp_rss.init(_FakeCfg(), str(tmp_path))
    token.configure(str(tmp_path))

    token.set_token(_login_data())
    assert token.get("token") == "tok_abc"
    assert "slave_sid" in token.get("cookie")


def test_can_get_token_true_when_valid(tmp_path) -> None:
    src.we_mp_rss.init(_FakeCfg(), str(tmp_path))
    token.configure(str(tmp_path))

    token.set_token(_login_data())
    success.setStatus(True)
    assert success.CanGetToken() is True


def test_can_get_token_false_when_logged_out(tmp_path) -> None:
    src.we_mp_rss.init(_FakeCfg(), str(tmp_path))
    token.configure(str(tmp_path))

    success.setStatus(False)
    assert success.CanGetToken() is False


def test_can_get_token_false_when_expired(tmp_path) -> None:
    src.we_mp_rss.init(_FakeCfg(), str(tmp_path))
    token.configure(str(tmp_path))

    token.set_token(_login_data(remaining=-10))
    success.setStatus(True)
    assert success.CanGetToken() is False


def test_store_save_and_load_cookies(tmp_path) -> None:
    src.we_mp_rss.init(_FakeCfg(), str(tmp_path))
    from src.we_mp_rss.driver import store

    store.configure(str(tmp_path))
    cookies = [
        {"name": "slave_sid", "value": "s", "domain": ".weixin.qq.com"},
        {"name": "token", "value": "t", "domain": ".weixin.qq.com"},
        {"name": "_clck", "value": "c", "domain": ".qq.com"},
    ]
    store.Store.save(cookies)
    loaded = store.Store.load()
    assert isinstance(loaded, list)
    names = [c["name"] for c in loaded]
    assert "slave_sid" in names
    assert "token" not in names  # filtered out
    assert "_clck" not in names  # filtered out


class _FakeCfg:
    gather_content = True
    clean_html = False
    proxy = None
    max_page = 1
    gather_interval = 3
    data_dir = "data/wxmp"
