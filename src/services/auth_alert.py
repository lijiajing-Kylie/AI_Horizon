"""微信读书登录态巡检 + 通用 webhook 告警。

被 ``scripts/check_weread_login.py``(cron 入口)与 ``horizon-auth-check``
console script 调用。检测方式:调用 ``horizon-wxmp status``(真实探测 token,
见 ``src/wxmp_cli.py::_cmd_status``),rc!=0 表示登录失效或未登录,按 cooldown
去重后向通用 webhook 发告警。

设计:
- 通用渠道:URL 自动适配钉钉/飞书/Slack/Discord,无需平台配置。
  URL 取 ``HORIZON_WEBHOOK_URL``(项目约定,见 .env.example),未配置时回退
  ``DINGTALK_WEBHOOK_URL``(历史遗留),保证两种部署都立即生效。
- cooldown:默认 24h,避免一天多次 cron 重复骚扰;登录恢复(rc=0)即重置。
- 发送失败不写状态:下次 cron 自动重试,保证告警最终送达。
- 刻意不依赖 ``WebhookNotifier``(它绑定 WebhookConfig + DailySummarizer,
  对纯文本告警过重);响应错误码校验语义与 ``webhook.py::_check_body_error_code``
  保持一致。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

DEFAULT_TITLE = "Horizon 微信登录失效"
ALERT_LOG_FILE = "data/logs/weread-auth-check.log"
ALERT_STATE_FILE = "data/logs/weread-alert-state.json"
DEFAULT_COOLDOWN_SECONDS = 24 * 3600  # 默认 24h,一天多次 cron 只告警一次
STATUS_TIMEOUT_SECONDS = 60.0
WEBHOOK_URL_KEYS = ("HORIZON_WEBHOOK_URL", "DINGTALK_WEBHOOK_URL")


# ── 路径与环境 ────────────────────────────────────────────────────────────────
def _repo_root() -> Path:
    """返回仓库根目录(src/services/auth_alert.py → parents[2]),与 cwd 无关。"""
    return Path(__file__).resolve().parents[2]


def load_env(env_file: str | Path) -> dict[str, str]:
    """逐行解析 KEY=VALUE 的 .env 文件,忽略注释与空行,last-wins。"""
    values: dict[str, str] = {}
    try:
        lines = Path(env_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _strip_url_escapes(url: str) -> str:
    """去掉 shell 转义残留(如 ``\\?`` ``\\&`` ``\\=``),保证 URL 可请求。"""
    return re.sub(r"\\([?&=%;])", r"\1", url)


def resolve_webhook_url(env_file: str | Path) -> str | None:
    """返回告警 webhook URL,未配置返回 None。

    优先级:``HORIZON_WEBHOOK_URL`` 优先,回退 ``DINGTALK_WEBHOOK_URL``;
    每把键先看进程环境(os.environ,手动 export 时生效),再看 ``.env`` 文件
    (cron 无导出时生效)。
    """
    file_env = load_env(env_file)
    for key in WEBHOOK_URL_KEYS:
        value = os.environ.get(key) or file_env.get(key)
        if value:
            return _strip_url_escapes(value.strip())
    return None


def redact_url(url: str) -> str:
    """打码 URL 查询参数中的密钥值,仅用于 dry-run 展示。"""
    parts = urlsplit(url)
    if not parts.query:
        return url
    masked = []
    for pair in parts.query.split("&"):
        key, _, value = pair.partition("=")
        if key.lower() in ("access_token", "token", "secret", "signature", "key"):
            masked.append(f"{key}=***")
        else:
            masked.append(f"{key}={value}")
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "&".join(masked), parts.fragment)
    )


# ── 平台适配 ──────────────────────────────────────────────────────────────────
def detect_platform(url: str) -> str:
    """按 URL host/path 特征识别渠道:dingtalk / feishu / slack / discord / generic。"""
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()
    if "dingtalk" in host:
        return "dingtalk"
    if "feishu.cn" in host or "larksuite.com" in host:
        return "feishu"
    if "slack.com" in host:
        return "slack"
    # discord 需要 webhooks 路径才判为告警渠道,避免把普通 discord 域名误判
    if host in ("discord.com", "discordapp.com") and "/api/webhooks" in path:
        return "discord"
    return "generic"


def build_alert_payload(url: str, text: str, title: str = DEFAULT_TITLE) -> dict:
    """按平台构建 webhook POST body。"""
    platform = detect_platform(url)
    if platform == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    if platform == "feishu":
        # 飞书 text 消息的 content 必须是对象,传字符串会报 code=19001
        return {"msg_type": "text", "content": {"text": text}}
    if platform == "discord":
        return {"content": text}
    # slack 与 generic 共用最宽容的裸文本约定
    return {"text": text}


def build_alert_text(repo_root: Path, now: datetime | None = None) -> str:
    """告警正文(中文,含重新扫码指引与检测时间)。"""
    now = now or datetime.now()
    return (
        "### ⚠️ Horizon 微信登录已失效\n\n"
        "collector 会一直跳过公众号抓取,且**不会自动重新登录**。\n\n"
        "请重新扫码:\n\n"
        f"```bash\ncd {repo_root} && uv run horizon-wxmp login\n```\n\n"
        f"检测时间:{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ── 响应校验与发送 ────────────────────────────────────────────────────────────
def check_response_ok(platform: str, response: httpx.Response) -> tuple[bool, str]:
    """按平台校验 webhook 响应,返回 (成功, 失败提示)。

    - 非 2xx → 失败
    - 204 / 空 body → 成功(Discord 成功即 204)
    - body 非 JSON → 成功(部分平台 200 返回纯文本)
    - 按平台查 body 错误码(语义同 ``webhook.py::_check_body_error_code``)
    """
    if not 200 <= response.status_code < 300:
        return False, f"HTTP {response.status_code}"
    text = response.text
    if response.status_code == 204 or not text.strip():
        return True, ""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return True, ""

    platform = platform.lower()
    check_all = platform in ("", "generic")
    if platform in ("feishu", "lark") or check_all:
        code = data.get("code") or data.get("StatusCode")
        if code is not None and code != 0:
            return (
                False,
                f"Feishu/Lark error (code={code}): "
                f"{data.get('msg') or data.get('StatusMessage') or ''}",
            )
    if platform == "dingtalk" or check_all:
        errcode = data.get("errcode")
        if errcode is not None and errcode != 0:
            return False, f"DingTalk error (errcode={errcode}): {data.get('errmsg') or ''}"
    if platform in ("slack", "discord") or check_all:
        if data.get("ok") is False:
            return False, f"Slack/Discord error: {data.get('error') or ''}"
    return True, ""


def send_alert(url: str, text: str, title: str = DEFAULT_TITLE) -> bool:
    """发送告警到 webhook URL。任何异常都不抛出,返回是否成功。"""
    try:
        payload = build_alert_payload(url, text, title)
        resp = httpx.post(url, json=payload, timeout=10.0)
        ok, why = check_response_ok(detect_platform(url), resp)
        if not ok:
            print(f"webhook 发送失败: {why}", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001 — 巡检脚本自身不允许崩溃
        print(f"webhook 发送异常: {exc}", file=sys.stderr)
        return False


# ── 探测命令与状态 ────────────────────────────────────────────────────────────
def status_command(bin_override: str | Path | None = None) -> list[str]:
    """返回探测命令:优先 venv 内同名 bin,退化 ``uv run``。"""
    if bin_override:
        return [str(bin_override)]
    candidate = Path(sys.executable).with_name("horizon-wxmp")
    if candidate.exists():
        return [str(candidate)]
    return ["uv", "run", "horizon-wxmp"]


def _load_state(state_file: Path) -> float | None:
    """读取上次告警时间戳;无状态/损坏返回 None。"""
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return float(data.get("last_alert_sent_at", 0) or 0)
    except (OSError, ValueError, TypeError):
        return None


def _save_state(state_file: Path) -> None:
    """原子写告警状态(tmp + os.replace,防并发 cron 交错写坏)。"""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_name(state_file.name + ".tmp")
    tmp.write_text(
        json.dumps({"last_alert_sent_at": int(time.time())}), encoding="utf-8"
    )
    os.replace(tmp, state_file)


def _clear_state(state_file: Path) -> None:
    """登录恢复后删除告警状态,下次失效立即告警(不受陈旧 cooldown 抑制)。"""
    try:
        state_file.unlink()
    except FileNotFoundError:
        pass


def _append_log(log_file: Path, message: str) -> None:
    """追加一行巡检日志。"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def check_auth(
    *,
    repo_root: Path | None = None,
    env_file: str | Path | None = None,
    log_file: str | Path | None = None,
    state_file: str | Path | None = None,
    bin_override: str | Path | None = None,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    force: bool = False,
    simulate_failure: bool = False,
    dry_run: bool = False,
) -> int:
    """探测微信读书登录态,失效时按 cooldown 发通用 webhook 告警。

    返回:
        - 0: 登录有效(同时清除告警状态)
        - 1: 登录失效/未登录(已告警、被 cooldown 抑制、未配置 URL 或 dry-run)
        - 2: 探测失败(status 超时)
    """
    root = Path(repo_root) if repo_root else _repo_root()
    env = Path(env_file) if env_file else root / ".env"
    log = Path(log_file) if log_file else root / ALERT_LOG_FILE
    state = Path(state_file) if state_file else root / ALERT_STATE_FILE

    if simulate_failure:
        rc, output = 1, "[simulated] login invalid"
    else:
        try:
            proc = subprocess.run(
                status_command(bin_override) + ["status"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=STATUS_TIMEOUT_SECONDS,
            )
            rc = proc.returncode
            output = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            _append_log(log, f"status 超时(>{STATUS_TIMEOUT_SECONDS:.0f}s)")
            return 2

    _append_log(log, f"rc={rc}\n{output}")

    if rc == 0:
        _clear_state(state)
        return 0

    url = resolve_webhook_url(env)
    if not url:
        _append_log(log, "未配置 HORIZON_WEBHOOK_URL/DINGTALK_WEBHOOK_URL,跳过告警")
        print(
            "未配置 HORIZON_WEBHOOK_URL/DINGTALK_WEBHOOK_URL,跳过告警",
            file=sys.stderr,
        )
        return 1

    platform = detect_platform(url)
    if dry_run:
        print(f"[dry-run] 登录失效(rc={rc}),将发送告警:")
        print(f"  url: {redact_url(url)}")
        print(f"  platform: {platform}")
        print(
            "  payload: "
            + json.dumps(
                build_alert_payload(url, build_alert_text(root)), ensure_ascii=False
            )
        )
        return 1

    last = _load_state(state)
    if last is not None and not force and (time.time() - last) < cooldown_seconds:
        remain = cooldown_seconds - (time.time() - last)
        _append_log(log, f"cooldown 内({remain:.0f}s 后解除),跳过重复告警")
        return 1

    if send_alert(url, build_alert_text(root)):
        _save_state(state)
        _append_log(log, f"已发送告警({platform})")
    else:
        _append_log(log, "告警发送失败,下次巡检重试")
    return 1


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 入口(console script: ``horizon-auth-check``)。"""
    root = _repo_root()
    parser = argparse.ArgumentParser(
        prog="horizon-auth-check",
        description="微信读书登录态巡检:失效时按 cooldown 发通用 webhook 告警",
    )
    parser.add_argument("--repo", default=str(root), help="项目根目录(默认自动推导)")
    parser.add_argument("--env-file", default=str(root / ".env"), help=".env 文件路径")
    parser.add_argument("--log-file", default=str(root / ALERT_LOG_FILE), help="巡检日志路径")
    parser.add_argument(
        "--state-file", default=str(root / ALERT_STATE_FILE), help="告警去重状态路径"
    )
    parser.add_argument(
        "--bin", default=None, help="探测命令覆盖(默认 venv 内 horizon-wxmp)"
    )
    parser.add_argument(
        "--cooldown-hours",
        type=float,
        default=DEFAULT_COOLDOWN_SECONDS / 3600,
        help="两次告警最小间隔小时(默认 24)",
    )
    parser.add_argument(
        "--force", action="store_true", help="忽略 cooldown 强制告警"
    )
    parser.add_argument(
        "--simulate-failure",
        action="store_true",
        help="不跑真实探测,强制走失效分支(测试/演练)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印 payload,不发送不写状态"
    )
    args = parser.parse_args(argv)
    return check_auth(
        repo_root=Path(args.repo),
        env_file=args.env_file,
        log_file=args.log_file,
        state_file=args.state_file,
        bin_override=args.bin,
        cooldown_seconds=args.cooldown_hours * 3600,
        force=args.force,
        simulate_failure=args.simulate_failure,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
