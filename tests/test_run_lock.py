"""Tests for the run_date single-instance lock (src/run_lock.py)."""

import pytest

from src.run_lock import RunLock, RunLockError


def test_acquire_creates_lock_file(tmp_path) -> None:
    lock = RunLock(tmp_path, "2026-08-25")
    path = lock.acquire()
    assert path.name == "horizon-2026-08-25.lock"
    assert path.exists()
    lock.release()


def test_second_acquire_same_day_fails(tmp_path) -> None:
    first = RunLock(tmp_path, "2026-08-25")
    first.acquire()
    try:
        second = RunLock(tmp_path, "2026-08-25")
        with pytest.raises(RunLockError):
            second.acquire()
    finally:
        first.release()


def test_different_days_do_not_conflict(tmp_path) -> None:
    day1 = RunLock(tmp_path, "2026-08-25")
    day1.acquire()
    try:
        day2 = RunLock(tmp_path, "2026-08-26")
        day2.acquire()  # 不同 run_date 互不冲突
        day2.release()
    finally:
        day1.release()


def test_release_allows_reacquire(tmp_path) -> None:
    lock = RunLock(tmp_path, "2026-08-25")
    lock.acquire()
    lock.release()
    lock.acquire()  # 释放后可再次获取
    lock.release()


def test_release_is_idempotent(tmp_path) -> None:
    # 从未 acquire 就 release 必须无害(acquire 抛错时也会走到这)
    lock = RunLock(tmp_path, "2026-08-25")
    lock.release()
    lock.release()


def test_context_manager_releases_on_exit(tmp_path) -> None:
    with RunLock(tmp_path, "2026-08-25"):
        # 持有期间,另一个实例拿不到锁
        other = RunLock(tmp_path, "2026-08-25")
        with pytest.raises(RunLockError):
            other.acquire()
    # 退出 context 后锁已释放,可再次获取
    again = RunLock(tmp_path, "2026-08-25")
    again.acquire()
    again.release()
