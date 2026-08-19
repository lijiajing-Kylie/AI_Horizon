# Horizon 阿里云部署方案（qianwenai-deploy skill 执行手册）

> **本文档是自包含执行手册**，供一个新窗口的 Claude Code（或人）照着直接实施，无需重新设计。
> 配套 skill：`.agents/skills/qianwenai-deploy/`（执行前先读其 `SKILL.md` 与 `reference/rules/rule_interaction.md`、`reference/rules/rule_error_handling.md`）。
> 本文档只定义"针对 Horizon 的参数与定制层"；通用 13 步流程的语义以 skill 文档为准。
>
> 状态：**待实施**（2026-08-18 设计定稿）。与 `horizon-vps-deployment-plan-v2.md` 的关系：v2 是手工 VPS 方案（未实施），本文档取代其落地路径，复用其容器/脚本设计。

---

## 0. 已锁定决策（执行时不要再问，除非标注 ⚠️ASK）

| 决策 | 结论 |
|---|---|
| 云平台 | 阿里云**国内站**（aliyun.com），qianwenai-deploy skill（ROS 单机编排：VPC + SG + ECS + EIP） |
| 地域 | **cn-guangzhou** |
| 实例规格 | `ecs.e-c1m1.large`（2C2G，≈¥0.10/h，最便宜档；步骤 9 询价后由用户最终确认） |
| 数据 | **带数据迁移**：`horizon.db`（~414MB）+ `data/auth/`（微信登录态）+ `data/config.py` + `data/reports_pdfs/` + `data/summaries/` + `.env` |
| 数据库 | SQLite 留 ECS 本地盘（`/var/lib/horizon/data`），**不用 RDS** |
| 境外源出口 | **mihomo 代理 sidecar**（用户的商业订阅 → 本地 `http://proxy:7890`），仅 `pipeline` 服务走代理 |
| 前端 | React SPA + FastAPI 一起上 ECS，**公网开放**（nginx `static+app`），替代 GitHub Pages 静态站；用户已知情接受 API 无鉴权 |
| 更新方式 | skill 热更新（`update_app.sh`，IP 不变） |
| 服务器端 gh-pages 推送 | **取消**；GitHub Actions `daily-summary.yml` 保留为 VPS 故障时的兜底 |

**架构选择及理由**（与 skill 能力的映射，改了会破坏流程，勿擅动）：

| 决策点 | 选择 | 理由 |
|---|---|---|
| app_type / app_mode | `docker` / `docker-compose` | ECS 系统 Python 是 3.9（项目要求 ≥3.11）；skill 的 compose 模式热更新原生支持 |
| nginx_mode | `static+app` | SPA 作静态产物；`/api/` 反代 `127.0.0.1:8080`；前端 `BASE_URL` 默认同源（`frontend/src/api/client.ts:22`），构建时不设 `VITE_STATIC_MODE` 即 API 模式 |
| app_port | `8080` | skill 约定；compose 把 API 的 8000 映射到宿主机 `127.0.0.1:8080` |
| 数据目录 | `/var/lib/horizon/data` | **必须在 `/opt/qianwenai` 之外**——热更新会原子替换应用目录 |
| compose 文件名 | 必须是 `docker-compose.yml` 且在产物根目录 | `update_app.sh:104` 写死 |
| 探活 | nginx `/healthz`（skill 模板自带）；热更新健康检查 `curl -sf localhost:8080/` | FastAPI 的 `/` 是 Jinja2 SSR 页返回 200，天然满足 |

**代理分流原则（重要）**：只有 `pipeline` 服务配代理环境变量；`collector`（只打 weread 转发，国内）与 `api`（只服务本地 + 国内图床代理）**不走代理**。微信/DeepSeek/阿里系流量绝不经过境外节点，避免触发微信风控。分流靠客户端 `NO_PROXY`，mihomo 配置保持最小（全部流量转发给订阅节点）。

---

## 1. 架构总览

```
用户浏览器
   │ http://<EIP>/
   ▼
nginx(ECS,80)── / → /var/www/static(React SPA,静态产物)
   │            ── /api/ → 127.0.0.1:8080 ──► api 容器(uvicorn:8000)
   │            ── /healthz(探活)
   │
docker compose(/opt/qianwenai)
   ├─ proxy      mihomo,商业订阅 → :7890,url-test 自动切节点,restart=unless-stopped
   ├─ collector  horizon-wxmp-collector 常驻,直连国内,restart=unless-stopped
   ├─ api        uvicorn :8000,restart=unless-stopped
   └─ pipeline   profile=pipeline 瞬态(cron `run --rm -T`),唯一走代理的服务
                   每日:news → reports → papers
宿主机 cron(/etc/cron.d/horizon):每日管道 / 登录巡检×3 / 代理巡检×4h /  nightly 备份 / @reboot compose up
持久状态:/var/lib/horizon/{data,.env}    备份:/var/backups/horizon(留 14 份,chmod 700)
```

---

## 2. Phase A — 仓库文件落地（先做，并 commit + push）

按以下完整内容新建/替换 7 个文件。**不要**改 `src/api/server.py`、不要改前端代码。

### 2.1 `Dockerfile.vps`（新建）

相对现有 `Dockerfile` 的关键差异：去掉 `COPY data ./data`（运行时状态走 volume，绝不能把本机登录态/密钥烤进镜像）；uv 用 pip 从阿里镜像装（ECS 拉 ghcr.io 不稳）；apt/pip 全部走阿里镜像。

```dockerfile
FROM python:3.11-slim

# Debian 源换阿里镜像(ECS 构建加速;本地构建无害)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv 不用 ghcr.io 镜像层(国内拉取不稳),pip 阿里镜像安装
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# 不装 Playwright:Twitter 源服务器上关闭;browser 类 RSS 源自动降级 HTTP;
# 报告 PDF 浏览器解析 fail-open(只给文章链接)。

COPY src ./src
COPY scripts ./scripts
COPY deploy ./deploy
# 注意:不 COPY data/ —— 运行时数据一律由 volume 挂载。

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uv", "run"]
CMD ["horizon", "--help"]
```

### 2.2 `docker-compose.yml`（替换现有文件）

> 现有根 `docker-compose.yml` 有设计缺陷（`restart: unless-stopped` + 跑完即退的命令 = 反复重启），v2 方案已判定废弃，直接整体替换。本地开发不依赖它（都是 `uv run` 直跑）。

```yaml
# Horizon 服务器编排(阿里云 ECS,/opt/qianwenai)。
# 数据与密钥在 /var/lib/horizon/(热更新原子替换 /opt/qianwenai 不影响)。
# 常驻:proxy / collector / api;瞬态:pipeline(cron 用 `docker compose run --rm -T pipeline ...`)。

services:
  proxy:
    image: metacubex/mihomo:Meta
    container_name: horizon-proxy
    restart: unless-stopped
    env_file: /var/lib/horizon/.env
    volumes:
      - ./deploy/mihomo/config.template.yaml:/etc/mihomo/config.template.yaml:ro
    # 启动时用 sed 把订阅 URL 渲进配置(转义 & | \ 三种 sed 特殊字符)
    entrypoint: ["sh", "-c", 'mkdir -p /root/.config/mihomo && esc=$$(printf "%s" "$$PROXY_SUBSCRIPTION_URL" | sed "s/[&|\\]/\\\\&/g") && sed "s|__PROXY_SUBSCRIPTION_URL__|$${esc}|g" /etc/mihomo/config.template.yaml > /root/.config/mihomo/config.yaml && exec mihomo -d /root/.config/mihomo']
    healthcheck:
      test: ["CMD-SHELL", "https_proxy=http://127.0.0.1:7890 wget -q -O /dev/null --timeout=10 https://www.gstatic.com/generate_204"]
      interval: 60s
      timeout: 15s
      retries: 3
      start_period: 30s

  api:
    build:
      context: .
      dockerfile: Dockerfile.vps
    image: horizon:local
    container_name: horizon-api
    restart: unless-stopped
    # 绕过 src/api/server.py 硬编码的 reload=True,直接跑 uvicorn(生产模式)
    entrypoint: ["uv", "run", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "127.0.0.1:8080:8000"   # 只绑回环,对外只经 nginx
    volumes:
      - /var/lib/horizon/data:/app/data
    env_file: /var/lib/horizon/.env
    environment:
      - TZ=Asia/Shanghai

  collector:
    image: horizon:local
    container_name: horizon-collector
    restart: unless-stopped
    entrypoint: ["uv", "run", "horizon-wxmp-collector"]
    volumes:
      - /var/lib/horizon/data:/app/data
    env_file: /var/lib/horizon/.env
    environment:
      - TZ=Asia/Shanghai
    # 不带子命令 = 常驻循环。手动补抓:
    #   docker compose run --rm -T --entrypoint "uv" collector run horizon-wxmp-collector once

  pipeline:
    image: horizon:local
    container_name: horizon-pipeline
    profiles: ["pipeline"]        # `up -d` 不拉起;仅 cron/手动 `run --rm -T` 瞬态
    restart: "no"
    depends_on:
      proxy:
        condition: service_healthy
    volumes:
      - /var/lib/horizon/data:/app/data
    env_file: /var/lib/horizon/.env
    environment:
      - TZ=Asia/Shanghai
      # 唯一走代理的服务:境外源(HN/Reddit/RSS/arXiv/OpenAlex/DuckDuckGo)经 mihomo
      - HTTPS_PROXY=http://proxy:7890
      - HTTP_PROXY=http://proxy:7890
      - https_proxy=http://proxy:7890
      - http_proxy=http://proxy:7890
      - PROXY=http://proxy:7890
      # 国内直连白名单(微信/DeepSeek/阿里系/报告源绝不走境外节点)
      - NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,mp.weixin.qq.com,mmbiz.qpic.cn,weread.111965.xyz,api.deepseek.com,dashscope.aliyuncs.com,aliyuncs.com,aliyun.com,volces.com,minimax.chat,fxbaogao.com
      - no_proxy=localhost,127.0.0.1,10.0.0.0/8,mp.weixin.qq.com,mmbiz.qpic.cn,weread.111965.xyz,api.deepseek.com,dashscope.aliyuncs.com,aliyuncs.com,aliyun.com,volces.com,minimax.chat,fxbaogao.com
```

> httpx 客户端全部 `trust_env=True`（已全仓验证），代理 env 自动生效，无需改代码；Playwright 路径显式读 `PROXY`（`src/scrapers/twitter_playwright.py:32` 等）也已覆盖。

### 2.3 `deploy/mihomo/config.template.yaml`（新建）

```yaml
# mihomo(Clash.Meta)最小配置:全部流量转发给订阅节点组。
# 分流在客户端 NO_PROXY 完成(见 docker-compose.yml pipeline 服务),此处刻意不做规则。
mixed-port: 7890
allow-lan: true
bind-address: "*"
mode: rule
log-level: warning
external-controller: 127.0.0.1:9090   # 排障用:docker exec 进容器后可查/切节点

proxy-providers:
  airport:
    type: http
    url: "__PROXY_SUBSCRIPTION_URL__"   # 启动时由 entrypoint 从 env 渲染
    interval: 3600                      # 每小时刷新订阅(节点变更自动跟进)
    path: ./providers/airport.yaml
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300

proxy-groups:
  - name: AUTO
    type: url-test                      # 单节点失效自动切换到可用节点
    use: [airport]
    url: https://www.gstatic.com/generate_204
    interval: 300
    tolerance: 50

rules:
  - MATCH,AUTO
```

### 2.4 `scripts/run_all_pipelines.sh`（新建）

```bash
#!/usr/bin/env bash
# 每日全管道:news → reports → papers。由宿主机 cron 经
# `docker compose run --rm -T pipeline bash scripts/run_all_pipelines.sh` 拉起。
# 日志:/app/data/pipeline.log;任一管道 FAIL 经 webhook 告警(复用 src.services.auth_alert)。
set -u
cd /app

RESULTS=()
run() {
  local name="$1"; shift
  echo "--- [$name] ---"
  if "$@" >> /app/data/pipeline.log 2>&1; then RESULTS+=("$name:OK")
  else RESULTS+=("$name:FAIL"); fi
}

run "news"    uv run horizon --hours 24
run "reports" uv run horizon-reports
run "papers"  uv run horizon-papers

echo "[$(date '+%F %T')] ${RESULTS[*]}" >> /app/data/pipeline.log

# 有 FAIL 且有 webhook 配置时告警(auth_alert.send_alert 不抛异常)
if printf '%s\n' "${RESULTS[@]}" | grep -q FAIL; then
  uv run python - "${RESULTS[*]}" <<'PY' || true
import sys
from src.services.auth_alert import resolve_webhook_url, send_alert
url = resolve_webhook_url("/app/.env")
if url:
    send_alert(url, f"### ⚠️ Horizon 每日管道有失败\n\n`{sys.argv[1]}`\n\n见服务器 /var/lib/horizon/data/pipeline.log", "Horizon 管道告警")
PY
fi
```

> 与 v2 §6.3 的差异：删掉 `export`（导出静态 JSON）与 gh-pages push 两段——前端已自托管为 API 模式。

### 2.5 `scripts/backup.sh`（新建，宿主机执行）

```bash
#!/usr/bin/env bash
# 每日备份:SQLite 在线备份(WAL 模式必须 .backup,裸 cp 可能拷到不一致快照)
# + 登录态/PDF/配置打包。保留最近 14 份。宿主机 cron 执行,需 sqlite3(部署脚本已装)。
set -euo pipefail
DATA_DIR="${DATA_DIR:-/var/lib/horizon/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/horizon}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"   # 库含微信 token,禁止世界可读
ts="$(date +%F_%H%M)"

sqlite3 "$DATA_DIR/horizon.db" ".backup '$BACKUP_DIR/horizon-$ts.db'"
tar czf "$BACKUP_DIR/assets-$ts.tgz" -C "$DATA_DIR" auth reports_pdfs config.py 2>/dev/null || true

ls -1t "$BACKUP_DIR"/horizon-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f
ls -1t "$BACKUP_DIR"/assets-*.tgz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[$(date '+%F %T')] backup OK" >> "$DATA_DIR/backup.log"
```

### 2.6 `scripts/stage_deploy.sh`（新建）

`upload_artifacts.py` 的 tar 排除清单是写死的（只有 node_modules/.git/__pycache__ 等），**不含 `data/`**——直接对仓库根打包会把 414MB 库、2.7GB 本地备份、`.env` 密钥全部打进产物。必须用白名单 staging：

```bash
#!/usr/bin/env bash
# 组装上传用 staging 目录(白名单制):只含运行/构建必需文件。
# 用法: bash scripts/stage_deploy.sh [目标目录]   默认 /tmp/horizon-deploy-staging
set -euo pipefail
STAGE="${1:-/tmp/horizon-deploy-staging}"
ROOT="$(git rev-parse --show-toplevel)"

rm -rf "$STAGE"
mkdir -p "$STAGE"
cd "$ROOT"
rsync -a pyproject.toml uv.lock README.md Dockerfile.vps docker-compose.yml "$STAGE/"
rsync -a --exclude '__pycache__' --exclude '.pytest_cache' src scripts deploy "$STAGE/"
echo "staging ready: $STAGE"
du -sh "$STAGE"
```

### 2.7 `scripts/check_proxy.py`（新建）

代理巡检，cron 每 6h 一次（在 pipeline 容器内跑，`http://proxy:7890` 可达）。模式完全仿 `scripts/check_weread_login.py`，复用 `src/services/auth_alert.py` 的 webhook 发送：

```python
#!/usr/bin/env python3
"""代理巡检:经 mihomo(http://proxy:7890)探测境外 204,失败按 24h cooldown 发 webhook。

复用 src/services/auth_alert 的平台适配/发送/错误码校验;cooldown 状态文件
data/logs/proxy-alert-state.json,日志 data/logs/proxy-check.log。
在 pipeline 容器内运行:cron `docker compose run --rm -T pipeline uv run python scripts/check_proxy.py`。
返回:0=代理正常;1=代理异常(已告警/被抑制/未配置 webhook)。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.services.auth_alert import resolve_webhook_url, send_alert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "data/logs/proxy-check.log"
STATE_FILE = ROOT / "data/logs/proxy-alert-state.json"
COOLDOWN_SECONDS = 24 * 3600
PROBE_URL = os.environ.get("PROXY_CHECK_URL", "https://www.gstatic.com/generate_204")
PROXY_URL = os.environ.get("PROXY_CHECK_PROXY", "http://proxy:7890")


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def _last_alert() -> float | None:
    try:
        return float(json.loads(STATE_FILE.read_text())["last_alert_sent_at"])
    except Exception:
        return None


def _save_alert() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps({"last_alert_sent_at": int(time.time())}))
    os.replace(tmp, STATE_FILE)


def main() -> int:
    try:
        resp = httpx.get(PROBE_URL, proxy=PROXY_URL, timeout=15.0)
        ok = resp.status_code < 400
    except Exception as exc:  # noqa: BLE001 — 巡检脚本自身不崩
        ok = False
        _log(f"探测异常: {exc}")

    if ok:
        _log(f"OK via {PROXY_URL}")
        STATE_FILE.unlink(missing_ok=True)  # 恢复即重置 cooldown
        return 0

    _log(f"代理异常({PROBE_URL} via {PROXY_URL})")
    url = resolve_webhook_url(ROOT / ".env")
    if not url:
        _log("未配置 webhook,跳过告警")
        return 1
    last = _last_alert()
    if last is not None and (time.time() - last) < COOLDOWN_SECONDS:
        _log("cooldown 内,跳过重复告警")
        return 1
    if send_alert(url, "### ⚠️ Horizon 代理(mihomo)异常\n\n境外源抓取退化中,请检查订阅/节点:\n`docker compose logs proxy`", "Horizon 代理告警"):
        _save_alert()
        _log("已发送告警")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 2.8 收尾

```bash
chmod +x scripts/run_all_pipelines.sh scripts/backup.sh scripts/stage_deploy.sh
git add Dockerfile.vps docker-compose.yml deploy/mihomo/config.template.yaml \
        scripts/run_all_pipelines.sh scripts/backup.sh scripts/stage_deploy.sh scripts/check_proxy.py
git commit -m "feat(deploy): 阿里云部署资产(Dockerfile.vps + 四服务 compose + mihomo sidecar + 运维脚本)"
git push
```

> **必须先 commit + push 再开始云端操作**——这是交接/断点续作的前提（接手方 git clone 即得全部部署资产）。

---

## 3. Phase B — skill 13 步执行（命令级）

工作目录约定：`SKILL=.agents/skills/qianwenai-deploy`。skill 每步的交互/错误语义见其 `reference/deploy/*.md`；下面只列 Horizon 的参数化命令。

### 步骤 1 · 环境检查

```bash
aliyun version                          # 需 3.x
aliyun configure list                   # 默认 profile 带 * 且 Valid
aliyun configure get region             # 应为 cn-guangzhou;否则:
aliyun configure set --profile default --region cn-guangzhou
aliyun oss ls                           # 报未开通则: aliyun ossadmin OpenOssService
aliyun sts GetCallerIdentity            # 记 ACCOUNT_ID
```

无有效凭证 → 按 skill `01_env_check.md` 走 OAuth 认证（禁止在聊天收集 AK/SK）。

### 步骤 2 · Git clone

跳过（本地项目）。

### 步骤 3 · 项目分析

已在本手册完成，产出即 skill 变量：`APP_NAME=horizon`、`APP_DESC="Horizon AI 信息聚合平台"`、`app_type=docker`、`app_mode=docker-compose`、`nginx_mode=static+app`、`app_port=8080`、`static_dir=frontend/dist`。
硬编码密钥检查：`data/config.py` 只含 `api_key_env` 变量名（无密钥本体）；`.env` 与 `data/` 由 staging 白名单排除，不进产物。确认 `git status` 中 `.env`/`data/` 未被 stage。

### 步骤 4 · 存量部署扫描

```bash
aliyun ros ListStacks --RegionId cn-guangzhou --Tag.1.Key from --Tag.1.Value qianwenai
```

过滤 `DELETE_COMPLETE`，比对 tag `qianwenai-appName == horizon`。若存在：⚠️ASK 用户（热更新 or 删旧栈重建）。

### 步骤 5 · 数据库识别

SQLite 无 RDS 信号 → **按"无数据库"跳过**（告知用户：SQLite 随 ECS 本地盘，无需 RDS）。

### 步骤 6 · 实例规格

`ecs.e-c1m1.large`（2C2G，参考 ≈¥0.10/h）。已选定，无需再问。

### 步骤 7 · 生成 ROS 模板

```bash
cd "$SKILL"
python3 scripts/generate_template.py \
  --topology single --app-type docker --app-mode docker-compose \
  --app-port 8080 --nginx-mode static+app \
  --output /tmp/horizon-template.yaml --userdata-output /tmp/horizon-userdata.sh
```

### 步骤 8 · 库存检查

```bash
aliyun ecs DescribeAvailableResource --RegionId cn-guangzhou \
  --DestinationResource InstanceType --InstanceType ecs.e-c1m1.large \
  --InstanceChargeType PostPaid
```

取 `Status ∈ {Available, WithStock}` 的第一个 `ZoneId` 记为 `ZONE_ID`；无货则按 skill 文档给替代（同区换 `ecs.e-c1m2.large` 等）并 ⚠️ASK。

### 步骤 9 · 模板验证 + 询价确认

```bash
python3 "$SKILL/scripts/upload_artifacts.py" --region cn-guangzhou --template-file /tmp/horizon-template.yaml
# → 记录输出 JSON 的 bucket 与 template_url(下称 TEMPLATE_URL、BUCKET)
aliyun ros ValidateTemplate --RegionId cn-guangzhou --TemplateURL "$TEMPLATE_URL"
aliyun ros GetTemplateEstimateCost --RegionId cn-guangzhou --TemplateURL "$TEMPLATE_URL" \
  --Parameters.1.ParameterKey AppName --Parameters.1.ParameterValue horizon \
  --Parameters.2.ParameterKey InstanceType --Parameters.2.ParameterValue ecs.e-c1m1.large \
  --Parameters.3.ParameterKey Password --Parameters.3.ParameterValue "Temp!234567890" \
  --Parameters.4.ParameterKey SystemDiskSize --Parameters.4.ParameterValue 40 \
  --Parameters.5.ParameterKey AppPort --Parameters.5.ParameterValue 8080 \
  --Parameters.6.ParameterKey ZoneId --Parameters.6.ParameterValue "$ZONE_ID" \
  --Parameters.7.ParameterKey UserDataScript --Parameters.7.ParameterValue "#!/bin/bash"
```

汇总每资源每小时 `OriginalAmount`（ECS + EIP + OSS 桶），⚠️ASK 用户确认费用后才继续（skill 硬性确认点）。

### 步骤 10 · 上传产物 + 数据包

```bash
# ① 前端构建(不设 VITE_STATIC_MODE → API 模式,同源 /api)
cd frontend && npm ci && npm run build && cd ..
# ② staging(白名单,防 data/ 泄漏)
bash scripts/stage_deploy.sh /tmp/horizon-deploy-staging
# ③ 上传产物(复用步骤 9 的 BUCKET)
python3 "$SKILL/scripts/upload_artifacts.py" --region cn-guangzhou --bucket "$BUCKET" \
  --static-dir frontend/dist --app-mode docker-compose \
  --app-dir /tmp/horizon-deploy-staging > /tmp/horizon-artifacts.json
# ④ 把产物 URL 烧回模板,重新生成并上传最终模板 → 新 TEMPLATE_URL
cd "$SKILL" && python3 scripts/generate_template.py \
  --topology single --app-type docker --app-mode docker-compose \
  --app-port 8080 --nginx-mode static+app \
  --artifacts-json /tmp/horizon-artifacts.json \
  --output /tmp/horizon-template.yaml --userdata-output /tmp/horizon-userdata.sh && cd -
python3 "$SKILL/scripts/upload_artifacts.py" --region cn-guangzhou --bucket "$BUCKET" \
  --template-file /tmp/horizon-template.yaml   # 输出 JSON 的 template_url 为最终 TEMPLATE_URL
# ⑤ 数据包(先 checkpoint 收拢 WAL,再单文件打包;签名 URL 转内网端点)
sqlite3 data/horizon.db "PRAGMA wal_checkpoint(TRUNCATE);"
tar czf /tmp/horizon-data-bundle.tar.gz \
  data/horizon.db data/auth data/config.py data/reports_pdfs data/summaries .env
aliyun oss cp /tmp/horizon-data-bundle.tar.gz "oss://$BUCKET/data-bundle.tar.gz"
aliyun oss sign "oss://$BUCKET/data-bundle.tar.gz" --timeout 86400
# 把签名 URL 的 host 改为 oss-cn-guangzhou-internal.aliyuncs.com(内网免流量费),记为 DATA_URL
```

### 步骤 11 · 创建栈

生成 ECS 密码（≥12 位，特殊字符仅限 `!@%^*+=_-`，不入聊天/不入文件明文物）：记为 `ECS_PWD`。

```bash
cat > /tmp/horizon-params.json <<EOF
[
  {"key":"AppName","value":"horizon"},
  {"key":"InstanceType","value":"ecs.e-c1m1.large"},
  {"key":"Password","value":"$ECS_PWD"},
  {"key":"SystemDiskSize","value":"40"},
  {"key":"AppPort","value":"8080"},
  {"key":"ZoneId","value":"$ZONE_ID"},
  {"key":"UserDataScript","value":$(python3 -c 'import json;print(json.dumps(open("/tmp/horizon-userdata.sh").read()))')}
]
EOF
APP_NAME=horizon APP_DESC="Horizon AI 信息聚合平台" \
  bash "$SKILL/scripts/create_stack.sh" cn-guangzhou "$TEMPLATE_URL" "qianwenai-horizon-$(date +%Y%m%d%H%M)" /tmp/horizon-params.json
# → StackId;脚本自动写 provisional .qianwenai-deploy(防孤儿栈,重试复用同名栈)
```

### 步骤 12 · 等待终态 + 探活

```bash
python3 "$SKILL/scripts/wait_and_probe.py" --region cn-guangzhou --stack-id "$STACK_ID" --has-app --max-wait 1200
# 成功输出 public_ip / instance_id;探的是 nginx /healthz
```

> 注意：首次 `docker compose up -d`（userdata 触发）会因 `/var/lib/horizon/.env` 尚不存在而失败——**预期行为**，Phase C 第 2 步补齐后手动 `up -d`。bootstrap 日志：`/var/log/qianwenai-bootstrap.log`。

### 步骤 13 · 记录状态

```bash
PASSWORD="$ECS_PWD" python3 "$SKILL/scripts/record_state.py" \
  --stack-id "$STACK_ID" --stack-name "$STACK_NAME" --region cn-guangzhou \
  --topology single --app-type docker --runtime none --nginx-mode static+app \
  --app-mode docker-compose --app-port 8080 \
  --app-dir /tmp/horizon-deploy-staging --static-dir frontend/dist \
  --outputs-json '<wait_and_probe 的 outputs>' \
  --artifact-bucket "$BUCKET" --artifact-urls-json "$(cat /tmp/horizon-artifacts.json)"
# → 写 .qianwenai-deploy(0600)+ .qianwenai-deploy.local(0600),自动加 .gitignore
```

---

## 4. Phase C — 部署后定制（一次性，Cloud Assistant 下发）

通过 Cloud Assistant 在 ECS 上执行脚本（免 SSH；安全组本就不开 22）：

```bash
aliyun ecs RunCommand --RegionId cn-guangzhou --InstanceId.1 "$ECS_ID" \
  --Type RunShellScript --CommandContent "$SCRIPT" --Timeout 600
# → InvokeId;sleep 10 后:
aliyun ecs DescribeInvocationResults --RegionId cn-guangzhou --InvokeId "$INVOKE_ID" --IncludeOutput true
# Output 是 base64,解码查看
```

按顺序下发（脚本均幂等，可整体重跑）：

**C1 · 系统准备 + 数据恢复**（⚠️ASK 用户索取 `PROXY_SUBSCRIPTION_URL` 后再执行写入那行）：

```bash
set -euxo pipefail
timedatectl set-timezone Asia/Shanghai
dnf install -y sqlite
systemctl enable --now crond || true

mkdir -p /var/lib/horizon/data /var/backups/horizon
chmod 700 /var/backups/horizon

curl -fsSL '__DATA_URL__' -o /tmp/data-bundle.tar.gz   # DATA_URL 用内网签名 URL
mkdir -p /tmp/databundle && tar xzf /tmp/data-bundle.tar.gz -C /tmp/databundle
rsync -a /tmp/databundle/data/ /var/lib/horizon/data/
install -m 600 /tmp/databundle/.env /var/lib/horizon/.env
echo 'PROXY_SUBSCRIPTION_URL=__向用户索取__' >> /var/lib/horizon/.env
rm -rf /tmp/data-bundle.tar.gz /tmp/databundle
```

**C2 · 服务器版 config.py 调整**：把 `twitter` 源的 `enabled` 改为 `False`（服务器无 cookies，避免空跑超时；wxmp 走 collector 不受影响）。先 `grep -n '"twitter"' -A5 /var/lib/horizon/data/config.py` 定位块，用 sed 限定块范围替换或手动编辑，改完 `grep` 复核。

**C3 · 启动 + 验证**：

```bash
cd /opt/qianwenai
docker compose up -d                     # 首次构建镜像约 5-15 分钟(apt + uv sync)
docker compose ps
docker compose logs --tail=30 proxy      # 订阅节点加载成功
docker compose logs --tail=30 collector  # 各号 next_run_at 排期正常
curl -sf http://127.0.0.1:8080/api/health
docker compose run --rm -T pipeline horizon-wxmp status   # 已登录
# 代理分流验证:经代理 = 境外 IP;直连 = 广州 IP
docker compose run --rm -T --entrypoint sh pipeline -c 'curl -sx http://proxy:7890 https://api.ipify.org && echo && curl -s https://api.ipify.org && echo'
```

**C4 · cron 安装**（写 `/etc/cron.d/horizon`，整文件替换幂等）：

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 0 * * * root cd /opt/qianwenai && docker compose run --rm -T pipeline bash scripts/run_all_pipelines.sh >> /var/lib/horizon/data/pipeline.log 2>&1
7 10,14,17 * * * root cd /opt/qianwenai && docker compose run --rm -T pipeline horizon-auth-check >> /var/lib/horizon/data/authcheck.log 2>&1
23 */6 * * * root cd /opt/qianwenai && docker compose run --rm -T pipeline uv run python scripts/check_proxy.py >> /var/lib/horizon/data/proxycheck.log 2>&1
5 1 * * * root bash /opt/qianwenai/scripts/backup.sh >> /var/lib/horizon/data/backup.log 2>&1
@reboot root cd /opt/qianwenai && docker compose up -d >> /var/lib/horizon/data/boot.log 2>&1
```

**C5 · 冒烟（可选，费 AI token）**：`docker compose run --rm -T pipeline horizon --hours 1`，重点看 HN/Reddit/RSS 成功率。

**C6 · 输出 runbook**：把访问地址 `http://<IP>/`、栈名/StackId、OSS 桶、备份位置、续期/热更新/删除命令写成一小节展示给用户（模板见第 7 节）。

---

## 5. 后续热更新 SOP（用户说「更新线上版本」时）

前提：仓库根存在 `.qianwenai-deploy`。

```bash
cd frontend && npm run build && cd ..              # 前端有改动才需要
bash scripts/stage_deploy.sh /tmp/horizon-deploy-staging
python3 "$SKILL/scripts/upload_artifacts.py" --region cn-guangzhou \
  --bucket "$(python3 -c 'import json;print(json.load(open(".qianwenai-deploy"))["artifact_bucket"])')" \
  --static-dir frontend/dist --app-mode docker-compose \
  --app-dir /tmp/horizon-deploy-staging > /tmp/horizon-artifacts.json
STATIC_URL=$(python3 -c 'import json;print(json.load(open("/tmp/horizon-artifacts.json"))["static_url"])')
APP_URL=$(python3 -c 'import json;print(json.load(open("/tmp/horizon-artifacts.json"))["app_url"])')
STATIC_URL="$STATIC_URL" APP_URL="$APP_URL" bash "$SKILL/scripts/update_app.sh"
```

ECS 端自动：staging 下载 → 停 compose → `/opt/qianwenai` 原子替换 → `up -d --build` → `curl -sf localhost:8080/` 健康检查（15 次重试）→ 失败自动回滚。数据、cron、`.env` 不受影响（都在 `/opt/qianwenai` 之外）。IP 不变。状态文件自动更新 `updated_at` / `previous_artifact_urls`。

## 6. 删除 SOP（用户说「删除/清理/释放」时）

> ⚠️ 不可逆：系统盘上的 `/var/lib/horizon`（含库、登录态）与 `/var/backups/horizon` 随栈销毁。**删前必须先把最新备份拉回本机**（`aliyun oss cp` 反向或 Cloud Assistant 打包上传）。二次确认后：
> `bash "$SKILL/scripts/delete_stack.sh" --project-root . --yes`
> 严禁手动逐个删资源。

## 7. 交接与运维 runbook（部署完成后填写）

```
访问地址:  http://<PUBLIC_IP>/(SPA)/ http://<PUBLIC_IP>/api/health
栈:        <STACK_NAME> / <STACK_ID>(cn-guangzhou),tag from=qianwenai
状态文件:  仓库根 .qianwenai-deploy(0600,gitignore;热更新/删除的钥匙,交接时安全渠道拷贝)
OSS 桶:    <BUCKET>(产物+数据包,7 天 lifecycle)
服务器:    应用 /opt/qianwenai(热更新原子替换);数据 /var/lib/horizon/{data,.env};备份 /var/backups/horizon
日志:      /var/log/qianwenai-{bootstrap,app,update}.log;/var/lib/horizon/data/{pipeline,authcheck,proxycheck,backup}.log
微信续期:  token 30 天过期 → auth-check 钉钉告警 → 本机 `uv run horizon-wxmp login` 扫码 →
           新 data/auth/weread.json 经 OSS 传 → Cloud Assistant 覆盖 /var/lib/horizon/data/auth/
           (collector 每 60s 自动探测恢复,无需重启)
代理续期:  订阅 URL 变更 → 改 /var/lib/horizon/.env 的 PROXY_SUBSCRIPTION_URL →
           docker compose restart proxy;节点失效 mihomo url-test 自动切,不用管
热更新:    见第 5 节;删除: 见第 6 节(先拉备份!)
```

**断点续作**（中途换人/换机）：栈名固定复用（重复执行不重复开资源）；建栈即写 provisional 状态文件；Phase A 已 push 到 git；数据包在 OSS 保留 7 天（签名 URL 过期可用凭证重签）；Phase C 脚本幂等可重跑。栈一旦创建即按量计费（~¥0.10/h + EIP），长时间搁置应删栈（先拉备份）。

---

## 8. 风险与故障排查

| 风险 | 缓解 | 排查 |
|---|---|---|
| 代理不稳（用户核心要求） | ① url-test 自动切节点 ② restart unless-stopped + 订阅 1h 自刷 ③ 每 6h `check_proxy.py` 巡检发 webhook ④ 管道 `return_exceptions=True`，代理抖动只丢当批境外源 | `docker compose logs proxy`；`docker exec horizon-proxy wget -qO- http://127.0.0.1:9090/proxies`；机场跑路/订阅过期 → 换 `.env` 一处 URL |
| 镜像拉取（鸡生蛋：`python:3.11-slim`、`metacubex/mihomo` 在 Docker Hub，大陆靠阿里加速器） | Alibaba Cloud Linux 预配加速器一般可用 | 失败则 fallback：本机（有代理）`docker build --platform linux/amd64 -f Dockerfile.vps -t horizon:local . && docker save horizon:local | gzip > /tmp/horizon-image.tar.gz` → OSS → ECS `docker load`，compose 去掉 `build:` 段；mihomo 同理（或本机拉 `metacubex/mihomo:Meta` 转存） |
| 首次 boot `compose up` 失败（`.env` 未就位） | **预期行为**，Phase C 补齐后手动 up | `/var/log/qianwenai-bootstrap.log` |
| 删栈 = 数据全丢 | 每日备份留 14 份；建议定期 `rsync` 回本机 | 删栈前必须拉回最新备份（第 6 节） |
| 公网无鉴权 | 用户已接受；`/debug` fail-closed（`HORIZON_API_ENV` 不设即关） | 需要时后续加 nginx basic auth（自定义 userdata，超出本手册） |
| 境外 AI provider 切换 | 无需改配置：不在 NO_PROXY 的域名自动走代理 | — |
| EIP 流量费 | 按量计费，微信图床代理经服务器中转会产生流量 | 控制台账单；异常时查 nginx 访问日志 |

## 9. 部署完成验证清单

- [ ] **代理分流**：pipeline 容器内经代理出口为境外 IP、直连为广州 IP；`logs proxy` 节点 url-test 正常
- [ ] **境外源冒烟**：`horizon --hours 1`，HN/Reddit/RSS 成功率与本机相当
- [ ] `http://<EIP>/` 打开 SPA 有数据；`http://<EIP>/api/health` 返回 ok
- [ ] 前端收藏一条新闻，刷新后仍在（API 写模式生效）
- [ ] `docker compose ps`：proxy、collector、api 均 Up；`logs collector` 显示各号 next_run_at
- [ ] `docker compose run --rm -T pipeline horizon-wxmp status` 已登录
- [ ] `sqlite3 /var/lib/horizon/data/horizon.db "PRAGMA journal_mode;"` 返回 `wal`
- [ ] 手动跑一次 `bash scripts/run_all_pipelines.sh` 三条管道 OK（FAIL 时收到 webhook）
- [ ] `backup.sh` 跑一次，`/var/backups/horizon/` 有库+资产包；恢复演练（v2 §7.3：停 collector → `.restore` 到临时库 → 抽查四表计数 → 换回）
- [ ] 第二天查 `pipeline.log`/`backup.log`/`authcheck.log`/`proxycheck.log` 确认 cron 生效
- [ ] 执行一次热更新全流程（第 5 节，改个小文案验证），确认 IP 不变、数据不动、回滚可信
- [ ] runbook（第 7 节）已填写并交付用户

---

*文档版本：v1.0 · 2026-08-18 · 基于 qianwenai-deploy skill v2.2 与 horizon-vps-deployment-plan-v2.md 设计*
