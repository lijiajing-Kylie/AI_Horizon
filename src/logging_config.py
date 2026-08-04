"""Logging configuration shared by Horizon CLI entry points.

Horizon prints pipeline status through rich ``Console`` and live-refresh
progress bars, while third-party HTTP libraries log every request through the
stdlib ``logging`` module.  Some of those libraries run
``logging.basicConfig(level=logging.INFO)`` at import time (e.g. ``we_mp_rss``),
which raises the root level to INFO and makes ``httpx`` emit one
``INFO:httpx:HTTP Request: ...`` line per API call — interleaving with rich's
progress bar and turning a single live-updating line into dozens.

The fix is to pin the noisy third-party loggers to WARNING.  An explicitly set
level always wins over the root logger's effective level, so calling
:func:`silence_http_loggers` early in a CLI entry point keeps terminal output
clean regardless of import order.
"""

import logging

_NOISY_LOGGERS = (
    "httpx",      # OpenAI-compatible client (DeepSeek etc.) logs every request here
    "httpcore",   # httpx's async HTTP backend
    "openai",
    "urllib3",
    "requests",
    "azure.core.pipeline",
)


def silence_http_loggers() -> None:
    """Silence per-request INFO logs from third-party HTTP loggers.

    Idempotent and safe to call before or after any ``logging.basicConfig`` —
    an explicitly set level overrides the root logger's effective level.
    """
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
