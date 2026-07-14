# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Horizon is an AI-powered news aggregation pipeline that fetches content from multiple sources (Hacker News, RSS, Reddit, Telegram, Twitter/X, GitHub, OpenBB, GDELT, Google News), deduplicates stories via URL and AI semantic matching, scores items for importance, enriches them with web-researched background context, and generates bilingual (EN/ZH) Markdown daily briefings. Outputs include GitHub Pages sites, email newsletters, webhook notifications (Feishu, Slack, Discord, etc.), and a FastAPI + React query API/UI over the same data.

## Build, Test, and Run

```bash
# Install dependencies (uses uv as package manager)
uv sync                          # base install
uv sync --extra dev              # install dev dependencies (pytest, pytest-cov)
uv sync --extra openbb           # optional OpenBB financial-news SDK
uv sync --extra twitter          # optional Playwright-based Twitter scraper

# Run the main pipeline
uv run horizon                   # default 24h window
uv run horizon --hours 48        # custom time window

# Interactive setup wizard (generates data/config.json from interests)
uv run horizon-wizard

# API server (FastAPI over data/horizon.db; serves the React app + server-rendered debug pages)
uv run horizon-api               # http://localhost:8000, auto-reload

# MCP server
uv run horizon-mcp

# Webhook CLI (send a one-off test notification)
uv run horizon-webhook --date 2026-07-01 --language en

# Tests
uv run pytest                    # all tests
uv run pytest tests/test_rss.py  # single test file
uv run pytest -k "test_name"     # specific test
uv run pytest --cov=src          # with coverage

# Docker
docker compose run --rm horizon
docker compose run --rm horizon --hours 48
```

### Frontend (React app under `frontend/`)

```bash
cd frontend
npm install
npm run dev        # Vite dev server; proxies /api to http://localhost:8000 (see vite.config.ts)
npm run build       # tsc -b && vite build
npm run lint         # oxlint
```

The frontend is a separate npm project (not part of the `uv` workspace); run `horizon-api` alongside `npm run dev` for a working local stack.

## Architecture

### Pipeline (the orchestrator)

`src/orchestrator.py` runs these stages linearly:

1. **Fetch** — all configured scrapers run concurrently via `asyncio.gather` sharing a single `httpx.AsyncClient`
2. **Merge cross-source duplicates** — deduplicate by normalized URL (strip www, trailing slashes, fragments), merge metadata and content from duplicates into the richest item (`src/dedup.py:merge_cross_source_duplicates`)
3. **AI Score** — `ContentAnalyzer.analyze_batch()` sends each item to the configured AI provider, returning a 0–10 score, reason, summary, and tags. Throttle and concurrency configurable via `ai.throttle_sec` and `ai.analysis_concurrency`
4. **Filter by threshold** — keep items with `ai_score >= ai_score_threshold`, sort descending
5. **AI topic dedup** — semantic deduplication: AI identifies groups covering the same story and merges content from dropped duplicates into the primary (`src/dedup.py:merge_topic_duplicates`)
6. **twitter discussion expansion** — optional second-stage reply fetch + re-analysis for Twitter items
7. **Balanced digest** — apply per-category quotas (`filtering.category_groups`) and global `max_items` cap (`src/filtering.py:apply_balanced_digest`)
8. **Enrich** — `ContentEnricher.enrich_batch()` for each item: AI extracts concepts needing explanation → DuckDuckGo web search → AI generates grounded background, detailed summary, and community discussion in both languages; light translation fallback on failure
9. **Summarize** — `DailySummarizer` renders Markdown with TOC, per-item sections. Summaries saved to `data/summaries/`, copied to `docs/_posts/` for GitHub Pages, and sent via email/webhook

`src/orchestrator.py` itself only coordinates this sequence — the dedup algorithms, balanced-digest filtering, and the static topic-taxonomy seed data used by stage 5's classification live in their own modules (`src/dedup.py`, `src/filtering.py`, `src/seed_topics.py`) so they're independently testable and reusable (e.g. by `src/mcp/service.py`).

### Scraper pattern

All scrapers extend `BaseScraper` (`src/scrapers/base.py`) with a single async method: `fetch(since: datetime) -> List[ContentItem]`. Each scraper receives its config object and a shared `httpx.AsyncClient`. The orchestrator constructs and calls them in `fetch_all_sources()`. New scrapers must:
- Accept `(config, http_client)` in `__init__`
- Implement `fetch(self, since: datetime) -> List[ContentItem]`
- Generate IDs as `{source_type}:{subtype}:{native_id}` via `self._generate_id()`

### AI provider abstraction

`src/ai/client.py` defines the factory `create_ai_client(config: AIConfig) -> AIClient`:

- `AnthropicClient` — native Anthropic SDK
- `OpenAIClient` — OpenAI-compatible SDK; handles OpenAI, Ali (DashScope), DeepSeek, Doubao, MiniMax, Ollama via base_url routing with provider-specific quirks (Ollama URL normalization, MiniMax temperature clamping, `response_format` suppression)
- `AzureOpenAIClient` — Azure-specific deployment API with `max_completion_tokens` fallback for reasoning models
- `GeminiClient` — native Google GenAI SDK
- `ChainedAIClient` — comma-separated `provider_chain` in config; lazy-initializes each provider and falls through on rate-limit/auth/quota/service-unavailable errors

All clients implement `async complete(system, user, temperature?, max_tokens?) -> str`.

### Data models

`src/models.py` — Pydantic v2 models for the entire config (`Config`, `AIConfig`, `SourcesConfig`, individual source configs, `FilteringConfig`, `EmailConfig`, `WebhookConfig`) and the unified `ContentItem`. Config uses `field_validator`s for allowed values. Provider defaults in `AI_PROVIDER_DEFAULTS`. The `SourceType` enum defines all supported source types.

### Configuration

`data/config.json` is the single config file. `StorageManager` (`src/storage/manager.py`) loads it and expands `${VAR_NAME}` references in any string value before Pydantic validation — private URLs, keys, and endpoints stay out of the JSON file. API keys are always stored in `.env` and referenced by env var name via `ai.api_key_env`.

### MCP server

`src/mcp/server.py` exposes Horizon pipeline steps as MCP tools (fetch, score, filter, enrich, summarize, run-full-workflow) so AI assistants can drive the pipeline. `src/mcp/service.py` handles pipeline execution and config validation; `src/mcp/run_store.py` persists each pipeline run's intermediate artifacts (raw/scored/filtered items, summaries) to disk under a run ID so MCP tool calls can resume/inspect a run across multiple calls.

### Query API and web frontend

Pipeline output is additionally persisted to a SQLite database (`src/storage/db.py`, `HorizonDB`) with an FTS5 full-text index over items, a real (indexed) `category` column kept in sync with `metadata_json.category` for backward compatibility, plus `topics` / `news_topics` tables for AI-assigned topic grouping. `src/api/server.py` (FastAPI, entry point `horizon-api`) reads from this DB and serves:
- A JSON REST API under `/api/*` (items, tags, categories, topics, daily runs, stats, search, favorites, topic preferences) consumed by the React frontend
- Server-rendered Jinja2 pages (`src/api/templates/`) at `/`, `/topics`, `/topics/{slug}` — a lightweight fallback UI with no favorites/preferences support (see below)
- `/debug` — serves the static `debug-frontend/` dashboard for inspecting raw pipeline state

`src/content_extractor.py` fetches an item's original URL and extracts full article text via `trafilatura`, skipping non-article domains (social/code-hosting sites) and non-HTML/too-short responses; used to give the AI enricher more grounded source material.

The **React frontend** (`frontend/`, Vite + React 19 + TypeScript + Tailwind v4 + react-router) is a separate npm project that consumes the `/api/*` JSON endpoints (`frontend/src/api/client.ts`, typed in `frontend/src/api/types.ts`). It uses `HashRouter` (`frontend/src/App.tsx`) with routes for home, daily list/detail, item detail, topics list/detail, favorites, and topic preferences, each backed by a `useApi`-style hook (`frontend/src/hooks/useApi.ts`). In production the built app is expected to be served as a static site (Vite `base: './'`); in dev, Vite proxies `/api` to `horizon-api` on port 8000.

#### Favorites and topic preferences (no login required)

There is no user-account system. The frontend generates a random per-browser id (`crypto.randomUUID()`, persisted in `localStorage` by `frontend/src/utils/userId.ts`) and sends it as an `X-User-Id` header on every API request (`frontend/src/api/client.ts`). The backend treats this as an opaque string — it doesn't authenticate it, and every endpoint that reads it is a no-op when the header is absent, so unauthenticated callers see identical behavior to before this feature existed.

Two DB tables scope state by that id: `user_item_state` (favorites; `state='favorited'`, leaves room for e.g. `'read'` later) and `user_topic_prefs` (`state` is `'subscribed'` or `'blocked'`, mutually exclusive per topic). `HorizonDB` exposes `set_favorite`/`get_favorites`/`get_favorited_ids` and `set_topic_pref`/`get_topic_prefs`/`get_blocked_topic_ids`.

- **Favorites** — `PUT`/`DELETE /api/favorites/{item_id}`, `GET /api/favorites`. Item responses gain an additive `is_favorited` field when `X-User-Id` is present.
- **Blocking** — `GET /api/items`, `GET /api/topics/{slug}/news`, `GET /api/daily/{date}` (home page + daily report), `GET /api/topics`, and `GET /api/search` all accept the caller's blocked-topic set and exclude matching items/topics; `GET /api/topics?include_blocked=true` opts out of that filtering (used by the preferences page, which needs to show every topic in order to un-block them).
- **Subscribing** — currently bookkeeping only (`GET`/`PUT /api/topic-prefs(/{slug})`); no page filters or highlights content based on it yet.
- Frontend pieces: `FavoriteButton`, `TopicPrefButtons` (controlled, backed by the shared `useTopicPrefsState` hook so the same topic shown in two places — e.g. the preferences page's summary and its full list — stays in sync), and the `FavoritesPage`/`PreferencesPage` routes.
- The server-rendered Jinja2 pages have no client-side identity mechanism and are intentionally out of scope for this feature.

### Key directories

| Path | Purpose |
|------|---------|
| `src/scrapers/` | Source-specific fetchers (one per source type) |
| `src/ai/` | AI client abstraction, analyzer, enricher, summarizer, prompts, token tracking |
| `src/storage/` | Config loading/saving, subscriber management, SQLite persistence (`db.py`) |
| `src/services/` | Email (SMTP/IMAP) and webhook (multi-platform) delivery |
| `src/api/` | FastAPI query API + server-rendered fallback UI over the SQLite DB |
| `src/mcp/` | MCP server that exposes pipeline as tools, plus per-run artifact storage |
| `src/setup/` | Interactive wizard — AI-generated source config from user interests |
| `src/content_extractor.py` | Full article text extraction (trafilatura) for enrichment |
| `src/models.py` | All Pydantic config/data models |
| `src/orchestrator.py` | Pipeline coordination |
| `src/dedup.py` | Cross-source URL dedup, AI semantic topic dedup, and source-provenance aggregation |
| `src/filtering.py` | Per-category quota / global item-cap balanced-digest filtering |
| `src/seed_topics.py` | Static topic taxonomy seed data (name/slug/keywords per topic) |
| `frontend/` | React + Vite + Tailwind SPA consuming the `/api/*` endpoints |
| `debug-frontend/` | Static HTML dashboard served at `/debug` by `horizon-api` |
| `data/` | Runtime data: config.json, summaries/, subscribers.json, horizon.db |
| `docs/` | GitHub Pages site (Jekyll); `docs/_posts/` receives generated summaries |

### CI/CD

- `.github/workflows/daily-summary.yml` — scheduled cron (00:17 UTC daily) + manual trigger; runs `uv run horizon --hours 24` with secrets, deploys to `gh-pages`
- `.github/workflows/deploy-docs.yml` — on push to `docs/**`, deploys to GitHub Pages via `peaceiris/actions-gh-pages`

### Webhooks

`src/services/webhook.py` — `WebhookNotifier` sends templated summaries to Feishu/Lark, DingTalk, Slack, Discord, or generic webhooks. Configurable delivery mode (`summary` or `summary_and_items`), layout (`markdown` or `collapsible`), and language filter.

### Tests

Tests use pytest with fixtures from `conftest.py` (just adds project root to sys.path). Test files mirror source modules (`test_rss.py`, `test_analyzer.py`, `test_api.py`, `test_db.py`, etc.). MCP and provider-specific tests (Azure, Minimax, chained client) validate integration paths. The `frontend/` app has no test suite yet — validate changes with `npm run build` and `npm run lint`.