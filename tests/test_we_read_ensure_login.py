"""Tests for ``we_read.ensure_login`` (interactive QR-prompt gating)."""

from __future__ import annotations

import asyncio
import importlib

# 必须从 sys.modules 拿模块对象：`src.we_read.__init__` 里 `from
# .ensure_login import ensure_login` 会把包的 ensure_login 属性遮蔽成函数，
# 字符串路径 / `import a.b as x` 都会解析到函数而非模块。
ensure_login_module = importlib.import_module("src.we_read.ensure_login")
from src.we_read.ensure_login import ensure_login, is_interactive
from src.we_read.errors import WeReadLoginTimeoutError


class _FakeStore:
    def __init__(self, present: bool) -> None:
        self.present = present

    def is_present(self) -> bool:
        return self.present


class _FakeClient:
    def __init__(self, present: bool = True) -> None:
        self.store = _FakeStore(present)


def test_interactive_true_when_tty(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    assert is_interactive() is True


def test_interactive_false_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert is_interactive() is False


def test_interactive_false_when_not_tty(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    assert is_interactive() is False


def test_token_present_returns_true_without_login() -> None:
    """Stored token → assumed valid; no QR flow runs."""
    assert asyncio.run(ensure_login(_FakeClient(present=True))) is True


def test_non_interactive_without_token_returns_false(monkeypatch) -> None:
    """Missing token + non-interactive → False without ever prompting."""
    flow_calls = {"n": 0}

    class _SpyFlow:
        def __init__(self, client) -> None:
            self.client = client

        async def run(self, **kwargs):  # pragma: no cover - must not be called
            flow_calls["n"] += 1
            return "session"

    monkeypatch.setattr(ensure_login_module, "WeReadLoginFlow", _SpyFlow)
    monkeypatch.setattr(ensure_login_module, "is_interactive", lambda: False)
    assert asyncio.run(ensure_login(_FakeClient(present=False))) is False
    assert flow_calls["n"] == 0


def test_interactive_without_token_runs_flow(monkeypatch) -> None:
    class _FakeFlow:
        def __init__(self, client) -> None:
            self.client = client

        async def run(self, **kwargs):
            return "session"

    monkeypatch.setattr(ensure_login_module, "WeReadLoginFlow", _FakeFlow)
    monkeypatch.setattr(ensure_login_module, "is_interactive", lambda: True)
    assert asyncio.run(ensure_login(_FakeClient(present=False))) is True


def test_force_relogs_even_with_stored_token(monkeypatch) -> None:
    """force=True (post-401) re-runs the QR flow despite a stored token."""
    flow_calls = {"n": 0}

    class _FakeFlow:
        def __init__(self, client) -> None:
            self.client = client

        async def run(self, **kwargs):
            flow_calls["n"] += 1
            return "session"

    monkeypatch.setattr(ensure_login_module, "WeReadLoginFlow", _FakeFlow)
    monkeypatch.setattr(ensure_login_module, "is_interactive", lambda: True)
    assert asyncio.run(ensure_login(_FakeClient(present=True), force=True)) is True
    assert flow_calls["n"] == 1


def test_flow_failure_returns_false(monkeypatch) -> None:
    class _FakeFlow:
        def __init__(self, client) -> None:
            self.client = client

        async def run(self, **kwargs):
            raise WeReadLoginTimeoutError("扫码超时")

    monkeypatch.setattr(ensure_login_module, "WeReadLoginFlow", _FakeFlow)
    monkeypatch.setattr(ensure_login_module, "is_interactive", lambda: True)
    assert asyncio.run(ensure_login(_FakeClient(present=False))) is False
