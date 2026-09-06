<div align="center">

# 🌅 Horizon

**你只管读结果，筛噪与精读交给 Horizon。**

AI 驱动的信息聚合平台 —— 聚焦 AI / LLM / 技术领域，新闻 · 论文 · 研究报告三条管道，中文优先

</div>

本项目 fork 自 [Thysrael/Horizon](https://github.com/Thysrael/Horizon)（一个 AI 驱动的新闻雷达开源项目），在此基础上扩展为聚焦 AI / LLM / 技术领域、中文优先的信息聚合平台。Horizon 把散落在海量来源里的高价值内容筛成"值得一读"的中文清单：并发抓取原始内容，由 AI 理解语义、判断重要性、消除冗余、补充背景，最终生成日报，并把经过筛选的新闻、论文、研究报告沉淀进同一个可查询的库，供 Web 站点、邮件、Webhook 消费。

## 特性

- **只做 AI / LLM / 技术内容** —— 新闻管道有硬性的 `ai_relevant` 门；论文与报告各有独立过滤器圈定范围，不做通用新闻
- **AI 打分、程序算总分** —— AI 只给各维度打分，总分由固定公式计算并钳制到 0–10，可复现可审计
- **中文优先** —— 摘要、打分理由、日报、论文解读一律中文，模型名 / 人名 / 方法名等专有名词保留英文原文
- **fail-open** —— AI 是增强手段不是闸门：报告过滤失败保留不误删、HTML 翻译失败回退原文、论文解读单段失败只丢该段，绝不因 AI 故障丢内容
- **跨来源去重** —— 先按 URL、再用 AI 做语义去重，同一件事只留一条并保留多来源溯源
- **背景补全** —— 自动提取陌生概念并联网检索，为重要内容补充背景、细节与社区讨论
- **多 Provider 自由切换** —— Anthropic / OpenAI / Gemini / DeepSeek / 豆包 / MiniMax / Azure / Ollama 及任意 OpenAI 兼容服务，支持故障链回退
- **三种阅读界面** —— Markdown 日报、GitHub Pages 静态站、FastAPI + React SPA（含收藏 / 屏蔽 / 话题偏好 / 跨库搜索）

## 三大管道

| 管道 | 目录 | CLI 入口 | 内容 |
|---|---|---|---|
| 新闻聚合 | `src/` | `uv run horizon` | Hacker News / RSS / Reddit / Telegram / Twitter / GitHub / GDELT / Google News / 微信公众号 等 → 日报 |
| 论文库 | `src/papers/` | `uv run horizon-papers` | OpenAlex 经典论文 + arXiv 每周精选，AI 四维打分、三段式解读并译成中文 |
| 报告库 | `src/reports/` | `uv run horizon-reports` | 阿里云 / 微信公众号 / fxbaogao 等研究报告，exemplar 过滤、正文清洗、尽力下载 PDF |

三条管道**刻意解耦**：论文与报告永远不走新闻打分器，避免 AI 口径互相污染；它们共享同一个 SQLite（`data/horizon.db`）与查询层。

### 新闻管道：四道关卡

1. **相关性门** —— AI 先判定是否 AI / LLM 相关内容，不是的直接丢弃，连加分机会都没有
2. **打分** —— AI 给六正四负十个维度打分（来源权威性 / 新颖度 / 技术含量 / 真实影响力 / 社区验证 / 内容完整度，扣营销味、重复、内容单薄、AI 相关性弱），总分过默认 7 分才进日报，够格不足则按分回填补足
3. **去重** —— 先按 URL、再按语义合并同一话题的多条来源，并保留多源溯源
4. **均衡与上限** —— 全局上限 30 条；仅在回填降格补位时才启用来源配额，防止单一类别刷屏，被挤掉的都记录原因

日报由**纯程序化渲染**（不调 LLM），落 `data/summaries/` 并同步到 `docs/_posts/`（GitHub Pages），同时触发邮件 / Webhook 分发。

### 论文库：两条腿

- **经典论文**：按人工种子清单直接入库，不打分，保证地基
- **每周精选**：arXiv 先规则过滤（撤稿 / 摘要过短 / 关键词黑名单），再让 AI 从创新性、技术质量、影响潜力、相关性四维打分，只挑顶尖若干篇；精选论文生成三段式解读（概览 / 方法 / 评估）并翻译成中文，单段失败只丢该段

### 报告库：给范例不给规则

筛选不给 AI 一堆规则，而是给三份标杆报告作为 exemplar，让它判断新报告是否同类；1–5 分、4 分以上保留，评估失败 fail-open 宁可保留也不误删。筛出的报告做 AI 关键词提取、正文清洗、尽力拿 PDF（含从微信"阅读原文"解析），并用综合分（AI 相关度 × 篇幅）排序。

## 快速开始

### 1. 依赖与配置

```bash
uv sync                     # 安装依赖（Python ≥ 3.11 + uv）
uv sync --extra dev         # 测试/开发依赖（pytest）
cp .env.example .env        # 填入你的 API 密钥
```

主配置是仓库自带的 **`data/config.py`**（Python 文件，支持注释、`os.getenv`、`${VAR}` 引用），直接编辑它即可自定义来源、阈值、模型与分发方式；密钥永远只写 `.env`，配置里只填 `api_key_env` 环境变量名。

需要交互式生成/调整配置时用：

```bash
uv run horizon-wizard
```

### 2. 跑新闻日报

```bash
uv run horizon                  # 默认窗口：昨天 00:00 UTC 起 24h
uv run horizon --hours 48       # 自定义时间窗
uv run horizon --date YYYY-MM-DD # 按日期回填
uv run horizon --live-wxmp      # 微信强制实时抓取（跳过 collector 中间表，诊断用）
```

日报生成在 `data/summaries/`。配置里开启邮件 / Webhook 后会自动推送。

### 3. 论文与报告

```bash
uv run horizon-papers                       # 论文库：默认只跑 arXiv 每周精选
uv run horizon-papers --source openalex     # 单独刷新经典论文
uv run horizon-papers --source all          # 经典 + 精选全跑
uv run horizon-papers --dry-run             # 只出匹配报告，不写库

uv run horizon-reports                      # 报告库
uv run horizon-reports backfill-pdfs        # 给库内报告补下载 PDF
uv run horizon-reports backfill-composite   # 重算综合分（不调 LLM）
uv run horizon-reports extract-keywords     # 回填 AI 关键词
```

### 4. 微信公众号（we_read 纯 HTTP 通道）

公众号文章经 `src/we_read` 纯 HTTP 通道抓取（转发服务，无需 Playwright）：

```bash
uv run horizon-wxmp login              # 扫微信二维码登录（token 存 data/auth/weread.json）
uv run horizon-wxmp status             # 查看登录态
uv run horizon-wxmp subscribe <share-link>  # 从分享链接解析公众号并订阅
uv run horizon-wxmp migrate            # 批量迁移 feed 列表
```

另有**独立采集 daemon** `horizon-wxmp-collector`：每号随机 4–8h 间隔抓公众号 → 中间表 `wxmp_articles`，新闻 / 报告两条管道只读消费，抓取与消费解耦：

```bash
uv run horizon-wxmp-collector                  # 常驻采集
uv run horizon-wxmp-collector once             # 单轮全量后退出（手动补抓 / CI）
uv run horizon-wxmp-collector once --feed 机器之心   # 只抓指定公众号
uv run horizon-wxmp-collector status           # 查看每号下次计划 / 中间表计数
uv run horizon-wxmp-collector reset-news --run-date YYYY-MM-DD  # 崩溃重跑清某天消费标记
uv run horizon-wxmp-collector prune --retention-days 60        # 清理已消费的过期中间表
```

### 5. 查询 API 与前端

```bash
uv run horizon-api               # FastAPI，http://localhost:8000，热重载
cd frontend && npm install && npm run dev    # Vite dev（代理 /api → 8000）
cd frontend && npm run build                 # tsc -b && vite build
cd frontend && npm run lint                  # oxlint
```

### 6. Docker

```bash
docker compose run --rm horizon               # 跑新闻管道
docker compose run --rm horizon --hours 48
```

## 架构

一条主线：**抓 → 筛 → 读 → 送**。三条管道各自演绎，落到同一个查询层：

```
新闻管道   src/orchestrator.py + src/scrapers/* + src/ai/{analyzer,enricher,summarizer}
论文库     src/papers/（fetcher / weekly / sources/*）
报告库     src/reports/（fetcher / filter / sources/*）
        └──────────────┬───────────────┬──────────────┘
              src/storage/db.py —— 单一 SQLite：data/horizon.db
                        │
        src/api/server.py ── JSON API ── frontend/（React SPA）
```

新闻管道内部阶段：并发抓取 → 范围过滤 → 正文抽取 → URL 去重 → 恢复历史翻译 → **AI 十维打分** → 预过滤持久化 → 相关性门 → 阈值 + 回填 → 语义话题去重 → 来源归因 + 多源加分 → 话题分类 → 均衡摘要 → 富化（概念提取 → 联网搜索 → 双语增强 → 中文 HTML 翻译）→ 渲染日报 → 落库分发。

| 栈 | 选型 |
|---|---|
| 后端 | Python 3.11+ · asyncio + httpx · Pydantic v2 · SQLite（含 FTS5 trigram 全文索引） |
| 数据抓取 | httpx · feedparser · trafilatura（正文提取）· Playwright（微信登录 / Twitter / PDF） |
| AI | 多 provider 抽象（Anthropic / OpenAI 兼容 / Azure / Gemini / 链式回退） |
| 查询 API | FastAPI + uvicorn，Jinja2 服务端渲染兜底页 |
| 前端 | Vite + React 19 + TypeScript + Tailwind v4 + react-router（HashRouter） |
| MCP | `src/mcp/`：把 pipeline 各步骤暴露为 AI 助手可调用的工具 |
| 部署 | Docker / docker-compose · GitHub Actions（Pages / 前端） |

## 测试

```bash
uv run pytest              # 全部
uv run pytest tests/test_rss.py
uv run pytest -k "test_name"
uv run pytest --cov=src    # 带覆盖率
```

前端无测试套件，改动以 `npm run build` + `npm run lint` 验证。

## CI/CD

- `.github/workflows/daily-summary.yml` —— 每日定时（UTC 00:17）+ 手动触发跑 `horizon --hours 24`，部署到 `gh-pages`
- `.github/workflows/deploy-docs.yml` —— 推送 `docs/**` 时部署 GitHub Pages
- `.github/workflows/deploy-frontend.yml` —— 前端构建与部署

CI 中 `CI=true` 自动关闭依赖本地服务的源（微信登录态等）。

## 文档

| 文档 | 内容 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 面向编码助手/协作者的项目指南（架构、评分原则、AI 调用纪律、前端设计系统、全部命令） |
| [Horizon 项目总览](Horizon%E9%A1%B9%E7%9B%AE%E6%80%BB%E8%A7%88.md) | 更详细的中文技术总览（子模块、数据模型、目录、命令） |
| docs/configuration.md | 配置指南（AI 提供商、来源、过滤、邮件、Webhook、Pages、MCP） |
| docs/scoring.md / docs/scrapers.md | 评分机制 / 抓取器扩展说明 |
| docs/product/PRD_Horizon_AI_News_Radar.md | 产品需求文档 |
| docs/product/horizon-aliyun-deployment-plan.md | 阿里云部署执行手册 |
| src/mcp/README.md | MCP 工具说明与客户端接入 |


## License

[MIT](LICENSE)