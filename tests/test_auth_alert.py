"""Tests for the WeRead auth alert (src/services/auth_alert.py).

覆盖:平台检测、各平台 payload 结构、webhook URL 解析与回退、响应错误码
校验、cooldown 去重与重置、dry-run / simulate_failure / 超时分支。
不依赖真实登录态与网络 —— subprocess 与 httpx.post 全部 mock。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import src.services.auth_alert as auth_alert
from src.services.auth_alert import (
    build_alert_payload,
    check_auth,
    check_response_ok,
    detect_platform,
    resolve_webhook_url,
    send_alert,
    status_command,
)

DINGTALK_URL = "https://oapi.dingtalk.com/robot/send?access_token=abc"


@pytest.fixture(autouse=True)
def _clean_webhook_env(monkeypatch) -> None:
    """全量收集时 ``tests/test_api.py`` 的 import 链会在模块级 load_dotenv(),
    把本机 .env 的 webhook URL 注入 os.environ —— 本模块所有测试都假定
    这两个 key 不在进程环境里(resolve_webhook_url 的环境优先级)。"""
    monkeypatch.delenv("HORIZON_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)


def _write_env(path: Path, **values: str) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def _ok_response(**kwargs) -> httpx.Response:
    return httpx.Response(200, json={"errcode": 0, "code": 0, "ok": True}, **kwargs)


# ── 平台检测 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://oapi.dingtalk.com/robot/send?access_token=x", "dingtalk"),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/x", "feishu"),
        ("https://open.larksuite.com/open-apis/bot/v2/hook/x", "feishu"),
        ("https://hooks.slack.com/services/T0000/B0000/xxx", "slack"),
        ("https://discord.com/api/webhooks/123/abc", "discord"),
        ("https://discordapp.com/api/webhooks/123/abc", "discord"),
        ("https://discord.com/not-a-webhook", "generic"),
        ("https://example.com/hook", "generic"),
    ],
)
def test_detect_platform(url: str, expected: str) -> None:
    assert detect_platform(url) == expected


# ── payload 构建 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url, expected",
    [
        (
            DINGTALK_URL,
            {"msgtype": "markdown", "markdown": {"title": "t", "text": "m"}},
        ),
        (
            "https://open.feishu.cn/open-apis/bot/v2/hook/x",
            {"msg_type": "text", "content": {"text": "m"}},
        ),
        ("https://hooks.slack.com/services/T/B/X", {"text": "m"}),
        ("https://discord.com/api/webhooks/1/2", {"content": "m"}),
        ("https://example.com/hook", {"text": "m"}),
    ],
)
def test_build_alert_payload(url: str, expected: dict) -> None:
    assert build_alert_payload(url, "m", title="t") == expected


# ── URL 解析与回退 ────────────────────────────────────────────────────────────
def test_resolve_url_prefers_horizon_key(tmp_path, monkeypatch) -> None:
    env = _write_env(
        tmp_path / ".env",
        HORIZON_WEBHOOK_URL="https://hooks.slack.com/services/A",
        DINGTALK_WEBHOOK_URL=DINGTALK_URL,
    )
    monkeypatch.delenv("HORIZON_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    assert resolve_webhook_url(env) == "https://hooks.slack.com/services/A"


def test_resolve_url_falls_back_to_dingtalk(tmp_path, monkeypatch) -> None:
    env = _write_env(tmp_path / ".env", DINGTALK_WEBHOOK_URL=DINGTALK_URL)
    monkeypatch.delenv("HORIZON_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    assert resolve_webhook_url(env) == DINGTALK_URL


def test_resolve_url_env_overrides_file(tmp_path, monkeypatch) -> None:
    env = _write_env(tmp_path / ".env", HORIZON_WEBHOOK_URL="https://file.example")
    monkeypatch.setenv("HORIZON_WEBHOOK_URL", "https://env.example")
    assert resolve_webhook_url(env) == "https://env.example"


def test_resolve_url_none_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HORIZON_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    assert resolve_webhook_url(tmp_path / ".env") is None


def test_resolve_url_strips_shell_escapes(tmp_path, monkeypatch) -> None:
    env = _write_env(
        tmp_path / ".env",
        DINGTALK_WEBHOOK_URL="https://x/robot/send\\?access_token=a\\&b=1",
    )
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    assert resolve_webhook_url(env) == "https://x/robot/send?access_token=a&b=1"


# ── 响应校验 ──────────────────────────────────────────────────────────────────
def test_check_response_ok_dingtalk() -> None:
    ok, why = check_response_ok("dingtalk", httpx.Response(200, json={"errcode": 0}))
    assert ok and why == ""
    ok, why = check_response_ok(
        "dingtalk", httpx.Response(200, json={"errcode": 30000, "errmsg": "bad"})
    )
    assert not ok and "errcode=30000" in why and "bad" in why


def test_check_response_ok_feishu() -> None:
    assert check_response_ok("feishu", httpx.Response(200, json={"code": 0}))[0]
    ok, why = check_response_ok(
        "feishu", httpx.Response(200, json={"StatusCode": 19001, "msg": "x"})
    )
    assert not ok and "19001" in why


def test_check_response_ok_slack() -> None:
    assert check_response_ok("slack", httpx.Response(200, json={"ok": True}))[0]
    ok, why = check_response_ok(
        "slack", httpx.Response(200, json={"ok": False, "error": "invalid_payload"})
    )
    assert not ok and "invalid_payload" in why


def test_check_response_ok_discord_204_empty_body() -> None:
    ok, why = check_response_ok("discord", httpx.Response(204, text=""))
    assert ok and why == ""


def test_check_response_ok_generic_checks_all() -> None:
    assert check_response_ok("generic", httpx.Response(200, json={"errcode": 0}))[0]
    assert not check_response_ok("generic", httpx.Response(200, json={"errcode": 400}))[0]


def test_check_response_ok_non_json_body_and_http_error() -> None:
    assert check_response_ok("slack", httpx.Response(200, text="ok"))[0]
    ok, why = check_response_ok("slack", httpx.Response(500))
    assert not ok and "HTTP 500" in why


# ── 发送 ──────────────────────────────────────────────────────────────────────
def test_send_alert_success(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return httpx.Response(200, json={"errcode": 0})

    monkeypatch.setattr(auth_alert.httpx, "post", fake_post)
    assert send_alert(DINGTALK_URL, "msg") is True
    assert captured["payload"]["msgtype"] == "markdown"


def test_send_alert_exception_returns_false(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(auth_alert.httpx, "post", fake_post)
    assert send_alert(DINGTALK_URL, "msg") is False


def test_send_alert_platform_error_body_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_alert.httpx,
        "post",
        lambda *a, **k: httpx.Response(200, json={"errcode": 310000}),
    )
    assert send_alert(DINGTALK_URL, "msg") is False


# ── 探测命令 ──────────────────────────────────────────────────────────────────
def test_status_command_prefers_venv_bin(tmp_path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "horizon-wxmp").touch()
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    assert status_command() == [str(bin_dir / "horizon-wxmp")]


def test_status_command_falls_back_to_uv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    assert status_command() == ["uv", "run", "horizon-wxmp"]


def test_status_command_respects_override() -> None:
    assert status_command(bin_override="custom-check") == ["custom-check"]


# ── check_auth 主流程 ────────────────────────────────────────────────────────
def _run_check(tmp_path, monkeypatch, subprocess_rc=1, **kwargs):
    sent = []
    monkeypatch.setattr(auth_alert, "send_alert", lambda *a, **k: sent.append(True) or True)
    monkeypatch.setattr(
        auth_alert.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, subprocess_rc, stdout="out", stderr=""),
    )
    rc = check_auth(
        repo_root=tmp_path,
        env_file=_write_env(tmp_path / ".env", DINGTALK_WEBHOOK_URL=DINGTALK_URL),
        log_file=tmp_path / "log.txt",
        state_file=tmp_path / "state.json",
        **kwargs,
    )
    return rc, sent


def test_check_auth_valid_resets_state(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"last_alert_sent_at": 1}', encoding="utf-8")
    rc, sent = _run_check(tmp_path, monkeypatch, subprocess_rc=0)
    assert rc == 0 and not sent and not state.exists()


def test_check_auth_sends_on_failure_then_cooldown_skips(tmp_path, monkeypatch) -> None:
    rc1, sent1 = _run_check(tmp_path, monkeypatch, subprocess_rc=1)
    assert rc1 == 1 and len(sent1) == 1  # 首调发送

    rc2, sent2 = _run_check(tmp_path, monkeypatch, subprocess_rc=1)
    assert rc2 == 1 and len(sent2) == 0  # cooldown 内跳过


def test_check_auth_force_bypasses_cooldown(tmp_path, monkeypatch) -> None:
    _run_check(tmp_path, monkeypatch, subprocess_rc=1)
    _, sent = _run_check(tmp_path, monkeypatch, subprocess_rc=1, force=True)
    assert len(sent) == 1


def test_check_auth_zero_cooldown_sends_every_time(tmp_path, monkeypatch) -> None:
    _run_check(tmp_path, monkeypatch, subprocess_rc=1, cooldown_seconds=0)
    _, sent = _run_check(tmp_path, monkeypatch, subprocess_rc=1, cooldown_seconds=0)
    assert len(sent) == 1


def test_check_auth_dry_run_does_not_send(tmp_path, monkeypatch, capsys) -> None:
    def _raise(*a, **k):
        raise AssertionError("dry-run 不应发送")

    monkeypatch.setattr(auth_alert, "send_alert", _raise)
    monkeypatch.setattr(
        auth_alert.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=""),
    )
    rc = check_auth(
        repo_root=tmp_path,
        env_file=_write_env(tmp_path / ".env", DINGTALK_WEBHOOK_URL=DINGTALK_URL),
        log_file=tmp_path / "log.txt",
        state_file=tmp_path / "state.json",
        dry_run=True,
    )
    assert rc == 1
    assert "[dry-run]" in capsys.readouterr().out


def test_check_auth_simulate_failure_skips_subprocess(tmp_path, monkeypatch) -> None:
    def _raise(*a, **k):
        raise AssertionError("simulate_failure 不应调用 subprocess")

    monkeypatch.setattr(auth_alert.subprocess, "run", _raise)
    monkeypatch.setattr(auth_alert, "send_alert", lambda *a, **k: True)
    rc = check_auth(
        repo_root=tmp_path,
        env_file=_write_env(tmp_path / ".env", DINGTALK_WEBHOOK_URL=DINGTALK_URL),
        log_file=tmp_path / "log.txt",
        state_file=tmp_path / "state.json",
        simulate_failure=True,
    )
    assert rc == 1


def test_check_auth_no_url_skips_alert(tmp_path, monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(auth_alert, "send_alert", lambda *a, **k: sent.append(True) or True)
    monkeypatch.setattr(
        auth_alert.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=""),
    )
    rc = check_auth(
        repo_root=tmp_path,
        env_file=tmp_path / ".env",  # 不存在 → resolve 返回 None
        log_file=tmp_path / "log.txt",
        state_file=tmp_path / "state.json",
    )
    assert rc == 1 and not sent


def test_check_auth_timeout_returns_2(tmp_path, monkeypatch) -> None:
    def _raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired("cmd", 60)

    monkeypatch.setattr(auth_alert.subprocess, "run", _raise_timeout)
    rc = check_auth(
        repo_root=tmp_path,
        env_file=tmp_path / ".env",
        log_file=tmp_path / "log.txt",
        state_file=tmp_path / "state.json",
    )
    assert rc == 2
