"""feed_id ↔ faker_id 映射测试（覆盖配置中全部真实公众号）。"""

from __future__ import annotations

import base64
from pathlib import Path

from src.scrapers.wxmp import faker_id_from_feed_id


def _configured_feed_ids() -> list[str]:
    """Read every configured feed_id from data/config.py via StorageManager."""
    from src.storage.manager import StorageManager

    cfg = StorageManager(data_dir=str(Path("data"))).load_config()
    wxmp = cfg.sources.wxmp
    if not wxmp:
        return []
    return [f.feed_id for f in wxmp.feeds if f.feed_id]


def test_all_configured_feeds_roundtrip() -> None:
    feed_ids = _configured_feed_ids()
    assert feed_ids, "data/config.py 应有已配置的公众号 feed_id"
    for feed_id in feed_ids:
        faker_id = faker_id_from_feed_id(feed_id)
        assert faker_id, f"{feed_id} 无法推导 fakeid"
        decoded = base64.b64decode(faker_id).decode()
        assert feed_id == "MP_WXS_" + decoded, f"{feed_id} round-trip 失败"


def test_roundtrip_is_bijective() -> None:
    """Each distinct feed_id must map to a distinct faker_id."""
    feed_ids = _configured_feed_ids()
    faker_ids = [faker_id_from_feed_id(f) for f in feed_ids]
    assert len(set(faker_ids)) == len(set(feed_ids))


def test_special_feeds_are_none() -> None:
    assert faker_id_from_feed_id("MP_WXS_FEATURED_ARTICLES") is None
    assert faker_id_from_feed_id("") is None
    assert faker_id_from_feed_id(None) is None
