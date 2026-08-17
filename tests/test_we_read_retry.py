"""Tests for WeRead pacing + empty/backoff retry helpers."""

from __future__ import annotations

import asyncio

import pytest

from src.we_read.errors import (
    WeReadEmptyResponseError,
    WeReadNetworkError,
    WeReadServerError,
)
from src.we_read.retry import RequestPacer, with_backoff, with_empty_retry


def _noop_sleep(monkeypatch) -> list:
    """Replace asyncio.sleep with an instant recorder."""
    import asyncio as _aio

    sleeps: list = []

    async def _fake(s):
        sleeps.append(s)

    monkeypatch.setattr(_aio, "sleep", _fake)
    return sleeps


# ── RequestPacer ────────────────────────────────────────────────────────────
def test_pacer_waits_at_least_interval(monkeypatch) -> None:
    sleeps = []
    import asyncio as _aio

    real_sleep = _aio.sleep

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)

    monkeypatch.setattr(_aio, "sleep", fake_sleep)
    pacer = RequestPacer(interval=10, jitter=0)

    async def main():
        await pacer.wait_before_request()
        await pacer.wait_before_request()

    asyncio.run(main())
    assert len(sleeps) == 1  # first call is immediate, second waits
    assert sleeps[0] >= 10 - 0.01  # tolerance for float clock drift


def test_pacer_immediate_when_single_call(monkeypatch) -> None:
    sleeps = _noop_sleep(monkeypatch)
    pacer = RequestPacer(interval=10, jitter=0)

    async def main():
        await pacer.wait_before_request()

    asyncio.run(main())
    assert sleeps == []


# ── with_empty_retry ────────────────────────────────────────────────────────
def test_empty_retry_passes_through_nonempty() -> None:
    calls = []

    async def f():
        calls.append(1)
        return [1]

    assert asyncio.run(with_empty_retry(f, waits=(0.001, 0.002))) == [1]
    assert len(calls) == 1


def test_empty_retry_raises_after_max(monkeypatch) -> None:
    _noop_sleep(monkeypatch)
    calls = []

    async def f():
        calls.append(1)
        return []

    with pytest.raises(WeReadEmptyResponseError):
        asyncio.run(with_empty_retry(f, waits=(0.001, 0.002), max_empties=3))
    assert len(calls) == 3  # original + 2 retries


def test_empty_retry_recovers_after_empties(monkeypatch) -> None:
    _noop_sleep(monkeypatch)
    calls = []

    async def f():
        calls.append(1)
        return [] if len(calls) < 3 else [42]

    assert asyncio.run(with_empty_retry(f, waits=(0.001, 0.002))) == [42]


# ── with_backoff ────────────────────────────────────────────────────────────
def test_backoff_succeeds_after_transient() -> None:
    calls = []

    async def f():
        calls.append(1)
        if len(calls) < 2:
            raise WeReadNetworkError("x")
        return "ok"

    assert asyncio.run(with_backoff(f, waits=(0.001, 0.002))) == "ok"
    assert len(calls) == 2


def test_backoff_raises_after_max_attempts(monkeypatch) -> None:
    _noop_sleep(monkeypatch)
    calls = []

    async def f():
        calls.append(1)
        raise WeReadServerError("boom")

    with pytest.raises(WeReadServerError):
        asyncio.run(with_backoff(f, waits=(0.001, 0.002, 0.003), max_attempts=3))
    assert len(calls) == 3


def test_backoff_does_not_catch_auth_errors() -> None:
    from src.we_read.errors import WeReadAuthError

    calls = []

    async def f():
        calls.append(1)
        raise WeReadAuthError("401")

    with pytest.raises(WeReadAuthError):
        asyncio.run(with_backoff(f, waits=(0.001, 0.002), max_attempts=3))
    assert len(calls) == 1  # not retried
