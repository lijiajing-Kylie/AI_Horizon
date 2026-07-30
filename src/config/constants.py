"""Horizon 代码常量配置表 — 所有可调参数集中到此文件。

**改参数就改这里**，不需要去翻各个代码文件。
"""

# ── AI 供应商默认值 ──────────────────────────────────────────────────────────
# 每项为一个 dict: {"model": 默认模型名, "api_key_env": API 密钥的环境变量名}
# 新增供应商时在这里加一条就行
AI_PROVIDER_DEFAULTS: dict = {
    # Anthropic — 用 claude-3-5-sonnet，密钥从 ANTHROPIC_API_KEY 环境变量读
    "anthropic": {"model": "claude-3-5-sonnet-20241022", "api_key_env": "ANTHROPIC_API_KEY"},
    # OpenAI — 用 gpt-4，密钥从 OPENAI_API_KEY 环境变量读
    "openai":    {"model": "gpt-4",                      "api_key_env": "OPENAI_API_KEY"},
    # Azure OpenAI — 用 gpt-4，密钥从 AZURE_OPENAI_API_KEY 环境变量读
    "azure":     {"model": "gpt-4",                      "api_key_env": "AZURE_OPENAI_API_KEY"},
    # 阿里云通义千问 — 用 qwen-plus，密钥从 DASHSCOPE_API_KEY 环境变量读
    "ali":       {"model": "qwen-plus",                  "api_key_env": "DASHSCOPE_API_KEY"},
    # Google Gemini — 用 gemini-1.5-flash，密钥从 GOOGLE_API_KEY 环境变量读
    "gemini":    {"model": "gemini-1.5-flash",           "api_key_env": "GOOGLE_API_KEY"},
    # 字节豆包 — 用 doubao-pro-32k，密钥从 DOUBAO_API_KEY 环境变量读
    "doubao":    {"model": "doubao-pro-32k",             "api_key_env": "DOUBAO_API_KEY"},
    # MiniMax — 用 MiniMax-Text-01，密钥从 MINIMAX_API_KEY 环境变量读
    "minimax":   {"model": "MiniMax-Text-01",            "api_key_env": "MINIMAX_API_KEY"},
    # DeepSeek — 用 deepseek-chat，密钥从 DEEPSEEK_API_KEY 环境变量读
    "deepseek":  {"model": "deepseek-chat",              "api_key_env": "DEEPSEEK_API_KEY"},
    # Ollama 本地部署 — 用 llama3.1，无需密钥（空字符串表示不检查密钥）
    "ollama":    {"model": "llama3.1",                   "api_key_env": ""},
}

# ── AI 厂商默认 API 地址（仅 OpenAl 兼容客户端用）───────────────────────────
# 当 config 里 base_url 为空时，从这里取默认值
# key 用供应商字符串（与 AI_PROVIDER_DEFAULTS 的 key 对应）
DEFAULT_BASE_URLS: dict = {
    "ali":      "https://dashscope.aliyuncs.com/compatible-mode/v1",     # 阿里云通义千问
    "deepseek": "https://api.deepseek.com",                               # DeepSeek
    "doubao":   "https://ark.cn-beijing.volces.com/api/v3",               # 字节豆包
    "minimax":  "https://api.minimax.io/v1",                              # MiniMax
    "ollama":   "http://localhost:11434/v1",                              # Ollama 本地
}

# API 地址的环境变量回退 — 设了环境变量可以覆盖 DEFAULT_BASE_URLS
# 格式: {供应商: (环境变量名1, 环境变量名2, ...)}，按顺序取第一个有值的
BASE_URL_ENVS: dict = {
    "ollama": ("HORIZON_OLLAMA_BASE_URL", "OLLAMA_BASE_URL", "OLLAMA_HOST"),
}

# ── AI 厂商特性标记 ──────────────────────────────────────────────────────────
# 不支持 response_format（需强制 JSON 输出时会被跳过）
NO_RESPONSE_FORMAT: set = {"minimax"}

# 温度参数需要裁剪到 (0,1] 范围内的供应商
TEMP_CLAMP: set = {"minimax"}

# Azure reasoning 模型列表 — 这些模型需要传 max_completion_tokens 而非 max_tokens
# Azure 的 deployment 名由用户自定义，这里是 best-effort 匹配
MODELS_REQUIRING_MAX_COMPLETION_TOKENS: tuple = ("o1", "o3", "o4", "gpt-5")

# ── 来源角色权威性排序 ───────────────────────────────────────────────────────
# 数字越小越优先。合并多条同内容来源时，选优先级最高的作为主来源。
# 来源类型		示例					优先级
# 官方公司博客	openai.com/blog			1
# 官方产品页	github.com				2
# 官方模型页	huggingface.co/models	3
# 论文			arxiv.org				4
# 社交帖子		x.com/twitter			5
# 媒体报道		techcrunch.com			6
# 专家博客		simonwillison.net		7
# 社区讨论		stackoverflow.com		8
# 聚合器		news.ycombinator.com	9
# 未知			—						10
SOURCE_ROLE_PRIORITY: dict = {
    "official_company_blog": 1,
    "official_product_page": 2,
    "official_model_page":   3,
    "paper":                 4,
    "social_post":           5,
    "media_report":          6,
    "expert_blog":           7,
    "community_discussion":  8,
    "aggregator":            9,
    "unknown":              10,
}

# ── 域名→角色映射 ────────────────────────────────────────────────────────────
# 用于 classify_url_role() 根据 URL 判断来源类型。
# 前面的匹配优先于后面的（python 的 for 循环顺序匹配）。
ROLE_DOMAIN_MAP: list = [
    # ── 官方模型/代码托管 ──
    ("github.com",           "official_model_page"),
    ("huggingface.co",       "official_model_page"),
    ("modelscope.cn",        "official_model_page"),
    ("gitlab.com",           "official_model_page"),
    ("bitbucket.org",        "official_model_page"),
    # ── 论文 ──
    ("arxiv.org",            "paper"),
    ("arxiv.org/abs",        "paper"),
    ("openreview.net",       "paper"),
    ("paperswithcode.com",   "paper"),
    ("proceedings.neurips.cc", "paper"),
    ("proceedings.mlr.press",  "paper"),
    ("dl.acm.org",           "paper"),
    ("ieeexplore.ieee.org",  "paper"),
    ("aclanthology.org",     "paper"),
    ("research.google",      "paper"),
    ("ai.meta.com/research", "paper"),
    ("cdn.openai.com/papers","paper"),
    # ── 官方公司博客 ──
    ("openai.com",           "official_company_blog"),
    ("anthropic.com",        "official_company_blog"),
    ("deepmind.google",      "official_company_blog"),
    ("blog.google",          "official_company_blog"),
    ("ai.googleblog.com",    "official_company_blog"),
    ("ai.meta.com/blog",     "official_company_blog"),
    ("about.fb.com",         "official_company_blog"),
    ("engineering.fb.com",   "official_company_blog"),
    ("aws.amazon.com/blogs", "official_company_blog"),
    ("azure.microsoft.com",  "official_company_blog"),
    ("blogs.microsoft.com",  "official_company_blog"),
    ("nvidia.com/blog",      "official_company_blog"),
    ("developer.nvidia.com", "official_company_blog"),
    ("blog.x.ai",            "official_company_blog"),
    ("x.ai/blog",            "official_company_blog"),
    ("mistral.ai",           "official_company_blog"),
    ("cohere.com",           "official_company_blog"),
    ("stability.ai",         "official_company_blog"),
    ("deepseek.com",         "official_company_blog"),
    ("tech.meituan.com",     "official_company_blog"),
    ("seed.bytedance.com",   "official_company_blog"),
    ("qwenlm.github.io",     "official_company_blog"),
    ("huggingface.co/blog",  "official_company_blog"),
    # ── 专家博客 ──
    ("simonwillison.net",    "expert_blog"),
    ("karpathy.ai",          "expert_blog"),
    ("lilianweng.github.io", "expert_blog"),
    ("ycombinator.com",      "expert_blog"),
    ("gwern.net",            "expert_blog"),
    ("colah.github.io",      "expert_blog"),
    ("jalammar.github.io",   "expert_blog"),
    # ── 聚合器 ──
    ("news.ycombinator.com", "aggregator"),
    ("reddit.com",           "aggregator"),
    ("lobste.rs",            "aggregator"),
    ("producthunt.com",      "aggregator"),
    ("techmeme.com",         "aggregator"),
    # ── 媒体报道 ──
    ("techcrunch.com",       "media_report"),
    ("theverge.com",         "media_report"),
    ("arstechnica.com",      "media_report"),
    ("wired.com",            "media_report"),
    ("venturebeat.com",      "media_report"),
    ("zdnet.com",            "media_report"),
    ("theregister.com",      "media_report"),
    ("bloomberg.com",        "media_report"),
    ("reuters.com",          "media_report"),
    ("techinasia.com",       "media_report"),
    ("36kr.com",             "media_report"),
    ("jiqizhixin.com",       "media_report"),
    ("theinformation.com",   "media_report"),
    ("infoq.com",            "media_report"),
    ("thenewstack.io",       "media_report"),
    # ── 社交帖子 ──
    ("x.com",                "social_post"),
    ("twitter.com",          "social_post"),
    ("t.me",                 "social_post"),
    ("telegram.org",         "social_post"),
    ("linkedin.com",         "social_post"),
    ("weibo.com",            "social_post"),
    ("zhihu.com",            "social_post"),
    # ── 社区讨论 ──
    ("stackoverflow.com",        "community_discussion"),
    ("discord.com",              "community_discussion"),
    ("discuss.pytorch.org",      "community_discussion"),
    ("community.openai.com",     "community_discussion"),
    ("huggingface.co/spaces",    "community_discussion"),
]

# ── 阿里云报告源 — 浏览器默认值 ──────────────────────────────────────────────
# 用于 src/reports/sources/aliyunreports.py
# 抓取 aliyun.com/reports 需要用 Playwright 浏览器渲染
ALIYUNREPORTS_DEFAULTS: dict = {
    "content_category": "报告",          # 内容分类过滤（中文）
    "tech_category": "人工智能",          # 技术分类过滤（中文）
    "browser_profile_dir": "data/aliyun_profile",  # 浏览器持久化会话目录（登录态存这里）
    "headless": True,                    # 无头模式（True=不显示浏览器窗口）
    "max_retries": 3,                    # 抓取失败时重试次数
    "timeout_ms": 60000,                 # 每次请求超时（毫秒）
    "delay_between_requests": 0.5,       # 两次请求之间的间隔（秒）
}

# ── 微信报告源 — 默认值 ──────────────────────────────────────────────────────
# 用于 src/reports/sources/wxmp.py
# 从 we-mp-rss 服务获取微信公众号文章作为报告
WXMP_REPORT_DEFAULTS: dict = {
    "max_age_days": 7,      # 最多获取多少天内的文章
    "fetch_limit": 100,     # 每次最多获取多少篇
}
