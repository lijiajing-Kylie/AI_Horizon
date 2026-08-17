"""Tests for the WeRead token store (data/auth/weread.json)."""

from __future__ import annotations

import time

from src.we_read.token_store import WeReadTokenStore


def _store(tmp_path):
    return WeReadTokenStore(tmp_path / "auth" / "weread.json")


def test_save_and_load(tmp_path) -> None:
    store = _store(tmp_path)
    assert not store.is_present()
    store.save("vid1", "token1")
    assert store.is_present()
    assert store.get("vid") == "vid1"
    assert store.get("token") == "token1"


def test_created_at_and_last_success_initialized(tmp_path) -> None:
    store = _store(tmp_path)
    store.save("v", "t")
    data = store.load()
    assert data["created_at"] > 0
    assert data["last_success"] > 0


def test_touch_success_updates_last_success(tmp_path) -> None:
    store = _store(tmp_path)
    store.save("v", "t")
    before = store.load()["last_success"]
    time.sleep(1.05)
    store.touch_success()
    after = store.load()["last_success"]
    assert after > before


def test_age_seconds(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.age_seconds() is None
    store.save("v", "t")
    assert store.age_seconds() is not None
    assert store.age_seconds() >= 0


def test_clear(tmp_path) -> None:
    store = _store(tmp_path)
    store.save("v", "t")
    store.clear()
    assert not store.is_present()
    assert not store.path.exists()


def test_corrupt_file_returns_none(tmp_path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() is None
    assert not store.is_present()
