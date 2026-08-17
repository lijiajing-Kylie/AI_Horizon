"""Ensure the WeRead channel is logged in before scraping.

Interactive runs (local terminal, not CI) that hit a missing or invalid token
pop the QR login window (:class:`WeReadLoginFlow`) and block until the user
scans — same UX as ``horizon-wxmp login``. Non-interactive environments (CI,
no terminal stdin) never prompt: :func:`ensure_login` returns ``False`` there
so callers fail-open and skip the WeChat source instead of hanging the run.
"""

from __future__ import annotations

import os
import sys
from typing import Callable

from .client import WeReadClient
from .errors import WeReadError
from .login import WeReadLoginFlow


def is_interactive() -> bool:
    """True when a QR prompt is safe to block on (local terminal, not CI)."""
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        return sys.stdin.isatty()
    except Exception:  # pragma: no cover - best-effort tty probe
        return False


async def ensure_login(
    client: WeReadClient,
    *,
    print_fn: Callable[[str], None] = print,
    timeout: float = 120.0,
    force: bool = False,
) -> bool:
    """Ensure a usable WeRead token; pop the QR window when missing/invalid.

    - ``force=False`` and a stored token → ``True`` (assumed valid; a real 401
      later triggers ``force=True`` re-login).
    - Non-interactive environment → ``False`` (never prompt).
    - Otherwise run the QR login flow; ``True`` on scan, ``False`` on failure.
    """
    if not force and client.store.is_present():
        return True
    if not is_interactive():
        return False
    flow = WeReadLoginFlow(client)
    try:
        await flow.run(timeout=timeout, print_fn=print_fn)
        return True
    except WeReadError as exc:
        print_fn(f"微信读书登录失败: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - fail-open on unexpected errors
        print_fn(f"微信读书登录异常: {exc}")
        return False
