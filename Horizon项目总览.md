# Horizon 项目总览

> 一句话：Horizon 是一套 **AI 驱动的信息聚合与筛选系统** —— 从数十个信息源抓取原始内容，由 AI 理解语义、判断重要性、消除冗余、补充背景，最终输出高质量、有深度的个性化简报。

## 1. 项目定位

- **愿景**：让每个人拥有自己的 AI 信息雷达，用户只读结果，不筛噪音。
- **形态**：Python（uv 包管理）+ React 前端的完整技术栈，同时输出 Markdown 日报、GitHub Pages 站点、邮件简报、webhook 通知（飞书 / Slack / Discord 等）以及可查询的 API / 前端。
- **数据管线**：核心是一条「抓取 → 去重 → AI 评分 → 过滤 → 语义去重 → 均衡消化 → 富化 → 生成简报」的线性流水线。

## 2. 三大独立子系统

Horizon 由三条相互独立、共用 SQLite 与前端壳的管线组成：

| 子系统 | 目录 | 入口 CLI | 说明 |
|---|---|---|---|
| **新闻管道** | `src/`（`orchestrator.py`） | `uv run horizon` | 核心能力：多源抓取 + AI 评分 + 富化 + 每日中英双语简报 |
| **论文库** | `src/papers/` | `uv run horizon-papers` | 独立学术论文管线（OpenAlex / arXiv 每周精选），不经过 AI 分析器 |
| **报告库** | `src/reports/` | `uv run horizon-reports` | 独立研究机构报告管线（AliResearch、Aliyunreports、FxBaogao、微信公众号报告源），自动下载 PDF 并本地服务 |

另有微信相关独立组件：

- `src/scrapers/wxmp.py` —— 微信公众号抓取（新闻管道源之一）。
- `src/we_read/` —— 微信读书（WeRead）扫码登录 + 数据抓取，独立子模块。
- `wechat-collector/` —— 独立的微信抓取调试 collector 脚本。

## 3. 技术栈

- **后端**：Python ≥3.11，`uv` 管理依赖与脚本入口。
- **AI**：`anthropic` / `openai` / `google-genai` SDK，支持 Anthropic、OpenAI、阿里通义（DashScope）、DeepSeek、豆包、MiniMax、Gemini、Azure OpenAI、Ollama 等多种提供商，支持多提供商故障转移（Chained AI Client）。
- **数据抓取**：`httpx`（异步）、`feedparser`（RSS）、`playwright`（微信 / Twitter 等反爬场景）、`trafilatura`（正文提取）、`ddgs`（DuckDuckGo 搜索富化）。
- **存储**：SQLite（`HorizonDB`，含 FTS5 全文索引）。
- **API**：FastAPI + uvicorn，同时提供 JSON REST API 与 Jinja2 服务端渲染回退页。
- **前端**：Vite + React 19 + TypeScript + Tailwind v4 + react-router（HashRouter），独立 npm 项目。
- **MCP**：基于 `mcp` SDK 的服务器，将 pipeline 各步骤暴露为 AI 助手可调用的工具。
- **部署**：Docker / docker-compose、GitHub Actions CI/CD（GitHub Pages）。

## 4. 新闻管道架构

`src/orchestrator.py` 按顺序协调以下阶段：

1. **Fetch** —— 所有启用的 scraper 通过共享的 `httpx.AsyncClient` 并发抓取（`src/scrapers/`，每源一个）。
2. **跨源 URL 去重** —— 归一化 URL 后合并元数据，保留信息最丰富的一条（`src/dedup.py`）。
3. **AI 评分** —— `ContentAnalyzer.analyze_batch()` 对每条内容打分（0–10）、给出理由、摘要与标签。
4. **阈值过滤** —— 保留 `ai_score >= threshold` 的条目，按分降序。
5. **AI 主题去重** —— 语义识别同一话题的多条来源，合并为一条并保留溯源。
6. **Twitter 讨论扩展**（可选）—— 二级回复抓取 + 重新分析。
7. **均衡消化** —— 按类别配额 + 全局上限裁剪，避免单一话题淹没（`src/filtering.py`）。
8. **富化 Enrich** —— AI 提取需解释的概念 → 联网搜索 → 生成有依据的背景、详细摘要与社区讨论（中英双语，失败时降级为轻量翻译）。
9. **Summarize** —— 渲染 Markdown 日报（含目录），存 `data/summaries/`，复制到 `docs/_posts/` 供 GitHub Pages，并触发邮件 / webhook 推送。

### Scraper 模式

所有 scraper 继承 `BaseScraper`（`src/scrapers/base.py`），实现单一异步方法 `fetch(since: datetime) -> List[ContentItem]`，构造时接收 `(config, http_client)`，ID 形如 `{source_type}:{subtype}:{native_id}`。当前源包括：Hacker News、RSS、Reddit、Telegram、Twitter/X、GitHub、OpenBB、GDELT、Google News、华为新闻、OSS Insight、字节种子（Seed）、微信公众号等。

### AI 提供商抽象

`src/ai/client.py` 的 `create_ai_client(config) -> AIClient` 工厂按配置返回各客户端，统一 `complete()` 接口；`ChainedAIClient` 按逗号分隔的 `provider_chain` 逐个尝试，遇限流 / 鉴权 / 配额 / 服务不可用自动切换。

## 5. 数据模型与配置

- **`src/models.py`** —— Pydantic v2：`Config` 及全套子配置（`AIConfig`、`SourcesConfig`、`PapersConfig`、`ReportsConfig`、`FilteringConfig`、`EmailConfig`、`WebhookConfig`）与统一 `ContentItem`。
- **`src/config/constants.py`** —— 所有可调参数（AI 提供商默认模型、API 密钥环境变量名）集中于此，改参数只需改这一个文件。
- **配置来源** —— `data/config.py`（Python 常量配置）为主；`data/config.json` 兼容旧格式，由 `StorageManager` 加载并展开 `${VAR_NAME}` 引用，密钥一律放 `.env`。
- 论文与报告各有独立模型：`src/papers/models.py`、`src/reports/models.py`。

## 6. 查询 API 与前端

- **SQLite 持久化**（`src/storage/db.py`）：`items` 表 + FTS5 全文索引，`topics` / `news_topics` 主题分组，`user_item_state`（收藏）、`user_topic_prefs`（订阅/屏蔽）按浏览器 ID 隔离。
- **REST API**（`src/api/server.py`，入口 `horizon-api`）：`/api/items`、`/api/topics`、`/api/daily/*`、`/api/search`、`/api/papers`、`/api/reports`、收藏 / 主题偏好等；`/debug` 提供静态调试面板。
- **前端**（`frontend/`）：HashRouter 路由 —— 首页、每日列表 / 详情、条目详情、主题列表 / 详情、收藏、偏好设置、搜索、论文列表 / 详情、报告列表 / 详情。收藏与主题偏好通过 `X-User-Id` 请求头实现无登录机制。
- **设计系统**：卡片使用 `.glass` 毛玻璃样式，颜色全部走 CSS 变量 token（`--ink` / `--muted` / `--accent` / `--line` / `--bg` / `--card`），禁止硬编码 Tailwind 颜色；前端禁止使用 emoji，外部链接用 accent 纯文字。
- **静态导出**：`scripts/export_static_data.py` 将库数据导出为 JSON，供 GitHub Pages 静态展示。

## 7. 关键目录

| 路径 | 用途 |
|---|---|
| `src/scrapers/` | 新闻源抓取器（每源一个文件） |
| `src/ai/` | AI 客户端抽象、分析器、富化器、摘要器、提示词、token 统计 |
| `src/storage/` | 配置加载 / 订阅者管理 / SQLite 持久化 |
| `src/services/` | 邮件（SMTP/IMAP）与 webhook 多平台推送 |
| `src/api/` | FastAPI 查询 API + 服务端渲染回退 UI |
| `src/mcp/` | MCP 服务器（pipeline 工具化）+ 每次运行的中间产物存储 |
| `src/setup/` | 交互式配置向导（`horizon-wizard`） |
| `src/papers/` | 论文管线：模型、抓取器、CLI、源、富化、seed 数据 |
| `src/reports/` | 报告管线：模型、抓取器、CLI、源注册表、综合评分、PDF 下载 |
| `src/we_read/` | 微信读书扫码登录与抓取 |
| `frontend/` | React SPA（Vite + React 19 + TS + Tailwind v4） |
| `debug-frontend/` | `/debug` 静态调试面板 |
| `data/` | 运行时数据：`config.py`、`summaries/`、`subscribers.json`、`horizon.db`、`reports_pdfs/`、`wxmp/` |
| `docs/` | GitHub Pages 站点（Jekyll），`_posts/` 接收生成的日报 |
| `wechat-collector/` | 微信抓取调试 collector |
| `scripts/` | 运维脚本（`daily-run.sh`、静态导出、MCP 检查） |

## 8. 常用命令

```bash
uv sync                       # 安装依赖
uv run horizon                # 默认 24h 新闻管道
uv run horizon --hours 48     # 自定义时间窗
uv run horizon-wizard         # 交互式配置向导
uv run horizon-api            # API 服务，http://localhost:8000
uv run horizon-mcp            # MCP 服务器
uv run horizon-papers         # 论文库
uv run horizon-reports        # 报告库
uv run horizon-wxmp           # 微信抓取 CLI
uv run pytest                 # 全部测试
uv run pytest --cov=src       # 带覆盖率

cd frontend && npm install && npm run dev   # 前端开发（Vite 代理 /api）
cd frontend && npm run build                # 前端构建（tsc -b && vite build）
```

## 9. CI/CD

- `.github/workflows/daily-summary.yml` —— 每日定时（UTC 00:17）+ 手动触发跑 `horizon --hours 24`，部署到 `gh-pages`。
- `.github/workflows/deploy-docs.yml` —— 推送 `docs/**` 时部署 GitHub Pages。
- `.github/workflows/deploy-frontend.yml` —— 前端构建与部署。

## 10. 当前开发状态（截至 2026-08-11）

- **当前分支**：`we-mp-rss-embedded`（已基于 `main`）。
- **进行中**：移除内置的 we-mp-rss 抓取核心（`src/we_mp_rss/` 已标记删除），微信公众号抓取迁移到本地 `wechat-collector` + `wxmp_browser_resolver` 方案，`pyproject.toml` 已将 we-mp-rss 标记为 DEPRECATED。
- **近期方向**：报告库综合分 / AI 关键词 / wxmp 正文清洗、论文库移除 HF 源、列表页排序、主题 scope 隔离（新闻/论文主题分开）、VPS 自动化部署方案（见 `docs/product/horizon-vps-deployment-plan.md`）。
- **产品文档**：完整 PRD 见 `docs/product/PRD_Horizon_AI_News_Radar.md`。

## 11. 相关文档

- `CLAUDE.md` —— 面向 AI 编码助手的项目指南（架构、前端设计系统、命令）。
- `README.md` / `README_zh.md` —— 面向用户的项目介绍与使用说明。
- `docs/` —— GitHub Pages 站点：配置指南、评分机制、scraper 说明等。
- `docs/product/PRD_Horizon_AI_News_Radar.md` —— 产品需求文档。
- `src/mcp/README.md` —— MCP 服务器说明。
