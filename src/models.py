"""Core data models for Horizon."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, HttpUrl, Field, field_validator


class SourceType(str, Enum):
    """Supported information source types."""

    GITHUB = "github"
    HACKERNEWS = "hackernews"
    RSS = "rss"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    OPENBB = "openbb"
    OSSINSIGHT = "ossinsight"
    GDELT = "gdelt"
    GOOGLE_NEWS = "google_news"


class SourceRole(str, Enum):
    """Classification of a source's role/authority for provenance tracking."""

    OFFICIAL_COMPANY_BLOG = "official_company_blog"
    OFFICIAL_PRODUCT_PAGE = "official_product_page"
    OFFICIAL_MODEL_PAGE = "official_model_page"
    PAPER = "paper"
    MEDIA_REPORT = "media_report"
    EXPERT_BLOG = "expert_blog"
    SOCIAL_POST = "social_post"
    COMMUNITY_DISCUSSION = "community_discussion"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


# Priority used when picking the primary source for a merged event.
# Lower number = more authoritative.
SOURCE_ROLE_PRIORITY: dict[SourceRole, int] = {
    SourceRole.OFFICIAL_COMPANY_BLOG: 1,
    SourceRole.OFFICIAL_PRODUCT_PAGE: 2,
    SourceRole.OFFICIAL_MODEL_PAGE: 3,
    SourceRole.PAPER: 4,
    SourceRole.SOCIAL_POST: 5,
    SourceRole.MEDIA_REPORT: 6,
    SourceRole.EXPERT_BLOG: 7,
    SourceRole.COMMUNITY_DISCUSSION: 8,
    SourceRole.AGGREGATOR: 9,
    SourceRole.UNKNOWN: 10,
}


# Domain → SourceRole heuristics for URL classification.
_ROLE_DOMAIN_MAP: list[tuple[str, SourceRole]] = [
    # Official model / code hosts
    ("github.com", SourceRole.OFFICIAL_MODEL_PAGE),
    ("huggingface.co", SourceRole.OFFICIAL_MODEL_PAGE),
    ("modelscope.cn", SourceRole.OFFICIAL_MODEL_PAGE),
    ("gitlab.com", SourceRole.OFFICIAL_MODEL_PAGE),
    ("bitbucket.org", SourceRole.OFFICIAL_MODEL_PAGE),
    # Papers / research
    ("arxiv.org", SourceRole.PAPER),
    ("arxiv.org/abs", SourceRole.PAPER),
    ("openreview.net", SourceRole.PAPER),
    ("paperswithcode.com", SourceRole.PAPER),
    ("proceedings.neurips.cc", SourceRole.PAPER),
    ("proceedings.mlr.press", SourceRole.PAPER),
    ("dl.acm.org", SourceRole.PAPER),
    ("ieeexplore.ieee.org", SourceRole.PAPER),
    ("aclanthology.org", SourceRole.PAPER),
    ("research.google", SourceRole.PAPER),
    ("ai.meta.com/research", SourceRole.PAPER),
    ("cdn.openai.com/papers", SourceRole.PAPER),
    # Official company blogs / product pages
    ("openai.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("anthropic.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("deepmind.google", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("blog.google", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("ai.googleblog.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("ai.meta.com/blog", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("about.fb.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("engineering.fb.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("aws.amazon.com/blogs", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("azure.microsoft.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("blogs.microsoft.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("nvidia.com/blog", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("developer.nvidia.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("blog.x.ai", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("x.ai/blog", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("mistral.ai", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("cohere.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("stability.ai", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("deepseek.com", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("qwenlm.github.io", SourceRole.OFFICIAL_COMPANY_BLOG),
    ("huggingface.co/blog", SourceRole.OFFICIAL_COMPANY_BLOG),
    # Expert blogs
    ("simonwillison.net", SourceRole.EXPERT_BLOG),
    ("karpathy.ai", SourceRole.EXPERT_BLOG),
    ("lilianweng.github.io", SourceRole.EXPERT_BLOG),
    ("ycombinator.com", SourceRole.EXPERT_BLOG),
    ("gwern.net", SourceRole.EXPERT_BLOG),
    ("colah.github.io", SourceRole.EXPERT_BLOG),
    ("jalammar.github.io", SourceRole.EXPERT_BLOG),
    # Aggregators
    ("news.ycombinator.com", SourceRole.AGGREGATOR),
    ("reddit.com", SourceRole.AGGREGATOR),
    ("lobste.rs", SourceRole.AGGREGATOR),
    ("producthunt.com", SourceRole.AGGREGATOR),
    ("techmeme.com", SourceRole.AGGREGATOR),
    # Media
    ("techcrunch.com", SourceRole.MEDIA_REPORT),
    ("theverge.com", SourceRole.MEDIA_REPORT),
    ("arstechnica.com", SourceRole.MEDIA_REPORT),
    ("wired.com", SourceRole.MEDIA_REPORT),
    ("venturebeat.com", SourceRole.MEDIA_REPORT),
    ("zdnet.com", SourceRole.MEDIA_REPORT),
    ("theregister.com", SourceRole.MEDIA_REPORT),
    ("bloomberg.com", SourceRole.MEDIA_REPORT),
    ("reuters.com", SourceRole.MEDIA_REPORT),
    ("techinasia.com", SourceRole.MEDIA_REPORT),
    ("36kr.com", SourceRole.MEDIA_REPORT),
    ("jiqizhixin.com", SourceRole.MEDIA_REPORT),
    ("theinformation.com", SourceRole.MEDIA_REPORT),
    ("infoq.com", SourceRole.MEDIA_REPORT),
    ("thenewstack.io", SourceRole.MEDIA_REPORT),
    # Social platforms (official accounts may post here)
    ("x.com", SourceRole.SOCIAL_POST),
    ("twitter.com", SourceRole.SOCIAL_POST),
    ("t.me", SourceRole.SOCIAL_POST),
    ("telegram.org", SourceRole.SOCIAL_POST),
    ("linkedin.com", SourceRole.SOCIAL_POST),
    ("weibo.com", SourceRole.SOCIAL_POST),
    ("zhihu.com", SourceRole.SOCIAL_POST),
    # Community
    ("stackoverflow.com", SourceRole.COMMUNITY_DISCUSSION),
    ("discord.com", SourceRole.COMMUNITY_DISCUSSION),
    ("discuss.pytorch.org", SourceRole.COMMUNITY_DISCUSSION),
    ("community.openai.com", SourceRole.COMMUNITY_DISCUSSION),
    ("huggingface.co/spaces", SourceRole.COMMUNITY_DISCUSSION),
]


def classify_url_role(url: str) -> SourceRole:
    """Classify a URL into a SourceRole using domain heuristics.

    Args:
        url: A URL string to classify.

    Returns:
        SourceRole — falls back to ``SourceRole.UNKNOWN`` when no heuristic matches.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        path = parsed.path.lower()
        full = hostname + path
    except Exception:
        return SourceRole.UNKNOWN

    best: SourceRole = SourceRole.UNKNOWN
    best_len = 0
    for pattern, role in _ROLE_DOMAIN_MAP:
        # Longer pattern match = more specific
        if full.startswith(pattern) and len(pattern) > best_len:
            best = role
            best_len = len(pattern)
    return best


class ContentItem(BaseModel):
    """Unified content item model from any source."""

    id: str  # Format: {source}:{subtype}:{native_id}
    source_type: SourceType
    title: str
    url: HttpUrl
    content: Optional[str] = None  # legacy alias: raw_content if extraction succeeded, else the original scraper snippet
    raw_content: Optional[str] = None  # trafilatura plain-text extraction output, verbatim; None if extraction never succeeded
    rss_summary: Optional[str] = None  # scraper-provided snippet/summary, captured before extraction runs, always set
    raw_html: Optional[str] = None  # structured main-content HTML, unsanitized
    display_html: Optional[str] = None  # raw_html after nh3 whitelist sanitize
    display_html_zh: Optional[str] = None  # display_html with text blocks translated to Chinese
    cover_image: Optional[str] = None  # Primary/cover image URL, if any
    images: List[Dict[str, Any]] = Field(default_factory=list)  # [{url, alt, caption, source}, ...]

    # Full-article extraction provenance — persisted via metadata_json (see
    # storage/db.py), not dedicated DB columns.
    content_source: Optional[str] = None  # "full_text" | "rss_summary" | "none"
    extraction_status: Optional[str] = None  # "success" | "failed" | "skipped"
    extraction_error: Optional[str] = None  # skip/failure reason from content_extractor
    http_status: Optional[int] = None
    final_url: Optional[str] = None  # response URL after redirects
    text_length: Optional[int] = None  # len(raw_content) when extraction succeeded
    extracted_at: Optional[datetime] = None
    extractor_version: Optional[str] = None

    author: Optional[str] = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # AI analysis results
    ai_relevant: Optional[bool] = None  # True = relevant to AI/LLMs, False = not relevant
    ai_score: Optional[float] = None  # 0-10 importance score
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_tags: List[str] = Field(default_factory=list)


def sub_source_label(item: ContentItem) -> str:
    """Return a human-readable sub-source label for an item."""
    meta = item.metadata
    if meta.get("subreddit"):
        return f"r/{meta['subreddit']}"
    if meta.get("feed_name"):
        return meta["feed_name"]
    if meta.get("channel"):
        return f"@{meta['channel']}"
    if meta.get("period") and meta.get("repo"):
        return f"ossinsight:{meta.get('primary_language', 'all')}"
    if meta.get("repo"):
        return meta["repo"]
    if meta.get("watchlist"):
        return meta["watchlist"]
    if meta.get("source_name"):
        return meta["source_name"]
    if meta.get("gn_query"):
        return f"google_news:{meta['gn_query']}"
    if meta.get("domain"):
        return meta["domain"]
    return item.author or "unknown"


class AIProvider(str, Enum):
    """Supported AI providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE = "azure"
    ALI = "ali"
    GEMINI = "gemini"
    DOUBAO = "doubao"
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


# Default models and API key env vars for each provider
AI_PROVIDER_DEFAULTS = {
    AIProvider.ANTHROPIC: {
        "model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    AIProvider.OPENAI: {
        "model": "gpt-4",
        "api_key_env": "OPENAI_API_KEY",
    },
    AIProvider.AZURE: {
        "model": "gpt-4",
        "api_key_env": "AZURE_OPENAI_API_KEY",
    },
    AIProvider.ALI: {
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    AIProvider.GEMINI: {
        "model": "gemini-1.5-flash",
        "api_key_env": "GOOGLE_API_KEY",
    },
    AIProvider.DOUBAO: {
        "model": "doubao-pro-32k",
        "api_key_env": "DOUBAO_API_KEY",
    },
    AIProvider.MINIMAX: {
        "model": "MiniMax-Text-01",
        "api_key_env": "MINIMAX_API_KEY",
    },
    AIProvider.DEEPSEEK: {
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    AIProvider.OLLAMA: {
        "model": "llama3.1",
        "api_key_env": "",
    },
}


class AIConfig(BaseModel):
    """AI client configuration."""

    provider: AIProvider
    provider_chain: Optional[str] = None
    model: str
    base_url: Optional[str] = None
    api_key_env: str
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    analysis_concurrency: int = 1
    enrichment_concurrency: int = 1
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Azure OpenAI specific; required when provider == AZURE
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = None


class GitHubSourceConfig(BaseModel):
    """GitHub source configuration."""

    type: str  # "user_events", "repo_releases", etc.
    username: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True
    category: Optional[str] = None


class HackerNewsConfig(BaseModel):
    """Hacker News configuration."""

    enabled: bool = True
    fetch_top_stories: int = 30
    min_score: int = 100
    category: Optional[str] = None


class RSSSourceConfig(BaseModel):
    """RSS feed source configuration."""

    name: str
    url: HttpUrl
    enabled: bool = True
    category: Optional[str] = None


class RedditSubredditConfig(BaseModel):
    """Configuration for monitoring a specific subreddit."""

    subreddit: str
    enabled: bool = True
    sort: str = "hot"  # hot, new, top, rising
    time_filter: str = (
        "day"  # hour, day, week, month, year, all (only for top/controversial)
    )
    fetch_limit: int = 25
    min_score: int = 10
    category: Optional[str] = None


class RedditUserConfig(BaseModel):
    """Configuration for monitoring a specific Reddit user."""

    username: str  # without u/ prefix
    enabled: bool = True
    sort: str = "new"
    fetch_limit: int = 10


class RedditConfig(BaseModel):
    """Reddit source configuration."""

    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list)
    users: List[RedditUserConfig] = Field(default_factory=list)
    fetch_comments: int = 5  # top comments per post, 0 to disable


class TelegramChannelConfig(BaseModel):
    """Configuration for monitoring a specific Telegram channel."""

    channel: str  # channel username, e.g. "zaihuapd"
    enabled: bool = True
    fetch_limit: int = 20


class TelegramConfig(BaseModel):
    """Telegram source configuration."""

    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list)


class TwitterConfig(BaseModel):
    """Twitter source configuration.

    Two modes are supported:
    - "apify": Use Apify scweet actor (requires APIFY_TOKEN, more reliable)
    - "playwright": Use Playwright + browser cookies (free, no token needed)
    """

    enabled: bool = True
    mode: str = "apify"  # "apify" or "playwright"
    users: List[str] = Field(default_factory=list)
    fetch_limit: int = 10
    fetch_reply_text: bool = False
    max_replies_per_tweet: int = 3
    max_tweets_to_expand: int = 10
    reply_min_likes: int = 0
    # Apify settings (used when mode == "apify")
    apify_token_env: str = "APIFY_TOKEN"
    actor_id: str = "altimis~scweet"
    # Playwright settings (used when mode == "playwright")
    cookie_dir: str = "data"
    cookie_file_pattern: str = "x_cookies_*.json"


class OpenBBWatchlist(BaseModel):
    """A named watchlist of tickers fetched from one OpenBB provider.

    Each watchlist produces one news.company() call per run, so group
    symbols by provider rather than creating one watchlist per symbol.
    """

    name: str
    symbols: List[str] = Field(default_factory=list)
    enabled: bool = True
    provider: str = "yfinance"
    fetch_limit: int = 20
    category: Optional[str] = None


class OpenBBConfig(BaseModel):
    """OpenBB Platform source configuration.

    Uses the installed `openbb` SDK to fetch news and filings for a set of
    tickers. The SDK is an optional dependency; if it is not installed the
    scraper will no-op with a console warning rather than crash the run.

    Provider credentials (FMP, Benzinga, Polygon, Intrinio, Tiingo, etc.)
    are resolved by openbb from environment variables / its own user
    settings file, so Horizon does not need to pass them explicitly.
    """

    enabled: bool = True
    watchlists: List[OpenBBWatchlist] = Field(default_factory=list)
    fetch_filings: bool = False
    filings_provider: str = "sec"


class OSSInsightConfig(BaseModel):
    """OSS Insight trending repos source configuration.

    Pulls top star-gain repositories from the OSS Insight public API and
    emits them as ContentItems. Optional `keywords` filter limits results
    to repos whose description, repo name, or collection names contain at
    least one of the listed substrings (case-insensitive). Leave
    `keywords` empty to ingest everything trending in the configured
    languages.
    """

    enabled: bool = False
    period: str = "past_24_hours"  # past_24_hours, past_28_days
    languages: List[str] = Field(
        default_factory=lambda: ["All", "Python", "TypeScript"]
    )
    keywords: List[str] = Field(default_factory=list)
    min_stars: int = 5
    max_items: int = 30


class GDELTConfig(BaseModel):
    """GDELT 2.0 DOC API source configuration.

    Queries the key-less GDELT DOC API
    (https://api.gdeltproject.org/api/v2/doc/doc) for recent news articles
    matching a search query and emits them as ContentItems. No API key is
    required. The DOC API caps results at 250 records per request, so keep
    `max_records` modest.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    mode: str = "ArtList"
    max_records: int = 75  # GDELT DOC API caps at 250; keep modest
    timespan: Optional[str] = None  # e.g. "24h"; overrides since-derived window
    language: Optional[str] = None  # sourcelang filter, e.g. "english"; None = no filter
    country: Optional[str] = None  # sourcecountry filter; None = no filter
    category: Optional[str] = None  # Horizon category label for downstream grouping


class GoogleNewsConfig(BaseModel):
    """Google News RSS search source configuration.

    Builds Google News RSS search URLs
    (https://news.google.com/rss/search) for a query and parses the
    resulting feed via feedparser. No API key is required.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    language: str = "en"  # hl
    country: str = "US"  # gl
    ceid: Optional[str] = None  # when None scraper derives it as "{country}:{language}"
    max_results: int = 100  # cap ~100
    category: Optional[str] = None


class SourcesConfig(BaseModel):
    """All sources configuration."""

    github: List[GitHubSourceConfig] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    rss: List[RSSSourceConfig] = Field(default_factory=list)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    twitter: Optional[TwitterConfig] = None
    openbb: Optional[OpenBBConfig] = None
    ossinsight: OSSInsightConfig = Field(default_factory=OSSInsightConfig)
    gdelt: Optional[GDELTConfig] = None
    google_news: Optional[GoogleNewsConfig] = None


class WebhookConfig(BaseModel):
    """Webhook notification configuration."""

    url_env: Optional[str] = (
        None  # Environment variable name containing the webhook URL
    )
    request_body: Optional[Union[str, dict, list]] = (
        None  # POST body: real JSON object or string with #{key} placeholders; if empty, will use GET
    )
    headers: Optional[str] = None  # Custom headers, "Key: Value" per line
    delivery: str = "summary"  # summary, or summary_and_items
    overview_position: str = "first"  # For summary_and_items: first, or last
    platform: str = "generic"  # generic, feishu, lark, dingtalk, slack, discord
    layout: str = "markdown"  # markdown, or collapsible
    fallback_layout: str = (
        "markdown"  # Layout to use when the requested layout is unsupported
    )
    languages: Optional[List[str]] = (
        None  # Optional language filter for webhook delivery; defaults to all AI languages
    )
    enabled: bool = False
    max_items: Optional[int] = Field(default=None, gt=0)

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str) -> str:
        allowed = {"summary", "summary_and_items"}
        if v not in allowed:
            raise ValueError(f"webhook.delivery must be one of {allowed}, got '{v}'")
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"generic", "feishu", "lark", "dingtalk", "slack", "discord"}
        if v not in allowed:
            raise ValueError(f"webhook.platform must be one of {allowed}, got '{v}'")
        return v

    @field_validator("layout")
    @classmethod
    def validate_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(f"webhook.layout must be one of {allowed}, got '{v}'")
        return v

    @field_validator("fallback_layout")
    @classmethod
    def validate_fallback_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(
                f"webhook.fallback_layout must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("overview_position")
    @classmethod
    def validate_overview_position(cls, v: str) -> str:
        allowed = {"first", "last"}
        if v not in allowed:
            raise ValueError(
                f"webhook.overview_position must be one of {allowed}, got '{v}'"
            )
        return v


class EmailConfig(BaseModel):
    """Email configuration for updates/subscriptions."""

    imap_server: str
    imap_port: int = 993
    imap_enabled: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_username: Optional[str] = None
    email_address: str
    password_env: str = "EMAIL_PASSWORD"
    sender_name: str = "Horizon Daily"
    subscribe_keyword: str = "SUBSCRIBE"
    unsubscribe_keyword: str = "UNSUBSCRIBE"
    enabled: bool = False


class CategoryGroupConfig(BaseModel):
    """A quota group containing one or more source categories."""

    name: Optional[str] = None
    limit: int = Field(gt=0)
    categories: List[str] = Field(min_length=1)


class FilteringConfig(BaseModel):
    """Content filtering configuration."""

    ai_score_threshold: float = 7.0
    time_window_hours: int = 24
    max_items: Optional[int] = Field(default=None, gt=0)
    category_groups: Dict[str, CategoryGroupConfig] = Field(default_factory=dict)
    default_group: str = "other"
    default_group_limit: Optional[int] = Field(default=None, gt=0)


class Config(BaseModel):
    """Main configuration model."""

    version: str = "1.0"
    ai: AIConfig
    sources: SourcesConfig
    filtering: FilteringConfig
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None
