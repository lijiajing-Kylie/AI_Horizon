# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Horizon is an AI-powered news aggregation pipeline that fetches content from multiple sources (Hacker News, RSS, Reddit, Telegram, Twitter/X, GitHub, OpenBB, GDELT, Google News), deduplicates stories via URL and AI semantic matching, scores items for importance, enriches them with web-researched background context, and generates bilingual (EN/ZH) Markdown daily briefings. Outputs include GitHub Pages sites, email newsletters, and webhook notifications (Feishu, Slack, Discord, etc.).

## Build, Test, and Run

```bash
# Install dependencies (uses uv as package manager)
uv sync                          # base install
uv sync --extra dev              # install dev dependencies (pytest, pytest-cov)
uv sync --extra openbb           # optional OpenBB financial-news SDK

# Run the main pipeline
uv run horizon                   # default 24h window
uv run horizon --hours 48        # custom time window

# Interactive setup wizard (generates data/config.json from interests)
uv run horizon-wizard

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

## Architecture

### Pipeline (the orchestrator)

`src/orchestrator.py` runs these stages linearly:

1. **Fetch** — all configured scrapers run concurrently via `asyncio.gather` sharing a single `httpx.AsyncClient`
2. **Merge cross-source duplicates** — deduplicate by normalized URL (strip www, trailing slashes, fragments), merge metadata and content from duplicates into the richest item
3. **AI Score** — `ContentAnalyzer.analyze_batch()` sends each item to the configured AI provider, returning a 0–10 score, reason, summary, and tags. Throttle and concurrency configurable via `ai.throttle_sec` and `ai.analysis_concurrency`
4. **Filter by threshold** — keep items with `ai_score >= ai_score_threshold`, sort descending
5. **AI topic dedup** — semantic deduplication: AI identifies groups covering the same story and merges content from dropped duplicates into the primary
6. **twitter discussion expansion** — optional second-stage reply fetch + re-analysis for Twitter items
7. **Balanced digest** — apply per-category quotas (`filtering.category_groups`) and global `max_items` cap
8. **Enrich** — `ContentEnricher.enrich_batch()` for each item: AI extracts concepts needing explanation → DuckDuckGo web search → AI generates grounded background, detailed summary, and community discussion in both languages; light translation fallback on failure
9. **Summarize** — `DailySummarizer` renders Markdown with TOC, per-item sections. Summaries saved to `data/summaries/`, copied to `docs/_posts/` for GitHub Pages, and sent via email/webhook

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

`src/mcp/server.py` exposes Horizon pipeline steps as MCP tools (fetch, score, filter, enrich, summarize, run-full-workflow) so AI assistants can drive the pipeline. `src/mcp/service.py` handles pipeline execution and config validation.

### Key directories

| Path | Purpose |
|------|---------|
| `src/scrapers/` | Source-specific fetchers (one per source type) |
| `src/ai/` | AI client abstraction, analyzer, enricher, summarizer, prompts, token tracking |
| `src/storage/` | Config loading/saving, subscriber management |
| `src/services/` | Email (SMTP/IMAP) and webhook (multi-platform) delivery |
| `src/mcp/` | MCP server that exposes pipeline as tools |
| `src/setup/` | Interactive wizard — AI-generated source config from user interests |
| `src/models.py` | All Pydantic config/data models |
| `src/orchestrator.py` | Pipeline coordination |
| `src/search.py` | HN Algolia + Reddit related-story search |
| `data/` | Runtime data: config.json, summaries/, subscribers.json |
| `docs/` | GitHub Pages site (Jekyll); `docs/_posts/` receives generated summaries |

### CI/CD

- `.github/workflows/daily-summary.yml` — scheduled cron (00:17 UTC daily) + manual trigger; runs `uv run horizon --hours 24` with secrets, deploys to `gh-pages`
- `.github/workflows/deploy-docs.yml` — on push to `docs/**`, deploys to GitHub Pages via `peaceiris/actions-gh-pages`

### Webhooks

`src/services/webhook.py` — `WebhookNotifier` sends templated summaries to Feishu/Lark, DingTalk, Slack, Discord, or generic webhooks. Configurable delivery mode (`summary` or `summary_and_items`), layout (`markdown` or `collapsible`), and language filter.

### Tests

Tests use pytest with fixtures from `conftest.py` (just adds project root to sys.path). Test files mirror source modules (`test_rss.py`, `test_analyzer.py`, etc.). MCP and provider-specific tests (Azure, Minimax, chained client) validate integration paths.