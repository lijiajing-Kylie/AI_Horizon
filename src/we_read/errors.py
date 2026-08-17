"""Error hierarchy for the WeRead channel.

Distinguishes API error classes so callers can react appropriately:
``401`` → token invalid (auth), ``400`` → bad request (invalid mp_id / page),
``429`` → explicit rate limit, ``5xx`` → upstream server error,
connectivity/timeout → network error.

An empty JSON array from the articles endpoint is NOT an exception — it is
handled by :func:`we_read.retry.with_empty_retry` (the forwarding service
rate-limits silently with ``[]``).
"""

from __future__ import annotations


class WeReadError(Exception):
    """Base class for all WeRead channel errors."""


class WeReadAuthError(WeReadError):
    """401 — token invalid/expired; a fresh QR login is required."""


class WeReadError400(WeReadError):
    """400 — bad request (invalid mp_id, page out of range, …)."""


class WeReadRateLimitError(WeReadError):
    """429 — explicit rate limiting from the forwarding service."""


class WeReadEmptyResponseError(WeReadError):
    """Articles endpoint kept returning ``[]`` after retries — suspected rate limit."""


class WeReadServerError(WeReadError):
    """5xx — upstream forwarding-service error."""


class WeReadNetworkError(WeReadError):
    """Connection or timeout error."""


class WeReadLoginTimeoutError(WeReadError):
    """QR login poll timed out before the user scanned."""
