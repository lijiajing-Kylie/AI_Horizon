"""Request pacing and retry helpers for the WeRead channel.

The forwarding service rate-limits by **silently returning ``[]``** from the
articles endpoint — an empty list must NOT be treated as "no articles".
:func:`with_empty_retry` retries with backoff and only raises after
``max_empties`` consecutive empties.

Pacing lives here as :class:`RequestPacer`; the client calls
``await pacer.wait_before_request()`` once per request, so callers wrapping a
list call do NOT also pace (avoiding double throttling).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, List, Tuple

from .errors import (
    WeReadEmptyResponseError,
    WeReadNetworkError,
    WeReadRateLimitError,
    WeReadServerError,
)

logger = logging.getLogger(__name__)

# Transient errors worth retrying with backoff.
_TRANSIENT = (WeReadServerError, WeReadRateLimitError, WeReadNetworkError)


class RequestPacer:
    """Throttle requests to a minimum interval (± jitter), lock-guarded.

    The lock is held across the wait so concurrent callers (e.g. a future
    parallelized feed loop) cannot burst past the rate limit.
    """

    def __init__(self, interval: float = 20.0, jitter: float = 5.0) -> None:
        self.interval = max(0.0, interval)
        self.jitter = max(0.0, jitter)
        self._lock = asyncio.Lock()
        self._last_ts = -1.0  # sentinel: first request passes immediately

    async def wait_before_request(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_ts < 0:
                self._last_ts = now
                return
            delay = self.interval + random.uniform(-self.jitter, self.jitter)
            wait = max(0.0, self._last_ts + delay - now)
            if wait:
                await asyncio.sleep(wait)
            self._last_ts = time.monotonic()


async def with_empty_retry(
    func: Callable[[], Awaitable[List]],
    *,
    waits: Tuple[float, ...] = (15.0, 30.0),
    max_empties: int = 3,
    log: logging.Logger = logger,
    ctx: str = "",
) -> List:
    """Call ``func()``; if it returns ``[]`` up to ``max_empties`` times, retry
    after ``waits``. Raises :class:`WeReadEmptyResponseError` once the limit is
    hit. ``func`` is responsible for its own pacing (it goes through the
    client, which paces internally)."""
    empties = 0
    while True:
        result = await func()
        if result:
            return result
        empties += 1
        if empties >= max_empties:
            log.error("列表连续 %d 次为空(疑似频控)，放弃: %s", empties, ctx)
            raise WeReadEmptyResponseError(ctx)
        wait = waits[min(empties - 1, len(waits) - 1)]
        log.warning("列表为空(疑似频控)第 %d 次，%.0fs 后重试: %s", empties, wait, ctx)
        await asyncio.sleep(wait)


async def with_backoff(
    func: Callable[[], Awaitable],
    *,
    waits: Tuple[float, ...] = (15.0, 30.0, 60.0),
    max_attempts: int = 3,
    log: logging.Logger = logger,
    ctx: str = "",
    transient: Tuple[type, ...] = _TRANSIENT,
):
    """Retry ``func()`` with exponential-ish backoff on transient errors.

    Re-raises the last error after ``max_attempts``."""
    attempt = 0
    while True:
        try:
            return await func()
        except transient:
            attempt += 1
            if attempt >= max_attempts:
                raise
            wait = waits[min(attempt - 1, len(waits) - 1)]
            log.warning("瞬时错误，%.0fs 后重试(%d/%d): %s", wait, attempt + 1, max_attempts, ctx)
            await asyncio.sleep(wait)
