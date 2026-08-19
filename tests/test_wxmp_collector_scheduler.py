"""collector 调度纯函数 + WeReadSyncState 调度字段测试（无网络）。

覆盖随机间隔区间、到期判定、首启 schedule 读写与原子性。
"""

from __future__ import annotations

from src.wxmp_collector.scheduler import feed_due, random_interval
from src.we_read.state import WeReadSyncState


def test_random_interval_within_range() -> None:
    for _ in range(200):
        v = random_interval(240, 480)
        assert 240 <= v <= 480


def test_random_interval_extremes_respected() -> None:
    assert random_interval(100, 100) == 100


def test_feed_due() -> None:
    assert feed_due(None, 1000) is True  # 未排程 → 视为到期(首轮立即)
    assert feed_due(1000, 1000) is True  # 到点
    assert feed_due(1001, 1000) is False  # 未到
    assert feed_due(900, 1000) is True  # 已过


def test_schedule_roundtrip(tmp_path) -> None:
    path = tmp_path / "weread_sync.json"
    s = WeReadSyncState(path)
    assert s.feed_next_run("MP_WXS_001") is None
    s.record_feed_schedule("MP_WXS_001", 123456)
    assert s.feed_next_run("MP_WXS_001") == 123456

    # 原子写:新实例能读到
    s2 = WeReadSyncState(path)
    assert s2.feed_next_run("MP_WXS_001") == 123456
    # 覆盖更新
    s2.record_feed_schedule("MP_WXS_001", 654321)
    assert s.feed_next_run("MP_WXS_001") == 654321


def test_schedule_preserves_sync_state(tmp_path) -> None:
    """schedule 与 feeds/last_sync_at 并列,互相不覆盖(向后兼容)。"""
    path = tmp_path / "weread_sync.json"
    s = WeReadSyncState(path)
    s.record_feed_success("MP_WXS_001")
    s.record_feed_schedule("MP_WXS_001", 999)
    assert s.feed_last_sync("MP_WXS_001") is not None
    assert s.last_sync_at() is not None
    assert s.feed_next_run("MP_WXS_001") == 999
