"""Tests for the surgical data/config.py editor (subscribe/migrate writer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.pyconfig_editor import (
    ConfigEditError,
    list_wxmp_feeds,
    set_wxmp_enabled,
    update_wxmp_feed,
)

_CONFIG = """\
sources = {
    # 微信公众平台配置
    "wxmp": {
        "enabled": False,
        "feeds": [
            # 加公众号就在这里加一条，feed_id 是公众号的 MP_WXS_ id
            {"name": "机器之心", "feed_id": "MP_WXS_001"},
            {"name": "量子位", "feed_id": "MP_WXS_002"},
        ],
    },
}
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "config.py"
    p.write_text(_CONFIG, encoding="utf-8")
    return p


def test_update_existing_feed_preserves_other_fields(tmp_path) -> None:
    p = _write(tmp_path)
    result = update_wxmp_feed(p, name="机器之心", weread_mp_id="MP_WXS_999")
    assert result["weread_mp_id"] == "MP_WXS_999"

    feeds = list_wxmp_feeds(p)
    jx = next(f for f in feeds if f["name"] == "机器之心")
    assert jx["weread_mp_id"] == "MP_WXS_999"
    assert jx["feed_id"] == "MP_WXS_001"  # other fields preserved
    assert len(feeds) == 2  # no duplicate added


def test_update_matches_case_insensitive(tmp_path) -> None:
    p = _write(tmp_path)
    update_wxmp_feed(p, name="机器之心", weread_mp_id="MP_WXS_999")
    assert list_wxmp_feeds(p)[0]["weread_mp_id"] == "MP_WXS_999"


def test_add_new_feed_appends(tmp_path) -> None:
    p = _write(tmp_path)
    update_wxmp_feed(p, name="新智元", weread_mp_id="MP_WXS_777")
    feeds = list_wxmp_feeds(p)
    assert len(feeds) == 3
    assert feeds[-1]["name"] == "新智元"
    assert feeds[-1]["weread_mp_id"] == "MP_WXS_777"


def test_preserves_comments_and_structure(tmp_path) -> None:
    p = _write(tmp_path)
    update_wxmp_feed(p, name="机器之心", weread_mp_id="MP_WXS_999")
    text = p.read_text(encoding="utf-8")
    # comments must survive surgical edit
    assert "加公众号就在这里加一条" in text
    assert "微信公众平台配置" in text
    assert 'sources = {' in text


def test_backup_created(tmp_path) -> None:
    p = _write(tmp_path)
    update_wxmp_feed(p, name="机器之心", weread_mp_id="MP_WXS_999")
    assert p.with_name("config.py.bak").exists()


def test_set_wxmp_enabled(tmp_path) -> None:
    p = _write(tmp_path)
    set_wxmp_enabled(p, True)
    assert '"enabled": True' in p.read_text(encoding="utf-8")
    set_wxmp_enabled(p, False)
    assert '"enabled": False' in p.read_text(encoding="utf-8")


def test_missing_feeds_raises(tmp_path) -> None:
    p = tmp_path / "config.py"
    p.write_text('sources = {"wxmp": {"enabled": True}}', encoding="utf-8")
    with pytest.raises(ConfigEditError):
        update_wxmp_feed(p, name="x", weread_mp_id="MP_WXS_1")


def test_missing_wxmp_raises(tmp_path) -> None:
    p = tmp_path / "config.py"
    p.write_text('sources = {"rss": []}', encoding="utf-8")
    with pytest.raises(ConfigEditError):
        update_wxmp_feed(p, name="x", weread_mp_id="MP_WXS_1")


def test_list_feeds_returns_plain_dicts(tmp_path) -> None:
    p = _write(tmp_path)
    feeds = list_wxmp_feeds(p)
    assert len(feeds) == 2
    assert feeds[0]["name"] == "机器之心"
    assert feeds[0]["feed_id"] == "MP_WXS_001"
