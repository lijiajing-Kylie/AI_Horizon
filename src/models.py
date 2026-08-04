"""Core data models for Horizon."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, HttpUrl, Field, computed_field, field_validator

from .config.constants import (
    AI_PROVIDER_DEFAULTS as _AI_PROVIDER_DEFAULTS_STR,
    SOURCE_ROLE_PRIORITY as _SOURCE_ROLE_PRIORITY_STR,
    ROLE_DOMAIN_MAP as _ROLE_DOMAIN_MAP_STR,
)


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
    HUAWEI_NEWS = "huawei_news"
    BYTEDANCE_NEWS = "bytedance_news"
    WECHAT = "wechat"


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


# ── 枚举版常量（向下兼容 dedup.py 等从 models.py 导入的旧代码）──
# 数据定义在 src/config/constants.py，这里转为枚举 key 再导出
SOURCE_ROLE_PRIORITY: dict = {SourceRole(k): v for k, v in _SOURCE_ROLE_PRIORITY_STR.items()}
_ROLE_DOMAIN_MAP: list = [(d, SourceRole(r)) for d, r in _ROLE_DOMAIN_MAP_STR]



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
    rss_content_quality: Optional[str] = None  # "high" | "low" | "none" — quality assessment of RSS-provided content
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


# ── 枚举版常量（向下兼容 wizard.py / ai/client.py 等旧代码）──
# 数据定义在 src/config/constants.py（字符串 key），这里转为 AIProvider 枚举 key
AI_PROVIDER_DEFAULTS: dict = {AIProvider(k): v for k, v in _AI_PROVIDER_DEFAULTS_STR.items()}


class AIConfig(BaseModel):
    """AI 供应商连接配置。"""

    provider: AIProvider = Field(description="AI 供应商，可选：anthropic / openai / azure / ali / gemini / doubao / minimax / deepseek / ollama")
    provider_chain: Optional[str] = Field(default=None, description='供应商故障回退链，逗号分隔。例如 "deepseek,openai" —— 第一个失败时自动切到下一个')
    model: str = Field(description="模型名称。各供应商默认模型在 src/config/constants.py 的 AI_PROVIDER_DEFAULTS 中定义")
    base_url: Optional[str] = Field(default=None, description="自定义 API 端点。支持 ${VAR} 从环境变量读取。为空则用 constants.py 的 DEFAULT_BASE_URLS")
    api_key_env: str = Field(description="存放 API 密钥的环境变量名。例如 ANTHROPIC_API_KEY")
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    analysis_concurrency: int = Field(default=1, description="内容分析阶段的并发请求数。设为 5 可加速但注意 API 速率限制")
    enrichment_concurrency: int = Field(default=1, description="内容丰富阶段的并发请求数。值越大 Web 搜索 + AI 补充越快")
    languages: List[str] = Field(default_factory=lambda: ["en"])
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = Field(default=None, description="Azure OpenAI API 版本号，例如 2024-02-15-preview")


class GitHubSourceConfig(BaseModel):
    """GitHub 源配置：监听用户动态或仓库发布。"""

    type: str = Field(description="类型。user_events=用户动态 / repo_releases=仓库发布")
    username: Optional[str] = Field(default=None, description="GitHub 用户名，用于 user_events 模式")
    owner: Optional[str] = Field(default=None, description="仓库 owner，用于 repo_releases 模式")
    repo: Optional[str] = Field(default=None, description="仓库名，用于 repo_releases 模式")
    enabled: bool = True
    category: Optional[str] = None


class HackerNewsConfig(BaseModel):
    """Hacker News 源配置。"""

    enabled: bool = True
    fetch_top_stories: int = Field(default=30, description="每次抓取多少条 top stories")
    min_score: int = Field(default=100, description="最低分数过滤，分数低于此的不收录")
    category: Optional[str] = None


class RSSSourceConfig(BaseModel):
    """RSS 订阅源配置。"""

    name: str = Field(description="RSS 源显示名称（如 'OpenAI Blog'）")
    url: HttpUrl = Field(description="RSS/Atom 订阅地址。支持 ${VAR} 从环境变量读取")
    enabled: bool = True
    category: Optional[str] = Field(default=None, description="分类标签，用于后续过滤分组")
    extraction_mode: str = Field(default="http", description="文章提取模式：http=HTTP 抓取 / browser=Playwright 浏览器渲染 / skip=跳过提取")


class RedditSubredditConfig(BaseModel):
    """Reddit 子版块监控配置。"""

    subreddit: str = Field(description="子版块名，例如 MachineLearning")
    enabled: bool = True
    sort: str = Field(default="hot", description="排序方式：hot / new / top / rising")
    time_filter: str = Field(default="day", description="时间范围：hour / day / week / month / year / all（仅 top/rising 有效）")
    fetch_limit: int = Field(default=25, description="每次抓取帖子数")
    min_score: int = Field(default=10, description="最低分数过滤")
    category: Optional[str] = None


class RedditUserConfig(BaseModel):
    """Reddit 用户监控配置。"""

    username: str = Field(description="Reddit 用户名，不加 u/ 前缀")
    enabled: bool = True
    sort: str = Field(default="new", description="排序方式：new / hot / top / rising")
    fetch_limit: int = Field(default=10, description="每次抓取帖子数")


class RedditConfig(BaseModel):
    """Reddit 源配置。"""

    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list, description="要监控的子版块列表")
    users: List[RedditUserConfig] = Field(default_factory=list, description="要监控的用户列表")
    fetch_comments: int = Field(default=5, description="每条帖子的 top 评论数。0=不抓取评论")


class TelegramChannelConfig(BaseModel):
    """Telegram 频道监控配置。"""

    channel: str = Field(description="频道用户名，例如 zaihuapd")
    enabled: bool = True
    fetch_limit: int = Field(default=20, description="每次抓取消息数")


class TelegramConfig(BaseModel):
    """Telegram 源配置。"""

    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list, description="要监控的频道列表")


class TwitterConfig(BaseModel):
    """Twitter / X 源配置。"""

    enabled: bool = True
    mode: str = Field(default="apify", description="抓取模式：apify（通过 Apify Scweet，更稳定，需 APIFY_TOKEN）/ playwright（通过浏览器，免费）")
    users: List[str] = Field(default_factory=list, description="要监控的用户名列表")
    fetch_limit: int = Field(default=10, description="每次抓取推文数")
    fetch_reply_text: bool = Field(default=False, description="是否获取推文的回复内容")
    max_replies_per_tweet: int = Field(default=3, description="每条推文最多获取多少条回复")
    max_tweets_to_expand: int = Field(default=10, description="最多展开多少条推文的回复讨论")
    reply_min_likes: int = Field(default=0, description="回复的最低点赞数过滤")
    apify_token_env: str = Field(default="APIFY_TOKEN", description="Apify API 令牌的环境变量名")
    actor_id: str = Field(default="altimis~scweet", description="Apify Scweet actor ID")
    cookie_dir: str = Field(default="data", description="Playwright 浏览器 cookie 存储目录")
    cookie_file_pattern: str = Field(default="x_cookies_*.json", description="Playwright cookie 文件名模式")


class OpenBBWatchlist(BaseModel):
    """OpenBB 监控列表：一组股票代码，使用同一个数据提供商。"""

    name: str = Field(description="监控列表名称，仅用于标识")
    symbols: List[str] = Field(default_factory=list, description="股票代码列表，例如 ['AAPL', 'MSFT', 'GOOGL']")
    enabled: bool = True
    provider: str = Field(default="yfinance", description="数据提供商：yfinance / fmp / benzinga / polygon / intrinio / tiingo 等")
    fetch_limit: int = Field(default=20, description="每次抓取新闻数")
    category: Optional[str] = None


class OpenBBConfig(BaseModel):
    """OpenBB 金融数据源配置。"""

    enabled: bool = True
    watchlists: List[OpenBBWatchlist] = Field(default_factory=list, description="监控列表")
    fetch_filings: bool = Field(default=False, description="是否获取 SEC 文件申报")
    filings_provider: str = Field(default="sec", description="文件申报数据提供商")


class OSSInsightConfig(BaseModel):
    """OSS Insight 开源项目趋势配置。"""

    enabled: bool = False
    period: str = Field(default="past_24_hours", description="统计周期：past_24_hours / past_28_days")
    languages: List[str] = Field(default_factory=lambda: ["All", "Python", "TypeScript"], description="编程语言过滤")
    keywords: List[str] = Field(default_factory=list, description="关键词过滤（可选）。对描述/仓库名做不区分大小写的子串匹配")
    min_stars: int = Field(default=5, description="最低 star 数")
    max_items: int = Field(default=30, description="最多收录仓库数")


class GDELTConfig(BaseModel):
    """GDELT 全球新闻事件源配置。无需 API key。"""

    enabled: bool = False
    query: str = Field(default="artificial intelligence", description="搜索关键词")
    mode: str = Field(default="ArtList", description="API 模式")
    max_records: int = Field(default=75, description="最大返回条数（GDELT 上限 250）")
    timespan: Optional[str] = Field(default=None, description="时间范围，例如 24h。不填则根据 since 自动计算")
    language: Optional[str] = Field(default=None, description="新闻语言过滤，例如 english。不填则不限制")
    country: Optional[str] = Field(default=None, description="新闻来源国家过滤。不填则不限制")
    category: Optional[str] = None


class GoogleNewsConfig(BaseModel):
    """Google News RSS 搜索源配置。无需 API key。"""

    enabled: bool = False
    query: str = Field(default="artificial intelligence", description="搜索关键词")
    language: str = Field(default="en", description="新闻语言（hl 参数）")
    country: str = Field(default="US", description="新闻来源国家（gl 参数）")
    ceid: Optional[str] = Field(default=None, description="版本文本。不填则自动推导为 {country}:{language}")
    max_results: int = Field(default=100, description="最大结果数")
    category: Optional[str] = None


class HuaweiNewsConfig(BaseModel):
    """华为新闻中心源配置。需要 Playwright 渲染 JS SPA。"""

    enabled: bool = False
    url: str = Field(default="https://www.huawei.com/cn/news", description="华为新闻中心页面地址")
    fetch_limit: int = Field(default=50, description="每次抓取文章数")
    category: Optional[str] = None


class ByteDanceNewsConfig(BaseModel):
    """字节跳动 Seed 技术博客源配置。纯 HTTP 抓取，无需浏览器。"""

    enabled: bool = False
    url: str = Field(default="https://seed.bytedance.com/zh/blog", description="Seed 博客地址")
    fetch_limit: int = Field(default=50, description="每次抓取文章数")
    fetch_details: bool = Field(default=False, description="是否获取全文 HTML")
    category: Optional[str] = None


class OpenAlexSourceConfig(BaseModel):
    """OpenAlex 经典论文源：基于固定种子列表匹配，不是实时推荐。"""

    enabled: bool = Field(default=True, description="是否启用 OpenAlex 论文源")


class HuggingFaceSourceConfig(BaseModel):
    """Hugging Face 每日热门论文源：每月拉取上月热门论文。"""

    enabled: bool = Field(default=True, description="是否启用 Hugging Face 论文源")
    top_n: int = Field(default=15, description="按点赞数保留前 N 篇")
    topics: List[str] = Field(default_factory=list, description="关键词过滤（可选）。对标题/摘要/分类做不区分大小写的子串匹配")


class PapersConfig(BaseModel):
    """论文库配置：独立于新闻管线的学术论文抓取。"""

    enabled: bool = Field(default=False, description="是否启用论文库")
    openalex: OpenAlexSourceConfig = Field(default_factory=OpenAlexSourceConfig, description="OpenAlex 经典论文源（基于固定种子列表，非实时推荐）")
    huggingface: HuggingFaceSourceConfig = Field(default_factory=HuggingFaceSourceConfig, description="Hugging Face 每日热门论文源（每月自动更新）")


class ReportSourceItem(BaseModel):
    """A single report source with per-source settings.

    In config.json this maps to e.g. ``{"name": "fxbaogao", "ai_filter": true}``.
    For "wxmp", set ``account_names`` to the list of WeChat accounts to treat
    as report sources.
    """

    name: str
    ai_filter: bool = True
    account_names: List[str] = Field(
        default_factory=list,
        description="For wxmp source: which WeChat accounts to fetch as reports",
    )


class ReportsConfig(BaseModel):
    """Research-reports library configuration.

    Standalone pipeline, independent of both the news pipeline and the papers
    library. Per-source tunables (e.g. page size) live in that source's own
    module.
    """

    enabled: bool = Field(default=False, description="是否启用报告库")
    sources: List[ReportSourceItem] = Field(
        default_factory=lambda: [
            ReportSourceItem(name="aliresearch"),
            ReportSourceItem(name="aliyunreports"),
        ],
        description="报告源列表：每个项目为 {\"name\": 源名, \"ai_filter\": 是否AI过滤}，也兼容旧版字符串列表如 [\"aliresearch\"]",
    )

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_sources(cls, v):
        """兼容字符串列表和字典列表两种格式。"""
        if isinstance(v, list):
            items = []
            for item in v:
                if isinstance(item, str):
                    items.append({"name": item})
                elif isinstance(item, dict):
                    items.append(item)
                else:
                    items.append(item)
            return items
        return v
    pdf_output_dir: str = Field(default="data/reports_pdfs", description="PDF 文件下载后存放的本地目录")
    download_pdfs: bool = Field(default=True, description="抓取报告时自动下载 PDF")
    browser_headless: bool = Field(default=True, description="微信报告源浏览器是否无头模式。调试时可设 false 看浏览器窗口")
    aliyunreports_year: str = Field(
        default_factory=lambda: f"{datetime.now().year}年",
        description="阿里云报告源筛选年份，例如 2025年",
    )

    @computed_field  # type: ignore[misc]
    @property
    def ai_filter_enabled(self) -> bool:
        """Whether any source has AI filtering enabled (replaces old boolean flag)."""
        return any(s.ai_filter for s in self.sources)


class WxMpSourceConfig(BaseModel):
    """一个微信公众号的订阅配置（内置 we-mp-rss 核心抓取）。"""

    name: str = Field(description="公众号显示名称，例如 机器之心")
    feed_id: Optional[str] = Field(default=None, description="公众号 mp_id（MP_WXS_ 开头）")
    enabled: bool = True
    category: Optional[str] = None
    faker_id: Optional[str] = Field(default=None, description="微信侧 fakeid。留空则自动由 feed_id 推导")


class WxMpConfig(BaseModel):
    """微信公众号源配置（内置 we-mp-rss 核心抓取，无需外部服务）。"""

    enabled: bool = True
    feeds: List[WxMpSourceConfig] = Field(default_factory=list, description="订阅的公众号列表")
    gather_content: bool = Field(default=True, description="是否抓取文章完整正文（Playwright 无头浏览器）")
    clean_html: bool = Field(default=False, description="是否对抓取的正文做 HTML 清洗")
    proxy: Optional[str] = Field(default=None, description="HTTP 代理地址（可选）")
    lic_key: Optional[str] = Field(default=None, description="cookie 加密密钥。默认取环境变量 WXMP_LIC_KEY")
    data_dir: str = Field(default="data/wxmp", description="登录态 / 二维码文件存储目录")
    max_page: int = Field(default=1, description="每个公众号抓取的页数（每页约 5 篇）")
    gather_interval: int = Field(default=3, description="抓取间隔秒数（随机 0~N，用于反爬）")


class SourcesConfig(BaseModel):
    """所有新闻数据源的配置集合。启用/停用某个源就在这里操作。"""

    github: List[GitHubSourceConfig] = Field(default_factory=list, description="GitHub 源：监控用户动态或仓库发布")
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig, description="Hacker News 源")
    rss: List[RSSSourceConfig] = Field(default_factory=list, description="RSS 订阅源列表")
    reddit: RedditConfig = Field(default_factory=RedditConfig, description="Reddit 源：监控子版块和用户")
    telegram: TelegramConfig = Field(default_factory=TelegramConfig, description="Telegram 频道源")
    twitter: Optional[TwitterConfig] = Field(default=None, description="Twitter / X 源")
    openbb: Optional[OpenBBConfig] = Field(default=None, description="OpenBB 金融数据源")
    ossinsight: OSSInsightConfig = Field(default_factory=OSSInsightConfig, description="OSS Insight 开源项目趋势")
    gdelt: Optional[GDELTConfig] = Field(default=None, description="GDELT 全球新闻事件源")
    google_news: Optional[GoogleNewsConfig] = Field(default=None, description="Google News 搜索源")
    huawei_news: Optional[HuaweiNewsConfig] = Field(default=None, description="华为新闻中心源")
    bytedance_news: Optional[ByteDanceNewsConfig] = Field(default=None, description="字节跳动 Seed 技术博客源")
    wxmp: Optional[WxMpConfig] = Field(default=None, description="微信公众号源（内置 we-mp-rss 核心抓取）")


class WebhookConfig(BaseModel):
    """Webhook 通知配置：推送到钉钉/飞书/Slack/Discord 等。"""

    url_env: Optional[str] = Field(default=None, description="存放 Webhook URL 的环境变量名，例如 DINGTALK_WEBHOOK_URL")
    request_body: Optional[Union[str, dict, list]] = Field(default=None, description="POST 请求体。可以填 JSON 对象，也支持 #{key} 模板占位符；不填则发 GET 请求")
    headers: Optional[str] = Field(default=None, description="自定义 HTTP 请求头，每行一条 Key: Value")
    delivery: str = Field(default="summary", description="投递模式：summary=仅摘要 / summary_and_items=摘要+每条详情")
    overview_position: str = Field(default="first", description="概览在消息中的位置：first=开头 / last=末尾")
    platform: str = Field(default="generic", description="目标平台：generic / feishu / lark / dingtalk / slack / discord")
    layout: str = Field(default="markdown", description="消息排版：markdown / collapsible（折叠式）")
    fallback_layout: str = Field(default="markdown", description="当请求的排版不支持时的回退排版")
    languages: Optional[List[str]] = Field(default=None, description="语言过滤，只推送指定语言的摘要。不填则推送所有 AI 语言")
    enabled: bool = False
    max_items: Optional[int] = Field(default=None, gt=0, description="推送条目上限，不填则不限制")

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
    """邮件订阅配置：通过 IMAP 接收订阅/退订指令，通过 SMTP 发送日报。"""

    imap_server: str = Field(description="IMAP 服务器地址，用于接收订阅/退订邮件")
    imap_port: int = Field(default=993, description="IMAP 端口")
    imap_enabled: bool = Field(default=True, description="是否启动 IMAP 监听")
    smtp_server: str = Field(description="SMTP 服务器地址，用于发送日报邮件")
    smtp_port: int = Field(default=465, description="SMTP 端口")
    smtp_username: Optional[str] = Field(default=None, description="SMTP 登录用户名（通常与邮箱地址相同）")
    email_address: str = Field(description="发送邮件的邮箱地址")
    password_env: str = Field(default="EMAIL_PASSWORD", description="存放邮箱密码的环境变量名")
    sender_name: str = Field(default="Horizon Daily", description="发件人显示名称")
    subscribe_keyword: str = Field(default="SUBSCRIBE", description="邮件主题含此关键词时视为订阅请求")
    unsubscribe_keyword: str = Field(default="UNSUBSCRIBE", description="邮件主题含此关键词时视为退订请求")
    enabled: bool = Field(default=False, description="是否启用邮件功能")


class CategoryGroupConfig(BaseModel):
    """分类配额组：限制某个来源分类在摘要中的最大条数。"""

    name: Optional[str] = Field(default=None, description="配额组名称（仅用于标识）")
    limit: int = Field(gt=0, description="该组最多收录多少条")
    categories: List[str] = Field(min_length=1, description="归属于该组的分类标签列表")


class FilteringConfig(BaseModel):
    """内容过滤与摘要配额配置。"""

    ai_score_threshold: float = Field(default=7.0, description="AI 评分门槛（0-10），低于此分的不进入最终摘要。设为 0 则全部保留")
    time_window_hours: int = Field(default=24, description="每次运行抓取多少小时内的内容")
    max_items: Optional[int] = Field(default=None, gt=0, description="最终摘要的全局条目上限。不填则不限")
    category_groups: Dict[str, CategoryGroupConfig] = Field(default_factory=dict, description="按分类设置配额组。key 为组名，value 为该组的分类列表和上限")
    default_group: str = Field(default="other", description="未匹配到任何配额组的分类归入此组")
    default_group_limit: Optional[int] = Field(default=None, gt=0, description="默认组的条目上限")


class Config(BaseModel):
    """Main configuration model."""

    version: str = "1.0"
    ai: AIConfig
    sources: SourcesConfig
    filtering: FilteringConfig
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None
    papers: Optional[PapersConfig] = None
    reports: Optional[ReportsConfig] = None
