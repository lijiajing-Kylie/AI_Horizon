# Horizon VPS 自动化部署方案 v2

> 状态：待评审
> 版本：v2.0
> 取代：v1（2026-07-30，`horizon-vps-deployment-plan.md`）
> 最后更新：2026-08-17
>
> 目标：新闻 + 报告 + 论文三条管道定时跑，**微信抓取以常驻 collector 运行**，数据库加固 + 每日备份，关键故障能告警。

---

## 0. v2 相对 v1 的关键变化

v1 的模型是「crontab 每天跑一次 `docker compose run` 全管道，微信顺带抓」。**微信抓取拆成独立常驻 collector 之后，这个模型不成立了**：

| 变化点 | v1 | v2 |
|---|---|---|
| 微信抓取 | 随 `horizon` 管道一次性抓 | **常驻 daemon** `horizon-wxmp-collector`，每号随机 4-8h 间隔落中间表 `wxmp_articles` |
| 定时形态 | 全部 cron | **collector 常驻（systemd/容器 restart）+ 管道 cron**，两类机制 |
| 进程形态 | 单服务镜像 | **双服务 Compose**：`horizon`（瞬态管道）+ `collector`（常驻） |
| SQLite | 本机直连，未加固 | **`busy_timeout` + WAL + 每日备份**（部署后多进程并发写是常态，本机没有这个条件） |
| 微信登录态 | 一次性扫码 | **30 天过期**（`token_max_age_days=30`），需迁移 + 续期 + 失效告警 |

---

## 1. 目标架构

```
┌──────────────────────────────────────────────────────────────┐
│                      一台 VPS（Ubuntu 22.04 / Debian 12）        │
│                                                              │
│  ┌─────────────────┐    ┌────────────────────────────────┐   │
│  │   collector      │    │   horizon（管道，瞬态容器）        │   │
│  │   常驻 daemon     │    │   news / reports / papers      │   │
│  │   restart: up    │    │   cron → docker compose run --rm│   │
│  └────────┬─────────┘    └──────────────┬─────────────────┘   │
│           │        共享 data/ volume      │                     │
│  ┌────────┴─────────────────────────────┴───────────────┐   │
│  │  data/                                                │   │
│  │   ├── horizon.db            # 唯一主库（含 wxmp_articles） │   │
│  │   ├── config.py             # 运行时主配置（volume 为准）    │   │
│  │   ├── auth/weread.json      # 微信登录态（30 天过期）        │   │
│  │   ├── auth/weread_sync.json # collector 调度状态           │   │
│  │   └── reports_pdfs/         # 报告 PDF 资产                │   │
│  └──────────────────────────────────────────────────────┘   │
│  每日备份 → /var/backups/horizon/（异地可再加 rsync）           │
│  GitHub Pages:管道产物推 gh-pages                             │
└──────────────────────────────────────────────────────────────┘
```

**一句话**：collector 永远在跑、管道按点跑、数据全在一个 volume 里、每天备份、失败能告警。

---

## 2. 前置代码改动（部署前必做）

部署后 collector（7×24 常驻）+ 管道 + API 是**多个独立进程写同一个 SQLite 文件**，这是本机没有的新条件。以下 1、2 项是硬前提，不做就有锁崩溃风险；3 项强烈建议。

### 2.1 `busy_timeout=30`（必改）

`src/storage/db.py:803` 的连接目前没设超时，默认 5 秒 busy timeout。撞锁时（低概率但会真发生）`sqlite3.OperationalError` 会让 daemon 整个退出。改一行：

```python
conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
```

### 2.2 开启 WAL（必改）

WAL 让读不阻塞写、写不阻塞读，配合 busy_timeout 基本消灭 `database is locked`。`journal_mode` 是持久设置，但最好在代码里显式声明，避免库被复制/恢复后悄悄回到默认模式。在 `conn` property 里（db.py:804 之后）加：

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")
```

> 不想改代码的话，`sqlite3 data/horizon.db "PRAGMA journal_mode=WAL;"` 一条命令也能立即持久生效（存在库文件头里）。但 busy_timeout 是**连接级**的，必须代码里设，所以 2.1 躲不掉。

### 2.3 daemon 补 SQLite 锁容错（建议）

`src/wxmp_collector/daemon.py:191-196` 目前只捕 `WeReadAuthError` / `WeReadError`。撞锁抛出的 `sqlite3.OperationalError` 会一路冒到 cli.py 顶层，daemon 硬退出。加一层，让锁错误按「单号失败跳过」处理，而不是进程退出：

```python
except sqlite3.OperationalError as exc:
    logger.warning("数据库忙，跳过 %s：%s", f.name, exc)
```

### 2.4 登录失效:自动等待重登(无需重启)

daemon 遇到 `WeReadAuthError` 会**进入等待重登**:每 `auth_poll_sec`(默认 60s)探测一次登录态,期间日志持续提示「运行 `uv run horizon-wxmp login` 扫码后自动恢复」;扫码后自动重试当前公众号并继续抓取,**无需重启进程**。仅当等待超过 `auth_max_wait_sec`(默认不限,需限制时在 `run_daemon` 传参)时以**退出码 3** 停止,供部署层识别「需人工重登」。4.2 节 collector 用 `unless-stopped`(进程常驻不退出,崩溃/宿主机重启自动拉起,且登录失效不再触发「退出→restart」空转)。

---

## 3. VPS 环境准备

| 项目 | 推荐配置 |
|------|---------|
| OS | Ubuntu 22.04 / Debian 12 |
| CPU / RAM | 2 核 / 2 GB（Oracle 免费层 4C24G 也行） |
| 磁盘 | 20 GB SSD（主库 ~175MB + reports_pdfs，够用） |
| 软件 | Docker + Compose V2 + Git |

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
git clone <repo> /opt/horizon && cd /opt/horizon
```

---

## 4. 镜像与 Docker Compose v2

### 4.1 Dockerfile.vps

相对现有 `Dockerfile` 的改动：**去掉 `COPY data ./data`**（data 是运行时状态，必须走 volume，否则会把本机配置/登录态烤进镜像）；加 `git`（gh-pages push）；Playwright 按需。

```dockerfile
FROM python:3.11-slim

# git:gh-pages push;curl:告警/健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# 可选:报告管道 PDF 浏览器解析需要 Playwright。
# 需要时再开,镜像会大很多;不需要就注释掉(报告无 PDF 时 fail-open 只给文章链接)。
# RUN uv run playwright install --with-deps chromium

COPY src ./src
COPY scripts ./scripts
# 注意:不 COPY data/ —— 运行时数据一律由 volume 挂载。

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uv", "run"]
CMD ["horizon", "--help"]
```

### 4.2 docker-compose.yml（双服务）

```yaml
services:
  # 管道入口:restart 不设,由 cron 用 `docker compose run --rm` 瞬态拉起。
  # 不要让这个服务常驻 --hours 24(现有 compose 的用法会跑完即退 + unless-stopped 反复重启)。
  horizon:
    build:
      context: .
      dockerfile: Dockerfile.vps
    image: horizon:local
    container_name: horizon
    restart: "no"
    volumes:
      - ./data:/app/data          # 唯一持久状态(库/登录态/PDF/config.py)
      - ./.env:/app/.env:ro
      - ./scripts:/app/scripts:ro
      - ./docs:/app/docs          # gh-pages 输出目录(需先初始化为 gh-pages 工作树,见 4.3)
      - ~/.ssh:/root/.ssh:ro      # gh-pages 部署密钥
    environment:
      - TZ=Asia/Shanghai
    stdin_open: true
    tty: true

  # 微信常驻采集:与管道共享 data/ volume,写同一个 horizon.db。
  # restart: unless-stopped —— 崩溃/宿主机重启自动拉起。登录失效时进程不退出
  #   (进入等待重登,扫码后自动恢复),因此不会像「退出+restart」那样空转重启。
  collector:
    image: horizon:local
    container_name: horizon-collector
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
    environment:
      - TZ=Asia/Shanghai
    entrypoint: ["uv", "run", "horizon-wxmp-collector"]
    # 不带子命令 = 常驻循环;手动补抓用:
    #   docker compose run --rm --entrypoint "" collector uv run horizon-wxmp-collector once
```

> 两个服务必须先用 4.1 构建一次镜像再 `up -d`:
> `docker compose build && docker compose up -d collector`
> 常驻的只有 `collector`;`horizon` 只在 cron 里 `run --rm` 出现,不 `up -d`。

### 4.3 gh-pages 输出目录初始化

`docs/` 需要一个能 push 的 gh-pages 工作树（一次性初始化）：

```bash
cd /opt/horizon
git fetch origin gh-pages:gh-pages 2>/dev/null || git checkout --orphan gh-pages
git worktree add docs gh-pages   # 把 gh-pages 分支签出到 docs/ 子目录
```

容器内 `scripts/run_all_pipelines.sh` 会 `cd /app/docs && git add -A && git commit && git push`，`~/.ssh` 已挂载（部署密钥见第 6 步的 v1 文档或 GitHub Deploy keys）。

---

## 5. 微信登录态迁移与订阅

登录态就是 `data/auth/weread.json`（we_read 纯 HTTP 通道，无需浏览器服务）。collector 的调度状态在 `data/auth/weread_sync.json`——**两者都在 data/ volume 里，容器重建不丢**。

```bash
# 本机扫码(写 data/auth/weread.json)
uv run horizon-wxmp login
uv run horizon-wxmp status

# 迁移到 VPS(首次部署)
scp -r data/auth user@vps:/opt/horizon/data/

# 在 VPS 上验证
docker compose run --rm horizon horizon-wxmp status
```

订阅公众号仍走 `horizon-wxmp subscribe <分享链接>`（写回 `data/config.py`，也是 volume 里的运行时文件）。

> **token 30 天过期**（`token_max_age_days=30`）。到期的信号是 daemon 日志里 `登录失效;运行 uv run horizon-wxmp login 扫码后自动恢复。`，collector 进入等待重登（每 ~60s 探测一次），扫码后自动恢复，**无需重启**。把这条变成告警，见第 8 节；过期后重新扫码即可。

---

## 6. 定时编排

### 6.1 collector：常驻（不要用 cron）

`docker compose up -d collector` 已经常驻 + 自动拉起，不需要额外调度。要验证它活着：

```bash
docker compose logs --tail=50 collector
docker compose run --rm horizon horizon-wxmp-collector status   # 看每号 next_run_at / 中间表计数
```

### 6.2 管道：宿主机 crontab

三个管道按点跑，时间错开（错开 collector 的随机抓取，减小 DB 写锁碰撞窗口）：

```cron
# sudo crontab -e（宿主时区,以下为 CST 早上,错开整点）
17 0 * * * cd /opt/horizon && docker compose run --rm horizon bash scripts/run_all_pipelines.sh >> data/pipeline.log 2>&1
5  1 * * * /opt/horizon/scripts/backup.sh >> /opt/horizon/data/backup.log 2>&1
```

> `docker compose run --rm` 每次起新容器，跑完即销毁，不残留进程；日志写回宿主机 `data/`。

### 6.3 scripts/run_all_pipelines.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /app

RESULTS=()
run() {
  local name="$1"; shift
  echo "--- [$name] ---"
  if "$@" >> /app/data/pipeline.log 2>&1; then RESULTS+=("$name:OK")
  else RESULTS+=("$name:FAIL"); fi
}

# 首次部署用 `--source all` 把经典论文一次性入库,之后日常只跑 arXiv 每周精选。
run "news"    uv run horizon --hours 24
run "reports" uv run horizon-reports
run "papers"  uv run horizon-papers
run "export"  uv run python scripts/export_static_data.py --db data/horizon.db --out docs/data

# 推 GitHub Pages
echo "--- [push] ---"
if (cd /app/docs && git add -A && git commit -m "auto $(date +%F)" 2>/dev/null && git push origin gh-pages); then
  RESULTS+=("push:OK")
else
  RESULTS+=("push:SKIP")
fi

echo "[$(date '+%F %T')] ${RESULTS[*]}" >> /app/data/pipeline.log
```

> 微信文章不走 `horizon` 管道实时抓了：`horizon` 默认从 `wxmp_articles` 中间表读（`use_collector` + 非 `--live-wxmp`），collector 喂数据即可。

---

## 7. 数据库：SQLite 加固 + 备份恢复

**结论：不换 Postgres。** 写并发极低（管道一天一次 + collector 每号 4-8h 一次），SQLite 单写者模型完全够；换 PG 要重做连接、`ON CONFLICT`、trigram FTS 中文搜索和迁移机制，为一个不会遇到的瓶颈不值得。加固三件事：

### 7.1 已做（第 2 节）
- `busy_timeout=30` + WAL：多进程并发的基石。

### 7.2 每日备份脚本 scripts/backup.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/horizon
BACKUP_DIR="${BACKUP_DIR:-/var/backups/horizon}"
mkdir -p "$BACKUP_DIR"
ts="$(date +%F_%H%M)"

# WAL 模式下必须用 sqlite3 .backup(自带 checkpoint),裸 cp 可能拷到不一致快照
sqlite3 data/horizon.db ".backup '$BACKUP_DIR/horizon-$ts.db'"

# 登录态/调度状态/PDF/配置是唯一性资产,随库一起备
tar czf "$BACKUP_DIR/assets-$ts.tgz" -C data auth reports_pdfs config.py 2>/dev/null || true

# 保留最近 14 份
ls -1t "$BACKUP_DIR"/horizon-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[$(date '+%F %T')] backup OK" >> data/backup.log
```

- 权限：`chmod 700 /var/backups/horizon`，库含微信 token，别让它世界可读。
- 异地：定期 `rsync -a /var/backups/horizon/ user@other:/backup/horizon/`，或挂到对象存储。备份能防误删/崩溃，防不了机房着火。

### 7.3 恢复演练（部署后至少做一次）

```bash
# 停 collector,避免恢复期间写入
docker compose stop collector
sqlite3 /tmp/restore.db ".restore '$BACKUP_DIR/horizon-最新.db'"
# 抽查:三管道各一张表 + 中间表
sqlite3 /tmp/restore.db "SELECT COUNT(*) FROM items;
SELECT COUNT(*) FROM papers; SELECT COUNT(*) FROM reports;
SELECT COUNT(*) FROM wxmp_articles;"
# 确认后再真正恢复
cp /tmp/restore.db data/horizon.db && docker compose start collector
```

---

## 8. 监控与告警

复用现有 `HORIZON_WEBHOOK_URL`（钉钉/飞书/Slack/Discord，见 `.env.example`；未配置时回退 `DINGTALK_WEBHOOK_URL`）。三个「静默退化」点必须告警：

| 故障 | 触发 | 实现 |
|---|---|---|
| **微信登录失效**（30 天 token） | `horizon-wxmp status` rc!=0（`validate_token` 探测 401，见 `src/wxmp_cli.py`） | **已实现**：`scripts/check_weread_login.py`（cron 每天 10/14/17 点）。失效时按 24h cooldown 发通用 webhook（URL 自动适配钉钉/飞书/Slack/Discord），登录恢复即重置；发送失败不写状态、下次巡检重试。核心逻辑 `src/services/auth_alert.py`；VPS 上用 `docker compose run --rm horizon horizon-auth-check` 手动巡检（`--dry-run` 只打印 payload） |
| **collector 空跑** | 某轮抓取 0 篇 | 每日 cron 对比 `wxmp_articles` 计数，环比为 0 则告警 |
| **管道 FAIL** | pipeline.log 含 `FAIL` | 第 6.3 节脚本的 `RESULTS` 里含 FAIL 时发 webhook |

后两个告警点复用 Python 发送函数（自动适配平台 + 错误码校验，替代 bash 裸 curl）：

```python
# 例:cron 脚本内
import httpx
from src.services.auth_alert import build_alert_payload, check_response_ok, resolve_webhook_url

url = resolve_webhook_url("/app/.env")
if url:
    resp = httpx.post(url, json=build_alert_payload(url, "告警内容"), timeout=10.0)
    ok, why = check_response_ok("generic", resp)
```

> 注意：飞书 text 消息的 `content` 必须是对象 `{"text": ...}`，传字符串会报 `code=19001` —— `build_alert_payload` 已处理，不要用 bash 拼 JSON。

---

## 9. GitHub Actions 的角色：兜底，不是主调度

- 现状 `daily-summary.yml`（00:17 UTC）继续保留，作为 **VPS 故障时的兜底**——它只跑新闻管道子集（无 wxmp/Twitter/Playwright），VPS 挂了至少日报还有。
- 不要在 Actions 里跑 collector：常驻进程 + 30 天登录态 + 随机间隔不适合 CI 的一次性模型。
- VPS 与 CI 同时产出时，gh-pages 是每日覆盖写，幂等，不冲突。

---

## 10. 部署后验证清单

- [ ] `docker compose build` 通过（含去掉 `COPY data` 后镜像不含本机数据）
- [ ] `docker compose up -d collector` 后 `docker compose logs collector` 正常循环
- [ ] `docker compose run --rm horizon horizon-wxmp status` 显示已登录
- [ ] `docker compose run --rm horizon horizon --hours 48` 新闻管道成功（微信走中间表）
- [ ] `docker compose run --rm horizon horizon-reports` 成功
- [ ] `docker compose run --rm horizon horizon-papers` 成功
- [ ] `bash scripts/run_all_pipelines.sh` 全通过，gh-pages 更新
- [ ] `sqlite3 data/horizon.db "PRAGMA journal_mode;"` 返回 `wal`
- [ ] 备份脚本跑一次，`/var/backups/horizon/` 有库 + 资产
- [ ] 恢复演练通过（7.3）
- [ ] crontab 挂上后第二天查 `data/pipeline.log` 与 `data/backup.log`
- [ ] `docker compose run --rm horizon horizon-auth-check --dry-run` 显示已登录
- [ ] 故障演练：`horizon-auth-check --simulate-failure`（或清空 `data/auth/weread.json`）收到 webhook 告警；再跑一次命中 24h cooldown 不重复发
- [ ] 故障演练：改错 API Key 跑一次管道，观察 webhook 告警

---

## 11. 运营成本估算

| 项目 | 月费用 |
|------|--------|
| VPS（Hetzner CX22 / 阿里云 2C2G） | ~¥40-50 |
| LLM API（DeepSeek 为主） | ~¥10-30 |
| 对象存储/异地备份（可选） | ~¥5 |
| **合计** | **¥55-85/月** |

---

## 12. 未纳入 / 后续

- **horizon-api**：要交互式搜索/收藏才部署（Node 构建前端 + 常驻容器 + 端口）。单用户静态站够用。
- **监控面板**：Uptime Kuma 查 collector 存活 + 管道 cron 心跳。
- **登录态自动续期**：we_read 30 天过期是通道侧限制，需扫码续期；后续可考虑过期前 webhook 提醒。
- **多机/多用户**：到时才需要评估换 Postgres —— 现在不是。

---

*文档版本：v2.0*
*最后更新：2026-08-17*
