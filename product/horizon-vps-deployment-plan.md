# Horizon VPS 完整自动化部署方案

> **⚠️ 已过时，被 v2 取代**：微信抓取已拆成常驻 collector，v1 的「crontab 跑一次全管道」模型不再成立。
> 请用 **`horizon-vps-deployment-plan-v2.md`**（collector 常驻 + 双服务 Compose + SQLite 加固 + 备份告警）。
> 本文件仅保留作历史对照。

> 状态：待评审
> 目标：三个管道（新闻 + 报告 + 论文）全部定时、自动、稳定运行
> 部署方式：VPS + Docker Compose + crontab

---

## 1. 背景与现状

### 当前架构

```
GitHub Actions (定时 daily-summary.yml)
  └─ uv run horizon --hours 24
       ├─ RSS / HN / GitHub / Reddit / GDELT / ... ✅
       ├─ wxmp 公众号              ✅ (we_read 纯 HTTP,需扫码登录)
       ├─ Twitter / Playwright     ❌ (无 Playwright)
       ├─ Reports 管道             ❌ (从未调度)
       └─ Papers 管道              ❌ (从未调度)
```

GitHub Actions 跑的是新闻管道的子集。Twitter/Playwright 依赖本地浏览器；wxmp 走 we_read 纯 HTTP 通道（转发服务 weread.111965.xyz），仅需一次微信扫码登录；Reports 和 Papers 管道从未加入自动化调度。

### 三个独立管道一览

| 管道 | CLI | 外部服务依赖 | 浏览器依赖 |
|------|-----|-------------|-----------|
| **新闻** | `horizon` | RSS/HN/GitHub/Reddit + we_read 微信核心 / Twitter / Apify | 可选的 Playwright |
| **报告** | `horizon-reports` | we_read 微信核心 + aliyun.com + aliresearch + fxbaogao | Playwright (必选) |
| **论文** | `horizon-papers` | 默认只跑 **arXiv 每周精选**;经典论文走 **OpenAlex**(一次性入库,按需 `--source openalex`);Semantic Scholar / Crossref 作 enrichment 兜底 | 无 |

---

## 2. 部署架构

```
┌──────────────────────────────────────────────────────────┐
│                     VPS (一台 Linux 服务器)                 │
│                                                            │
│  Docker Compose 服务栈:                                     │
│                                                            │
│  ┌──────────────────────────────────────────────┐          │
│  │               horizon                         │          │
│  │  (含 Playwright + we_read 微信核心)            │          │
│  │  新闻 + 报告 + 论文                             │          │
│  └──────────────────┬───────────────────────────┘          │
│                     │                                      │
│                     ▼                                      │
│              data/auth/    weread.json (微信登录态)          │
│              data/horizon.db / reports_pdfs/               │
│              data/aliyun_profile/                          │
│                                                            │
│  宿主机 crontab ── 08:00 CST ──► docker compose run horizon │
│                                                            │
│  结果 ──► docs/ ──► git push gh-pages ──► GitHub Pages     │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 具体实施步骤

### 第 1 步：VPS 环境准备

| 项目 | 推荐配置 |
|------|---------|
| OS | Ubuntu 22.04 / Debian 12 |
| CPU | 2 核 |
| RAM | 2 GB |
| 磁盘 | 20 GB (SSD 更佳) |
| 软件 | Docker + Docker Compose V2 + Git |

**推荐服务商：** Hetzner CX22（~€5/月）、阿里云 ECS（~¥50/月）、Oracle Cloud 免费层（4核24GB 免费）

**初始化命令：**

```bash
# 安装 Docker (Ubuntu)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 克隆仓库
git clone https://github.com/你的用户名/horizon.git /opt/horizon
cd /opt/horizon
```

### 第 2 步：微信登录态

微信公众号抓取使用 **we_read 纯 HTTP 通道**（转发服务 weread.111965.xyz），
无需浏览器 / 独立服务。登录态就是 `data/auth/weread.json`：

```
data/auth/
└── weread.json   # 微信登录 token（JSON）
```

**初始化方式 A：本机扫码后迁移**

```bash
# 本机先扫码登录（自动写入 data/auth/weread.json）
uv run horizon-wxmp login
uv run horizon-wxmp status   # 确认已登录

# 把登录态随仓库/同步传到 VPS
scp -r data/auth user@your-vps:/opt/horizon/data/
```

**初始化方式 B：在 VPS 上直接扫码**（需要把二维码图片拿到本机扫）

```bash
docker compose run --rm horizon horizon-wxmp login
# 二维码保存为容器内 /app/data/auth/weread_qrcode.png
# 通过 docker cp 取出后用微信扫一扫本地图片即可
```

订阅公众号 = 用 `uv run horizon-wxmp subscribe <分享链接>` 从分享链接自动解析公众号
并写回 `data/config.py`（`sources.wxmp.feeds[].weread_mp_id`，也可用
`horizon-wxmp migrate` 批量迁移），无需在外部平台操作。

### 第 3 步：Docker Compose 配置

```yaml
# docker-compose.yml（单服务：微信核心已内置）
services:
  horizon:
    build:
      context: .
      dockerfile: Dockerfile.vps
    container_name: horizon
    restart: unless-stopped
    volumes:
      - ./data:/app/data              # 共享数据目录（含 data/auth 登录态）
      - ./.env:/app/.env:ro           # API Key 等环境变量
      - ./docs:/app/docs              # GitHub Pages 输出目录
      - ./scripts:/app/scripts:ro     # 调度脚本
      - ~/.ssh:/root/.ssh:ro          # GitHub 部署密钥
    environment:
      - TZ=Asia/Shanghai
    # 默认不启动，crontab 执行 docker compose run
    stdin_open: true
    tty: true
```

### 第 4 步：新建 Dockerfile.vps

```dockerfile
FROM python:3.12-slim

# 系统依赖（Playwright 需要 chromium 的系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 依赖文件
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra twitter

# Playwright 浏览器
RUN uv run playwright install --with-deps chromium

# 源码
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/config.py ./data/config.py

# docs 用于 gh-pages 输出
RUN mkdir -p /app/data /app/docs
```

> 相比当前 Dockerfile 的变化：
> 1. 增加 `git` 安装（脚本需要 `git push`）
> 2. 增加 `--extra twitter` 安装 Playwright
> 3. 增加 Playwright chromium 浏览器安装
> 4. 保留 `uv run horizon` 入口

### 第 5 步：全管道调度脚本

```bash
#!/bin/bash
# scripts/run_all_pipelines.sh
# 按顺序执行三个管道，完成后推送 GitHub Pages

set -euo pipefail

cd /app
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== Horizon Run: $TIMESTAMP ==="

RESULTS=()

# 1️⃣ 新闻管道
echo "--- [1/4] News Pipeline (24h) ---"
uv run horizon --hours 24 && RESULTS+=("news:OK") || RESULTS+=("news:FAIL")

# 2️⃣ 报告管道
echo "--- [2/4] Reports Pipeline ---"
uv run horizon-reports && RESULTS+=("reports:OK") || RESULTS+=("reports:FAIL")

# 3️⃣ 论文管道
echo "--- [3/4] Papers Pipeline ---"
# 首次部署/补库跑全部(经典 OpenAlex 一次性入库 + arXiv 每周精选);
# 日常 cron 默认 `horizon-papers` 只跑 arXiv 每周精选即可。
uv run horizon-papers --source all && RESULTS+=("papers:OK") || RESULTS+=("papers:FAIL")

# 4️⃣ 导出前端静态数据
echo "--- [4/4] Export Static Data ---"
uv run python scripts/export_static_data.py \
    --db data/horizon.db \
    --out docs/data

# 推送到 GitHub Pages
echo "--- Push to GitHub Pages ---"
cd /app/docs
git config user.name "Horizon Bot"
git config user.email "horizon-bot@users.noreply.github.com"
git add -A
git commit -m "auto update $(date +%Y-%m-%d)" 2>/dev/null || echo "Nothing to commit"
git push origin gh-pages 2>/dev/null && echo "Pushed OK" || echo "Push skipped"

# 汇总日志
echo "=== Summary: ${RESULTS[*]} ===" >> /app/data/pipeline.log
echo "[$TIMESTAMP] ${RESULTS[*]}" >> /app/data/pipeline.log
```

### 第 6 步：宿主机 crontab（最可靠的方式）

```cron
# sudo crontab -e
# 每天早上 08:00 CST = UTC 00:00
0 0 * * * cd /opt/horizon && docker compose run --rm horizon bash scripts/run_all_pipelines.sh >> data/pipeline.log 2>&1
```

相比容器内循环调度器，宿主机 crontab 更可靠：
- 容器重启不影响定时
- `docker compose run --rm` 每次运行新容器，不会残留进程
- 日志写回宿主机不会丢失

### 第 7 步：GitHub Pages 部署密钥

VPS 需要有权限推送到 `gh-pages` 分支：

```bash
# 在 VPS 上生成部署密钥
ssh-keygen -t ed25519 -f ~/.ssh/horizon_ghpages -N ""

# 查看并添加到 GitHub → Settings → Deploy keys
# 仓库: https://github.com/你的用户名/horizon/settings/keys
# 勾选 "Allow write access"
cat ~/.ssh/horizon_ghpages.pub

# 添加 GitHub 主机指纹
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

密钥在 docker compose 中以 volume 方式挂载进容器。

### 第 8 步：数据目录结构（最终形态）

```
/opt/horizon/
├── docker-compose.yml
├── Dockerfile.vps
├── .env                          # API Keys
├── data/
│   ├── config.py                 # 配置（复用现有）
│   ├── horizon.db                # SQLite 数据库
│   ├── pipeline.log              # 运行日志
│   ├── reports_pdfs/             # 已下载的 PDF
│   ├── aliyn_profile/            # 阿里云登录态（Playwright）
│   ├── wxmp_browser_profile/     # 微信浏览器配置（报告 PDF 解析）
│   └── auth/                     # 微信登录态（we_read 纯 HTTP）
│       └── weread.json           # 微信登录 token（JSON）
├── docs/                         # GitHub Pages（挂载 git）
│   ├── _posts/                   # 每日摘要
│   ├── data/                     # 前端静态数据
│   └── app/                      # React 编译产物
├── scripts/
│   ├── run_all_pipelines.sh
│   └── export_static_data.py
└── src/                          # 源码
```

---

## 4. 需要改动的代码文件

### 后端（含可靠性增强）

| 文件 | 改动 | 影响 |
|------|------|------|
| `src/services/webhook.py` | `notify()` 方法加入 3 次指数退避重试 | 网络抖动不丢通知 |
| `src/orchestrator.py` | `run()` 返回结构化 `PipelineResult` | 脚本可获取每个 scraper 结果 |
| `data/config.py` | 检测 `VPS` 环境（非 CI 环境）时启用全部源 | VPS 上 wxmp/Twitter 自动开启 |

### 基础设施

| 文件 | 操作 | 说明 |
|------|------|------|
| `Dockerfile.vps` | **新建** | 含 Playwright、git 的生产镜像 |
| `docker-compose.yml` | **重写** | 双服务栈 + 健康检查 |
| `scripts/run_all_pipelines.sh` | **新建** | 全管道调度 + 推 gh-pages |
| `.github/workflows/daily-papers.yml` | **新建** | CI 备用（VPS 出问题时兜底） |
| `.github/workflows/daily-reports.yml` | **新建** | CI 备用 |

---

## 5. 可靠性增强细节

### Webhook 重试

```python
# 当前：单次 POST，失败即丢弃
# 改为：最多 3 次，指数退避

MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        resp = await client.post(url, json=payload, timeout=15.0)
        resp.raise_for_status()
        break
    except (ConnectError, TimeoutException) as exc:
        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(2 ** attempt)
            continue
        raise  # 最后一次失败仍抛出，由外层 except 处理
```

### 空结果检测

脚本中检测 24h 内条目数：

```bash
uv run python -c "
from src.storage.db import HorizonDB
db = HorizonDB()
count = db.get_item_count_since('$(date -d '-24 hours' +%Y-%m-%d)')
print(count)
"
```

如果 `count == 0`，通过 webhook 发送告警消息。

### CI 备用

- 三个 `.github/workflows/daily-*.yml` 独立定时
- VPS 正常时，CI 的 `GITHUB_TOKEN` 推送是幂等的（每日覆盖写 docs/）
- VPS 故障时，CI 管道能兜底基础源的结果

---

## 6. 部署后验证清单

- [ ] **构建测试**：`docker compose build horizon` 正常通过
- [ ] **微信登录态**：`docker compose run --rm horizon horizon-wxmp status` 显示已登录
- [ ] **新闻管道**：`docker compose run --rm horizon horizon --hours 48` 成功输出
- [ ] **报告管道**：`docker compose run --rm horizon horizon-reports` 成功输出
- [ ] **论文管道**：`docker compose run --rm horizon horizon-papers` 成功输出
- [ ] **全管道脚本**：`bash scripts/run_all_pipelines.sh` 全部步骤通过
- [ ] **GitHub Pages**：VPS push 后，浏览器访问 GitHub Pages 数据更新
- [ ] **自动定时**：设置 crontab 后第二天检查 `data/pipeline.log`
- [ ] **故障测试**：临时改错 API Key，观察 webhook 告警

---

## 7. 运营成本估算

| 项目 | 月费用 |
|------|--------|
| VPS (Hetzner CX22) | ~€5 (~¥40) |
| LLM API (DeepSeek 为主) | ~¥10-30 |
| 域名（可选） | ~¥10 |
| **合计** | **¥60-80/月** |

---

## 8. 未纳入本次规划的内容

以下内容可以后续考虑，但不是 VPS 部署的阻塞项：

- **horizon-api (FastAPI)** — VPS 上可部署 API 服务替代静态 JSON，让前端有搜索/过滤能力。需要 Node.js 构建前端 + 额外端口
- **微信订阅自动发现** — 订阅公众号用 `horizon-wxmp subscribe <分享链接>` 从分享链接解析并写回 `data/config.py`（配置字段 `weread_mp_id`）；暂不支持在 Horizon 内搜索公众号并自动添加
- **监控面板** — 可用 Uptime Kuma / Grafana 监控管道健康度
- **Sentry 集成** — 收集运行时异常

---

*文档版本：v1.0*
*最后更新：2026-07-30*
