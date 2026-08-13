# CLAUDE.md

本文件为 Claude Code(及任何协作者)在 Horizon 仓库工作时提供项目约定。**改代码前先读本文件**,尤其是第 7 节前端设计系统与第 6 节 AI 调用原则——违反这两处约定会被立刻打回。

---

## 1. Project Overview — 项目定位、用户、目标

**定位**:一个 AI 驱动的信息聚合平台,聚焦 **AI/LLM/技术** 领域,而非通用新闻。它把散落在海量来源里的高价值内容(资讯、论文、研究报告)筛出来、翻译成中文、做成可读的产品。

**用户**:以中文读者为主(个人/小团队使用)。默认输出语言为简体中文,前端、日报、论文解读、报告正文清洗全部面向中文消费。

**三条独立管道 + 查询层**:

| 管道 | CLI 入口 | 内容 | 与新闻管线的耦合 |
|---|---|---|---|
| 新闻聚合 | `horizon` | HN / RSS / Reddit / Telegram / Twitter / GitHub / GDELT / Google News / 微信公众号等 → 打分 → 增强 → 日报 | — |
| 论文库 | `horizon-papers` | OpenAlex 经典论文 + arXiv 每周精选 | **刻意解耦**,只复用 `AIClient`/`parse_json_response`/`complete_with_retry` |
| 研究报告库 | `horizon-reports` | 阿里云报告 / 微信公号报告 / 领研网等 | **刻意解耦**,`ReportFilter` 独立 AI 评估 |
| 查询层 | `horizon-api` + React SPA | FastAPI JSON API + `frontend/` 前端 | 消费上面三条管道的 SQLite 数据 |

**目标**:
- 自动从多来源抓取 → 用 AI 把"真正值得读的 AI 内容"筛出来,而非照单全收
- 双语文档能力:第一遍打分强制中文 summary,增强阶段输出 en/zh 成对字段(当前只渲染 zh)
- 三条管道共享一个 SQLite 库、一个查询 API、一个前端,但 AI 流程各自独立,互不污染
- 输出渠道:GitHub Pages 静态站、邮件订阅、Webhook(钉钉/飞书/Slack/Discord)、以及查询 API + 前端

---

## 2. Product Principles — 产品决策、评分原则

### 产品决策

- **内容范围**:只做 AI/LLM/技术内容。新闻管道有硬性的 `ai_relevant` 门(只有 AI/LLM 内容通过);论文/报告管道通过各自过滤器(关键词白名单、`ReportFilter` 的 exemplar 评估)圈定范围。
- **三管道解耦是刻意为之**:论文和报告**永远不走**新闻管道的 `ContentAnalyzer`/`ContentEnricher`,避免 AI 打分口径互相污染。复用的最小集只有 `AIClient`、`parse_json_response`、`complete_with_retry`。
- **无账号系统**:前端用浏览器生成的匿名 `X-User-Id` 实现收藏/屏蔽,后端把 `user_id` 当不透明字符串,不校验不解释。缺省请求行为与无此功能时完全一致。
- **fail-open 原则**:AI 是增强手段不是闸门。报告 `ReportFilter` AI 异常时**保留报告且不写回分数**;日报 HTML 翻译失败时**静默保留原文 HTML**(前端回退),绝不因 AI 失败而丢内容。
- **AI 只打分、不算分**:所有总分由程序用固定公式计算(保证一致、可审计),AI 只给各维度打分或给出结构化中间量。
- **中文优先的双语策略**:关键词/摘要/理由默认中文,专有名词(模型名、人名、方法名)保留英文原文;前端与外部链接严禁 emoji。
- **迁移优先保数据**:DB 迁移全部幂等、在连接时执行;`data/horizon.db.bak-*` 备份文件不清理(目前有多个 166MB 的迁移备份)。

### 评分原则(新闻管道)

1. **相关性门** `ai_relevant`:第一遍分析 AI 判定是否 AI/LLM 相关内容,`False` 直接丢弃(计入 `drop_reason="relevance"`),**不做任何加分**。
2. **AI 十维打分 → 程序算总分**:AI 给 6 个正向维度(source_authority 0-1、novelty 0-2、technical_substance 0-3、real_world_impact 0-2、community_validation 0-1、content_completeness 0-1,正向满分 10)+ 4 个扣分项(marketing/duplicate/thin_content/weak_ai_relevance 各 0 到 -2,合计 -8);`score = 正向和 + 扣分和`,钳制到 `[0, 10]`。各维度存入 `metadata.score_breakdown` 供审查 UI。
3. **阈值 + 回填**:`ai_score >= filtering.ai_score_threshold`(默认 7.0)才进摘要;若通过项不足 `max_items`(默认 30),按分数回填最高分的未达标项,凑满配额。
4. **平衡摘要** `apply_balanced_digest`:先按分数降序全局 `max_items` 截断;**来源类型配额(`filtering.category_groups`)仅在发生过回填时才启用**(orchestrator 传 `enable_group_quotas=backfilled`,正常路径不限制来源构成);被配额挤掉的项记 `drop_reason="category_quota"`。
5. **语义话题去重** `merge_topic_duplicates`:AI 把讲同一件事的多条合成一条,被并入项记 `drop_reason="topic_duplicate"`。
6. **多源独立验证加分** `apply_multi_source_bonus`:同一条内容被 3+ 独立来源证实时加分(必须在来源归因和重分析之后跑)。
7. **来源权威性排序** `SOURCE_ROLE_PRIORITY`:合并多条同内容来源时,按官方公司博客(1)…聚合器(9)/未知(10)选主来源,`ROLE_DOMAIN_MAP` 把域名映射到角色。

### 评分原则(报告 / 论文)

- **报告** `ReportFilter`:exemplar-based 评估(系统 prompt 给 3 份标杆报告样本,让 AI 判断候选是否同类,而非规则清单),输出 `ai_relevance_score`(1-5);**score >= 4 才保留**;AI 失败 fail-open 保留、不写回分数。
- **报告综合分** `composite_score` = 0.5 × (ai_relevance/5) + 0.5 × `min(1, chars/15000)`;正文 <1000 字符时用 `pypdf` 读本地 PDF 数页。**仅供前端排序,永不展示**。
- **论文 arXiv weekly**:规则过滤(撤稿/短摘要/关键词黑名单/venue 信号排序)→ AI 粗筛四维打分(innovation / technical_quality / impact_potential / relevance,overall 0-10)→ top N 精选。经典 openalex 源**不打分**(人工种子列表)。

---

## 3. Architecture — 技术架构

### 技术栈

- **后端**:Python 3.11+,asyncio + `httpx`,Pydantic v2 全部数据模型,SQLite 持久化,`uv` 包管理
- **AI**:多 provider 抽象(Anthropic / OpenAI 兼容 / Azure / Gemini / provider 链回退),OpenAI 兼容一家覆盖 ali/deepseek/doubao/minimax/ollama
- **API**:FastAPI + uvicorn(`horizon-api`),另有 Jinja2 服务端渲染兜底页 + `/debug` 静态诊断面板
- **前端**:React 19 + Vite + TypeScript + Tailwind v4 + react-router,独立 npm 工程(`frontend/`)
- **抓取**:`httpx` 为主;Playwright 用于需 JS 渲染/登录态的场景(Twitter、华为新闻、阿里云报告、微信报告 PDF 解析)

### 三大管道示意

```
新闻管道   src/orchestrator.py + src/scrapers/* + src/ai/{analyzer,enricher,summarizer}
论文库     src/papers/{cli,fetcher,weekly,sources/*}        (经典 + arXiv weekly)
研究报告库  src/reports/{cli,fetcher,filter,sources/*}       (两阶段 + AI 过滤 + PDF)
        └──────────────┬───────────────┬──────────────┘
              src/storage/db.py (单一 data/horizon.db)
                        │
        src/api/server.py ── JSON API ── frontend/ (React SPA)
```

### 目录结构

| 路径 | 用途 |
|---|---|
| `src/orchestrator.py` | 新闻管道编排(阶段序列见第 4 节) |
| `src/scrapers/` | 新闻源抓取器(每源一个,继承 `BaseScraper`);`wxmp.py` = 微信公号(走 `src.we_read`) |
| `src/ai/` | AI 抽象:client / analyzer / enricher / summarizer / prompts / tokens |
| `src/content_extractor.py` | 正文抽取(`trafilatura`)+ `sanitize_article_html` 清洗(新闻与报告共用) |
| `src/dedup.py` | URL 去重、AI 语义话题去重、来源归因、多源加分 |
| `src/filtering.py` | 平衡摘要(配额 + 上限) |
| `src/seed_topics.py` | 新闻话题 taxonomy 种子数据 |
| `src/storage/` | 配置加载(`manager.py`)、SQLite(`db.py`) |
| `src/reports/` | 报告库:models / cli / fetcher / filter / scoring / sources/* / wxmp_browser_resolver / pdf / pdf_downloader |
| `src/papers/` | 论文库:models / cli / fetcher / weekly / sources/* / topics / seed_data |
| `src/we_read/` | **微信抓取通道**:纯 HTTP 客户端(weread.111965.xyz 转发服务),登录态 token 存 `data/auth/weread.json`。**本包不 import 任何 wxmp scraper 业务代码,以便通道故障时只换 `src/we_read/`** |
| `src/api/` | FastAPI 查询 API + Jinja2 兜底页 + `/debug` |
| `src/mcp/` | MCP server(把管道步骤暴露为工具)+ per-run 工件存储 |
| `src/services/` | 邮件(SMTP/IMAP 订阅)与 Webhook(钉钉/飞书/Slack/Discord) |
| `src/config/` | `constants.py`(供应商默认值/来源角色映射/域名映射)+ `pyconfig_editor.py`(改 `data/config.py`) |
| `frontend/` | React SPA(独立 npm 工程) |
| `data/` | **运行时数据**:`config.py`(主配置)、`horizon.db`、`summaries/`、`auth/`、`wxmp/`、`reports_pdfs/` |
| `wechat-collector/` | 微信调试工具(⚠️ 仍 import 已删除的 `src.we_mp_rss`,见第 10 节) |
| `scripts/export_static_data.py` | 导出静态 JSON 到 GitHub Pages |
| `debug-frontend/` | 静态诊断面板(`/debug`) |

### 配置系统

- **主配置是 `data/config.py`(Python 文件)**,不是 JSON:支持 `#` 注释、`os.getenv`、`datetime.now` 等动态值。`StorageManager.load_config()` 先找 `data/config.py`,找不到再回退 JSON(`app.json`+`sources.json`+`scoring.json` 合并,`config.json` 覆盖)。
- 任意字符串值里的 `${VAR}` 引用在 Pydantic 校验前统一展开(未设置的变量**原样保留**,让它作为清晰的下游错误冒出来,而不是静默空串)。
- **密钥永远不进 config 文件**:走 `.env`,配置里只写 `api_key_env`(环境变量名)。CI 中 `CI=true` 自动关闭依赖本地服务的源(微信登录态等)。
- 改配置就改 `data/config.py`;`src/config/constants.py` 集中所有代码常量(供应商默认模型/API 地址/来源角色优先级/域名映射)。

### 查询 API 与前端

- `GET /api/*`:items、daily、topics、search、stats、papers、reports、favorites、topic-prefs、global-search(跨三库全文)。服务器渲染兜底页在 `/`、`/topics`;`/debug` 是静态诊断面板。
- 前端路由全部走 `HashRouter`(`frontend/`):`/`、`/daily`、`/topics`、`/search`、`/favorites`、`/papers`、`/reports`、`/preferences` 等。
- 收藏/屏蔽:前端生成匿名 `X-User-Id` 头,后端按 id 隔离状态(见第 5 节 user 表);服务端渲染页无此机制,刻意不在范围内。

---

## 4. Pipeline — 数据处理流程

### 新闻管道(`src/orchestrator.py`,线性阶段)

1. **时间窗口**:`refetch_date`(UTC 整天)优先,否则 `force_hours`,默认"昨天 00:00 UTC – 今天 00:00 UTC"。
2. **并发抓取**:所有启用源经 `asyncio.gather` + 共享 `httpx.AsyncClient`(timeout 30s)并发抓取,`return_exceptions=True` 单源失败不拖垮整批。
3. **范围过滤**:`until` 存在时丢弃窗口外条目。
4. **正文抽取**:`extract_full_content_batch`(`trafilatura`),跳过社交/代码托管域与过短响应。
5. **URL 去重** `merge_cross_source_duplicates`:归一化 URL(去 www/尾部斜杠/fragment),合并元数据与正文到最富条目。
6. **恢复历史翻译** `_restore_prior_translations`:把上次持久化的 `display_html_zh` + `display_html_source_hash` 拷回条目,让 enricher 跳过未变更文章的重复 HTML 翻译。
7. **AI 分析打分** `_analyze_content`(`ContentAnalyzer.analyze_batch`):十维打分 + 中文 summary + tags(见第 6 节)。
8. **预过滤持久化**:**所有**已打分条目先落库 `selected=False`(含将被丢弃的),供事后审计;随后 `mark_selected` 写 `selected`/`drop_reason`(取值 `relevance` / `score` / `topic_duplicate` / `category_quota`)。
9. **相关性门** `ai_relevant=True` → **阈值+回填** → **语义话题去重** → **来源归因 + 多源加分** → **Twitter 讨论扩展**(可选,回拉回复再重分析)→ **话题分类**(`classify_topics`,news scope 话题,内容形态兜底"行业动态")→ **平衡摘要**。
10. **增强** `_enrich_content`(`ContentEnricher.enrich_batch`):概念提取 → DuckDuckGo 搜索(并发,`asyncio.to_thread`)→ 双语增强生成 → HTML 中文翻译(失败回退原文)。
11. **落库 topics + 更新 items**:`save_news_topics`(分类结果存 `news_topics`,不塞进 `metadata_json`)→ `save_items(selected=True, replace=False)`。
12. **生成日报**(每个 `ai.languages`):`DailySummarizer`(纯程序化渲染 Markdown,不调 LLM)→ 存 `data/summaries/` → 复制到 `docs/_posts/`(GitHub Pages)→ 邮件 + Webhook。
13. **Token 用量汇总**:`get_usage_snapshot()` 打印各 provider token。

### 论文库(`src/papers/`)

- **经典 openalex 源**:按人工种子列表(`src/papers/seed_data.py`,DOI/arXiv-id/标题年份作者匹配)→ 匹配报告(`matched`/`manual_review`/`unmatched` × `complete`/`partial`/`rate_limited`/`failed`)→ 增强(多源元数据合并,`canonical_*` 永远覆盖 API 值)→ `save_papers`(按 id upsert)。**不打分**。
- **arXiv 每周精选**(`src/papers/weekly.py`):按分类抓最新(`fetch_recent`,按 `window_days` 回看)→ 规则过滤(`exclude_withdrawn → reject_short_abstracts → keyword 白/黑名单 → github 提取 → venue 信号排序 → truncate` 到 `target_candidates`)→ AI 粗筛四维打分 → 取 `featured_count` top N(`is_featured` + `featured_date`)→ 三段式解读(overview/method/evaluation,单段 ≤4096 token,失败只丢该段)→ 翻译(title/abstract → 中文)→ `save_papers`。失败记录写 `data/papers_failed_list.md`。
- AI+金融子板块:同一次 `fetch_recent` 按 `finance_categories`(q-fin.*)拆分,各自独立精选(`source=arxiv_fin`)。

### 研究报告库(`src/reports/`)

- **两阶段抓取**:`fetch_native_ids`(列源内 id)→ `fetch_detail`(逐条补全)。源注册在 `fetcher._SOURCE_REGISTRY`(aliyunreports / wxmp / fxbaogao / aliresearch)。
- **wxmp 源**:`fetch_native_ids` 阶段经 `src.we_read` 抓文章并缓存,`fetch_detail` 从缓存出 `Report`(应用微信正文清洗、去微信页脚噪音,`_WEIXIN_CONTENT_END_MARKERS` 截断);`pdf_urls` 留给浏览器解析器补。
- **AI 过滤** `ReportFilter`:exemplar 评估,`ai_relevance_score`(1-5)写回,`>=4` 保留;`skip_ai_filter=True` 的源(如精选文章)跳过。
- **PDF 两套并存**:`pdf_downloader.py`(通用 HTTP 直下,CDN/公开 URL)+ `pdf.py`(Playwright 会话下载,保留 cookies/CSRF),落盘 `data/reports_pdfs/{source}/{native_id}/`;`wxmp_browser_resolver.py` 用 Playwright 开文章找"阅读原文"/解码二维码拿 PDF。
- **关键词**:`extract_report_keywords` AI 提取 5-8 个(中文为主,专有名词保留英文)。
- **综合分** `compute_composite_score`(见第 2 节)→ `save_reports`(按 id upsert)。CLI 另有 `backfill-pdfs`、`backfill-composite`、`extract-keywords`。

---

## 5. Database — 数据模型

**单一 SQLite 文件 `data/horizon.db`**(约 175MB),新闻/论文/报告/用户状态全部共存,**无分库**。`HorizonDB(db_path="data/horizon.db")` 无参实例化,`threading.local()` 每线程独立连接(FastAPI sync 端点跑在线程池)。所有调用点(编排器/API/两个 CLI)共用这一个默认路径。

### 表清单

| 表 | 用途 |
|---|---|
| `items` | 新闻条目(**run_date 快照**,见下) |
| `items_fts` | `items` 的 FTS5 外部内容表(**trigram** tokenizer,为中文设计) |
| `daily_runs` | 每日抓取运行汇总(fetched/selected 数、languages) |
| `topics` | 共享话题分类表,news 与 paper 两套 taxonomy 用 **`scope`** 列(`'news'`/`'paper'`)隔离,`UNIQUE(scope, slug)` |
| `news_topics` | 新闻 ↔ 话题 多对多(confidence/reason) |
| `paper_topics` | 论文 ↔ 话题 多对多(整体替换语义) |
| `papers` | 论文(跨 source 累积 upsert) |
| `reports` | 报告(跨 source 累积 upsert) |
| `user_item_state` | 新闻收藏(`state='favorited'`,预留 `'read'` 等) |
| `user_paper_favorites` / `user_report_favorites` | 论文 / 报告收藏 |
| `user_topic_prefs` | 话题偏好(`'subscribed'` / `'blocked'`,互斥) |

### 关键语义

- **`items` 是 run_date 快照**:`save_items(replace=True)` 先 `DELETE ... WHERE run_date=?` 再插入;`replace=False` 走 `COALESCE` 保留提取阶段列,供增量刷新 enrichment。**`papers`/`reports` 是累积 upsert**(按 id 覆盖,可幂等重跑)。
- **搜索**:`items_fts` 用 trigram + 触发器同步(`items_ai/ad/au`);`get_items(search)` 走 `MATCH`(需 ≥3 字符),`search()` 走 `LIKE` 支持任意长度子串。papers/reports **没有 FTS**,用 `LIKE` 匹配 title/abstract/中文翻译列。
- **drop 审计**:`mark_selected` 重置当日全部 `selected`/`drop_reason` 后写幸存者与丢弃原因,配合"预过滤持久化"提供完整审计轨迹。
- **`scope` 隔离**:`get_topics(scope=...)`、`seed_topics(..., scope=...)`;LLM 新闻分类只喂 news scope 话题,防止把新闻分到 paper 专属 slug。
- **报告机构归一化**:入库前 `_first_institution()` 把多机构字符串(`&`/`、`/`,`/`;`)归一为第一个机构;查询端 `_split_institutions()` 拆分计数。

### 迁移机制(易错点)

- **没有版本表 / `PRAGMA user_version` / Alembic**。迁移是**幂等的、按列存在性守卫**的 `ALTER TABLE ADD COLUMN` / 全表重建,在**每条新连接建立时**依次执行:
  - `_migrate_items_table`(补提取阶段列;`category` 首次补齐时从 `metadata_json` 回填)
  - `_migrate_papers_table`(补 arxiv/翻译/featured/AI 分数列;删已退役的 `ai_interpretation_json`)
  - `_migrate_reports_table`(补 raw_html/display_html/keywords/AI 分数/综合分)
  - `_migrate_topics_table`(**唯一一次全表重建**,给 `topics` 加 `scope`、改唯一键为 `(scope,slug)`,事务内执行)
  - `_migrate_fts_tokenizer`(检测 `items_fts` 是否 trigram,旧 `unicode61` 则重建)
- **`PRAGMA foreign_keys` 未开启**:声明了 FOREIGN KEY 但 `ON DELETE CASCADE` 实际**不生效**。
- 不要依赖 `CREATE TABLE IF NOT EXISTS` 之外的自动 schema 演进;加列走列存在性迁移。

---

## 6. AI Components — Prompt、评分、LLM 调用原则

### Provider 抽象(`src/ai/client.py`)

- `AIClient` 唯一抽象方法 `async complete(system, user, temperature?, max_tokens?) -> str`。
- `create_ai_client(config)` 工厂:有 `provider_chain` 则建 `ChainedAIClient`,否则单 provider。
- **OpenAI 兼容一家覆盖 6 家**(openai/ali/deepseek/doubao/minimax/ollama),base_url 三级解析(config → `BASE_URL_ENVS` → `DEFAULT_BASE_URLS`);Ollama 不校验密钥、自动补 `http://`+`/v1`;MiniMax 钳温到 ≥0.01、不强制 `response_format`;模型首调 400 报 temperature 不支持 → 自动降级去掉 temperature 重发。
- **Azure**:`model` 即 deployment 名;模型名前缀命中 o1/o3/o4/gpt-5 用 `max_completion_tokens`,错误文案触发运行时切换。
- **ChainedAIClient**:懒创建(缺后续 provider 密钥不阻塞启动);回退条件 = 429/限流、401/403/quota/exceeded、502/503/service unavailable、空响应;全部失败抛 `RuntimeError`。

### 新闻打分(prompt 与公式)

- `CONTENT_ANALYSIS_SYSTEM` 要求返回 `summary_zh/reason_zh/tags`——**`summary` 强制中文,即使原文是英文**;用户模板实际用 `reason/summary/tags`(analyzer 读这三个)。
- 十维打分公式见第 2 节;AI 只给维度分,**总分由 `_compute_score` 程序计算并钳制 [0,10]**,维度写入 `metadata.score_breakdown`。
- 正文三层优先级 `resolve_content`:`clean_content > raw_content > rss_summary`;只有摘要时给 AI 一条中文 `source_note`,提示"请勿因此判内容单薄而扣分"。

### 增强(prompt 与语言约束)

- `CONTENT_ENRICHMENT_USER`:concept 提取(`CONCEPT_EXTRACTION_*`,≤3 条搜索词)→ DuckDuckGo 搜索 → 双语增强字段 `title/whats_new/why_it_matters/key_details/reason/community_discussion` × `_en`/`_zh`。
- **语言硬约束**:`*_zh` 字段绝不允许用英文写(仅保留 GPT-4/CUDA/Rust 这类专有名词);每个字段至少一个完整句子;`community_discussion` 无评论时可为空。
- 来源引用只接受出现在搜索结果中的 URL(`metadata.enrichment_sources`)。
- 语言检测:title+resolved text 的 CJK 占比 >30% → `zh`;**刻意排除 `ai_summary`**(第一遍 prompt 强制其中文,会污染检测)。

### HTML 中文翻译(`html_translator.py`)

- 分块翻译 `display_html` 的 h2/h3/h4/p/blockquote/li/figcaption 可见文本(块内只允许 strong/em/br),批上限 20 块 / 3000 字符。
- **不信任 AI**:每块 `nh3` 白名单消毒 → 重组后整体 `sanitize_article_html`;任一批次数量不匹配或图片数不一致 → **整个翻译放弃返回 None**(前端回退原文)。
- 按 `display_html_source_hash` 跳过已翻译的相同 HTML;结果 hash 不匹配则丢弃陈旧翻译。

### 日报渲染(`summarizer.py`)

- **纯程序化渲染,不调 LLM**:Markdown 头 + 统计 → TOC(⭐️ score/10)→ 每条(锚点、标题+分数、摘要、来源行、评分理由、讨论、多来源 `source_provenance`)。
- 中文排版用 `_pangu` 在 CJK 与 ASCII 间插空格。

### JSON 输出与容错

- 所有 USER prompt 以"仅返回合法 JSON"结尾,禁 markdown/额外解释;OpenAI 兼容走 `response_format={"type":"json_object"}`,Gemini 走 `response_mime_type="application/json"`,Anthropic 靠 prompt 约束。
- `parse_json_response` 五级容错:直接 `json.loads` → ```json 代码块 → ``` 代码块 → 花括号配平取首个完整对象 → 正则兜底。
- **JSON 解析失败各消费方处理**(都是"宁缺毋滥、不崩整批"):analyzer → 置 `ai_relevant=False, ai_score=0.0, reason="Analysis response parse failed"`;enricher → 降级轻量翻译;html_translator → 放弃返回 None;dedup → 跳过该批去重;ReportFilter → fail-open 保留不写分;papers/reports 关键词 → 字段留空。

### 调用纪律(重试 / 节流 / 并发 / 回退)

- **重试**:analyzer/enricher 单条 `@retry(stop_after_attempt(3), wait=wait_exponential(min=2, max=10))`;papers/reports 用 `complete_with_retry`(默认 retries=2,退避 1.5s);reports 关键词空响应 3 次重试(间隔 2s)。
- **节流**:analyzer `throttle_sec` 条间 `asyncio.sleep`;enricher 不节流,靠并发 + 双信号量。
- **并发**:analyzer `Semaphore(analysis_concurrency)`;enricher `Semaphore(enrichment_concurrency)` + 独立 `Semaphore(max(concurrency,3))` 管 HTML 翻译。
- **单条失败兜底**:analyzer 失败置 `ai_relevant=False` 继续处理其余条目,不中断整批;papers 三段解读单段失败只丢该段字段。

---

## 7. Frontend Design System — UI 规则

**每个新页面/卡片/组件都必须遵循以下模式**,参考实现是 `frontend/src/pages/ItemDetailPage.tsx` + `frontend/src/components/ItemCard.tsx`。

### 颜色 token(严禁硬编码)

永远不要用硬编码的 Tailwind 颜色(`bg-gray-100`、`text-green-600` 等),一律用 `frontend/src/index.css` 里定义的 CSS 变量:

| Token | 值 | 用途 |
|---|---|---|
| `--ink` | `#2f3c50` | 标题 / 正文 |
| `--muted` | `#7d8999` | 元信息 / 次要文字 |
| `--accent` | `#B197C4` | 链接 / 高亮 / 激活态 |
| `--line` | `rgba(208,214,221,.6)` | 边框 / 分隔线 |
| `--bg` | `#f5f7f8` | 页面背景 |
| `--card` | `rgba(255,255,255,.74)` | 卡片底色 |

### 卡片模式

用 `.glass` 类(磨砂玻璃 + 阴影 + hover 抬升),**不要**用裸 `border + rounded`:

```tsx
// ✅ 正确 — glass + news-card
<article className="glass news-card rounded-2xl p-5">
// ❌ 错误 — 裸边框无玻璃效果
<article className="border border-[var(--line)] rounded-lg p-5">
```

### 布局规格

| 场景 | 类 | 说明 |
|---|---|---|
| 页面宽度 | `max-w-[1180px] mx-auto` | 所有详情页 |
| 标题卡片 | `glass news-card rounded-[28px] p-7 mb-6` | 详情页头部 |
| 内容区块 | `glass rounded-[22px] p-6` | 摘要 / 正文块 |
| 小节眉 | `text-[11px] font-bold tracking-[.14em] text-[#8ea0b6] mb-3` | 全大写 eyebrow |
| 正文字体 | `text-[17px] leading-[1.85] text-[var(--ink)]` | 摘要 / 正文段落 |
| 详情页元信息 | `text-sm text-[var(--muted)]` | — |
| 列表卡片元信息 | `text-xs text-[var(--muted)]` | — |
| 卡片标题 | `text-base font-medium text-[var(--ink)]` | 卡片内 `h3` |
| 列表页标题 | `text-[28px] font-normal text-[var(--ink)]` | `h1` |
| 列表副标题 | `text-sm text-[var(--muted)] mb-6` | "N 份报告" 这类 |
| 分类 tag | `text-xs px-2 py-0.5 rounded-full bg-black/[.03] text-[var(--muted)]` | — |
| 话题 tag | `text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/10 text-[var(--accent)]` | — |
| 卡片动作链接 | `text-[var(--accent)] hover:opacity-80 font-medium` | "查看详情 →" |
| 卡片外部链接 | `text-[var(--muted)] hover:text-[var(--ink)]` | "🔗 source" |
| 详情页动作按钮 | `inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-white/60 transition-colors` | — |
| 分隔线 | `hr className="my-8 border-[var(--line)]"` | 区块之间 |

### 硬性约定(易被忽视)

- **前端禁止任何 emoji**(按钮、图标、文案都不得用 emoji/箭头符号)。
- **外部链接是 accent 纯文字**,不加 emoji、不加箭头;只有"查看详情 →"这类动作链接用 accent + 箭头。
- 多个动作按钮时容器用 `flex-wrap`。
- A11y:可交互元素必须是 `<button>` 或 `<a>`,不能用 `<div onClick>`。

### 新页面清单

- [ ] 卡片用 `.glass`(不是裸 border)
- [ ] 颜色只用 CSS 变量 token(绝不 `bg-gray-*`、`text-green-*`)
- [ ] 标题层级匹配上表
- [ ] 详情页 `max-w-[1180px] mx-auto`
- [ ] 多个动作链接用 `flex-wrap`
- [ ] 无 emoji;外部链接纯文字
- [ ] 交互元素是 `<button>`/`<a>`

---

## 8. Development Commands — 命令

```bash
# 安装依赖(uv)
uv sync                    # 基础
uv sync --extra dev        # pytest
uv sync --extra openbb     # OpenBB 财经 SDK(可选)
uv sync --extra twitter    # Playwright Twitter 抓取(可选)

# 三条管道
uv run horizon             # 新闻管道,默认 24h 窗口
uv run horizon --hours 48
uv run horizon-papers            # 论文库,全部启用源
uv run horizon-papers --source openalex    # 单源
uv run horizon-papers --dry-run           # 只出匹配报告,不写库
uv run horizon-reports           # 报告库
uv run horizon-reports backfill-pdfs      # 给库内报告补下载 PDF
uv run horizon-reports backfill-composite # 重算综合分(不调 LLM)
uv run horizon-reports extract-keywords   # 回填 AI 关键词

# 微信抓取(we_read 通道)
uv run horizon-wxmp login    # 扫微信二维码登录(token 存 data/auth/weread.json)
uv run horizon-wxmp status   # 查看登录态
uv run horizon-wxmp subscribe <share-link>  # 从分享链接解析公众号并订阅
uv run horizon-wxmp migrate  # 批量迁移 feed 列表(写 data/config.py)

# API / MCP / 交互式配置
uv run horizon-api           # FastAPI,http://localhost:8000,热重载
uv run horizon-mcp
uv run horizon-wizard        # 交互式配置向导(生成 data/config.py)

# 测试
uv run pytest                # 全部
uv run pytest tests/test_rss.py
uv run pytest -k "test_name"
uv run pytest --cov=src

# Docker
docker compose run --rm horizon
docker compose run --rm horizon --hours 48
```

### 前端(`frontend/`,独立 npm 工程)

```bash
cd frontend
npm install
npm run dev        # Vite dev server,代理 /api → localhost:8000
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

前端无测试套件——改动用 `npm run build` + `npm run lint` 验证。本地开发跑 `horizon-api` + `npm run dev` 配合使用。

### CI/CD

- `.github/workflows/daily-summary.yml`:定时(00:17 UTC)+ 手动触发,跑 `uv run horizon --hours 24`,部署到 `gh-pages`。
- `.github/workflows/deploy-docs.yml`:push 到 `docs/**` 时部署 GitHub Pages。
- CI 中 `CI=true`:`data/config.py` 自动关闭依赖本地服务的源(微信登录态等),避免无谓超时。

---

## 9. Current Status — 当前进度

**当前分支 `we-mp-rss-embedded`,正在做微信抓取通道迁移:we-mp-rss(rachelos/Playwright)→ `src/we_read`(纯 HTTP)。** 该分支领先 `main` 9 个 commit,当前工作树有大量未提交改动。

### 进行中的迁移(未提交改动,git status)

- **微信抓取换通道**:旧的 `src/we_mp_rss/` 整包(36 个文件,含 3 个 JS 反爬脚本)已 staged 删除,改为 `src/we_read/`(9 个文件:client/config/errors/login/model/retry/state/token_store;weread.111965.xyz 转发服务,纯 HTTP,无需 Playwright、无需外部 we-mp-rss 服务)。`pyproject.toml` 标注 `# DEPRECATED — we-mp-rss (rachelos) scraping removed` 并新增 `segno`(登录二维码渲染)。
- **`data/config.py`**:31 条 feed 全部补 `weread_mp_id`(`feed_id` 保留作废弃回退);新增纯 `weread_mp_id` 的"字节跳动Seed";wxmp `enabled=True`、telegram 重新启用。**旧 feed 若缺 `weread_mp_id` 需补,否则抓不到**(`test_feed_without_weread_mp_id_is_skipped` 锁了这个行为)。
- **模型层**:`WxMpSourceConfig.feed_id`/`faker_id` 标记 **DEPRECATED**,新增 `weread_mp_id`(ACTIVE);`WxMpConfig.lic_key`/`max_page`/`gather_interval` 也 DEPRECATED;新增 `WeReadConfigModel`(`base_url` 默认 weread.111965.xyz、request_interval=20、token_max_age_days=30)。
- **CLI**:`horizon-wxmp` 从 `login/status/logout` 扩为 `login/status/logout/subscribe/migrate`;`subscribe` 用 `pyconfig_editor.py` 从分享链接解析公众号并写回 `data/config.py`。
- **前端**:`ReportCard`/`ReportDetailPage` **删除了 wechat_keyword 门控 UI**("关注公众号回复关键词获取 PDF"提示),微信报告只显示文章链接 + PDF 链接。
- **新增测试**:`test_we_read_client.py`(httpx.MockTransport 无网)、`test_we_read_retry.py`、`test_we_read_token_store.py`、`test_wxmp_cli_migrate.py`、`test_wxmp_golden.py`(真实腾讯研究院文章 HTML 清洗黄金锁,fixture 3.1MB)、`test_pyconfig_editor.py`。
- **删除的测试**:`test_wxmp_faker_id.py`、`test_wxmp_init.py`、`test_wxmp_login.py`(staged)、`test_wxmp_keyword_detection.py`(未 staged,关键词门控检测)。
- 登录态存 `data/auth/weread.json`;`src/we_read/login.py` 用 `segno` 本地渲染二维码(`scan_url` 是 open.weixin.qq.com 确认链接,非二维码图片)。

### 最近完成的功能(按提交倒序)

- **报告库**:综合分(`composite_score`,仅排序)、AI 关键词(5-8 个,中文为主)、wxmp 正文清洗(块级提取 + footer 截断)、AI 过滤 exemplar 评估、PDF 下载与浏览器解析。
- **论文库**:移除 HuggingFace 源;arXiv 每周精选管线(规则过滤 → AI 粗筛四维打分 → top N → 三段式解读);解读分三段生成 + 中英搜索 + 经典论文 backfill;arXiv 分类扩 cs.CV/cs.MA/cs.RO。
- **话题**:`topics` 表加 `scope` 隔离新闻/论文两套 taxonomy,主题页回到三大块。
- **微信**:固定 UA 防风控 + 独立微信调试 collector(早期;现已进一步换 we_read 通道)。
- **前端**:论文页搜索替代时间筛选、首页元信息、搜索键盘导航、报告列表页时间/综合排序切换。
- **部署**:VPS 自动化部署方案(`docs/product/horizon-vps-deployment-plan.md`)。

---

## 10. Known Issues — 已知问题

### 迁移遗留(当前分支,需在本分支处理)

- **`wechat-collector/` 调试工具会损坏**:`collector.py`、`ab_test_free_publish.py`、`test_fetch_recent.py` 仍直接 `import src.we_mp_rss`,`src/we_mp_rss/` 删除后这些工具全部 break;其 `README.md` 也声称"驱动内置 we-mp-rss v1.5.2 核心"。
- **多处过时注释/文档仍写"内置 we-mp-rss"**:`src/models.py:560`(wxmp description)、`src/config/constants.py:192`、`src/orchestrator.py:431`、`src/reports/fetcher.py:46/55`、`data/config.py` wxmp 注释;README 的 wxmp 章节(`README.md:329-336/361`)仍描述旧 rachelos 流程(Playwright、`data/wxmp/` 存登录态)——与现实现(pure HTTP、`weread_mp_id`)矛盾。
- **`data/config.py` 仍在手工迁移**:31+ 条 feed 的 `weread_mp_id` 靠人肉补;`horizon-wxmp subscribe/migrate` 可辅助,但 VPS 部署文档仍按旧流程写。
- **微信报告 PDF 解析依赖浏览器**:`wxmp_browser_resolver` 需要 Playwright + 可用的微信文章访问(登录态/风控),"阅读原文"/二维码两条策略都失败时报告只有原始文章链接、无 PDF。

### 架构 / 数据层

- **`PRAGMA foreign_keys` 未开启**:所有表声明的 `FOREIGN KEY ... ON DELETE CASCADE` 实际不生效——不要依赖数据库级联删除。
- **迁移无版本号**:DB schema 演进全靠连接时的幂等 `ALTER`/`ALTER`-重建,没有 `user_version`/Alembic;不要指望 `CREATE TABLE IF NOT EXISTS` 之外有自动迁移。
- **FTS trigram 的 `MATCH` 要求查询词 ≥3 字符**:中文单/双字搜索走 `search()` 的 `LIKE` 兜底(两者都建在 `items_fts` 上)。
- **配置是运行时执行文件**:`data/config.py` 会在加载时被 `exec_module` 执行,密钥绝不能写进去;未设置的 `${VAR}` 会原样保留并作为下游错误冒出来(不是静默空串)。
- **`content_hash`/`enrichment_source_hash` 目前只是记录字段**:除 HTML 翻译外,富化本身没有按 hash 跳过逻辑——每次运行对未变文章仍会重跑概念提取/搜索/生成。

### 数据质量(论文库)

- **`data/papers_failed_list.md`(未跟踪)**:164 篇 arXiv 论文 AI 打分失败(2026-08-03 批次)、2 篇精选论文解读 partial(`[enrich detail failed: partial: evaluation]`)。`src/papers/filters.py` 的 `is_paper_failed()` 过滤"失败不入库",但这批失败已入库的历史数据需注意。

### 配置 / 其它

- **deepseek 富化输出截断**:`ai.max_tokens` 默认 4096 对 en/zh 双语大 JSON 不够,必须 ≥8192(当前 `data/config.py` 已设);否则增强解析失败、退回轻量翻译。
- **`background_*` 字段在增强 prompt 里有定义但 enricher 不消费**(只拼了 `whats_new/why_it_matters/key_details` 等),做报告/前端时别依赖它。
- **前端无测试套件**:只能靠 `npm run build` + `npm run lint` 验证。
- **单用户架构**:`docs/product/PRD_Horizon_AI_News_Radar.md` 明确不支持多用户隔离;AI 补充背景信息可能有幻觉,靠标注来源缓解。
- **Twitter 源需 cookie**:建议用小号避免账号风险(`docs/twitter-cookies.md`)。
