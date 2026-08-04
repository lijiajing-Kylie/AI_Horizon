"""
Horizon 配置文件 — 所有可调参数都在这里。

改配置就改这个文件，不用去翻 JSON 或代码。
支持 Python 注释（# 开头）和动态值（os.getenv、datetime.now 等）。
"""

import os

# ── CI 环境检测（GitHub Actions 自动设 CI=true）────────────────────────────
# 在 CI 中禁用依赖本地服务的源（we-mp-rss、Twitter cookie 等），
# 避免无谓的连接失败和超时。
_IN_CI = os.getenv("CI") == "true"

# ═══════════════════════════════════════════════════════════════════════════════
# AI 供应商配置
# ═══════════════════════════════════════════════════════════════════════════════

ai = {
    # 供应商：anthropic / openai / azure / ali / gemini / doubao / minimax / deepseek / ollama
    "provider": "deepseek",
    # 模型名。各厂商默认值在 src/config/constants.py
    "model": "deepseek-v4-flash",
    # API 密钥从哪个环境变量读
    "api_key_env": "DEEPSEEK_API_KEY",
    # 自定义 API 地址。不填则用默认的（默认值在 constants.py 的 DEFAULT_BASE_URLS）
    "base_url": None,
    # 内容分析和丰富的并发数
    "analysis_concurrency": 5,
    "enrichment_concurrency": 3,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 数据源配置 — 启用/停用/添加就在这里操作
# ═══════════════════════════════════════════════════════════════════════════════

sources = {

    # ── RSS 订阅源 ────────────────────────────────────────────────────────
    # 加新源：在 rss 列表里加一条 {"name": "名字", "url": "feed地址", "category": "分类"}
    "rss": [
        # 外媒官方
        {"name": "BAIR Blog",               "url": "https://bair.berkeley.edu/blog/feed.xml",                   "category": "foreign-official"},
        {"name": "GitHub AI & ML",          "url": "https://github.blog/ai-and-ml/feed/",                       "category": "foreign-official"},
        {"name": "GitHub Changelog",        "url": "https://github.blog/changelog/feed/",                       "category": "foreign-official"},
        {"name": "Google AI Blog",          "url": "https://blog.google/innovation-and-ai/technology/ai/rss/",  "category": "foreign-official"},
        {"name": "Google DeepMind",         "url": "https://deepmind.google/blog/rss.xml",                       "category": "foreign-official"},
        {"name": "Hugging Face Blog",       "url": "https://huggingface.co/blog/feed.xml",                      "category": "foreign-official"},
        {"name": "OpenAI Blog",             "url": "https://openai.com/blog/rss.xml",                           "category": "foreign-official"},
        {"name": "OpenAI News",             "url": "https://openai.com/news/rss.xml",                           "category": "foreign-official"},
        {"name": "OpenAI Skills",           "url": "https://github.com/openai/skills/commits/main.atom",        "category": "foreign-official"},
        {"name": "Stanford AI Lab (SAIL)",  "url": "https://ai.stanford.edu/blog/feed.xml",                    "category": "foreign-official"},
        # 国外技术媒体
        {"name": "Ars Technica AI",         "url": "https://arstechnica.com/ai/feed/",                          "category": "foreign-media"},
        {"name": "TechCrunch AI",           "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "foreign-media"},
        {"name": "The Verge",               "url": "https://www.theverge.com/rss/index.xml",                    "category": "foreign-media"},
        {"name": "VentureBeat AI",          "url": "https://venturebeat.com/category/ai/feed/",                 "category": "foreign-media"},
        # 专家博客
        {"name": "Ahead of AI (Sebastian Raschka)", "url": "https://magazine.sebastianraschka.com/feed",   "category": "foreign-blogger"},
        {"name": "Chip Huyen",              "url": "https://huyenchip.com/feed.xml",                            "category": "foreign-blogger"},
        {"name": "Interconnects",           "url": "https://www.interconnects.ai/feed",                         "category": "foreign-blogger"},
        {"name": "Jay Alammar",             "url": "https://jalammar.github.io/feed.xml",                       "category": "foreign-blogger"},
        {"name": "Latent Space",            "url": "https://www.latent.space/feed",                             "category": "foreign-blogger"},
        {"name": "Lilian Weng",             "url": "https://lilianweng.github.io/index.xml",                    "category": "foreign-blogger"},
        {"name": "Machine Learning Mastery","url": "https://machinelearningmastery.com/feed/",                  "category": "foreign-blogger"},
        {"name": "Sebastian Raschka",       "url": "https://sebastianraschka.com/rss_feed.xml",                 "category": "foreign-blogger"},
        {"name": "Simon Willison",          "url": "https://simonwillison.net/atom/everything/",                "category": "foreign-blogger"},
        {"name": "The Gradient",            "url": "https://thegradient.pub/rss/",                              "category": "foreign-blogger"},
        {"name": "The Pragmatic Engineer",  "url": "https://newsletter.pragmaticengineer.com/feed",             "category": "foreign-blogger"},
        {"name": "Matthew Garrett / mjg59", "url": "http://mjg59.dreamwidth.org/data/rss",                     "category": "foreign-blogger"},
        # AI 聚合
        {"name": "AI Hot",                  "url": "https://aihot.virxact.com/feed.xml",                        "category": "ai-aggregator"},
        {"name": "AI News",                 "url": "https://www.artificialintelligence-news.com/feed/",         "category": "ai-aggregator"},
        {"name": "AI Weekly",               "url": "https://aiweekly.co/issues.rss",                            "category": "ai-aggregator"},
        {"name": "AINews (Buttondown)",     "url": "https://buttondown.com/ainews/rss",                        "category": "ai-aggregator"},
        {"name": "Anavem.com",              "url": "https://www.anavem.com/en/rss.xml",                         "category": "ai-aggregator"},
        {"name": "Last Week in AI",         "url": "https://lastweekin.ai/feed",                                "category": "ai-aggregator"},
        {"name": "MarkTechPost",            "url": "https://www.marktechpost.com/feed/",                        "category": "ai-aggregator", "extraction_mode": "browser"},
        {"name": "The Decoder",             "url": "https://the-decoder.com/feed/",                             "category": "ai-aggregator"},
        # 中文媒体
        {"name": "InfoQ CN",                "url": "https://www.infoq.cn/feed",                                 "category": "chinese-media"},
        {"name": "36氪",                    "url": "https://36kr.com/feed",                                     "category": "chinese-media", "extraction_mode": "browser"},
        {"name": "少数派",                  "url": "https://sspai.com/feed",                                    "category": "chinese-media"},
        {"name": "ReadHub",                 "url": "https://readhub.cn/rss",                                    "category": "chinese-aggregator", "extraction_mode": "browser"},
        # 中文官方
        {"name": "美团技术团队",            "url": "https://tech.meituan.com/rss.xml",                          "category": "chinese-official"},
    ],

    # ── 华为新闻中心 ────────────────────────────────────────────────────
    "huawei_news": {
        "url": "https://www.huawei.com/cn/news",
        "fetch_limit": 50,
        "category": "chinese-official",
    },

    # ── 字节跳动 Seed 博客 ──────────────────────────────────────────────
    "bytedance_news": {
        "url": "https://seed.bytedance.com/zh/blog",
        "fetch_limit": 50,
        "category": "chinese-official",
    },

    # ── GitHub ───────────────────────────────────────────────────────────
    "github": [
        {"type": "repo_releases", "owner": "sgl-project",  "repo": "sglang",  "category": "github-official"},
        {"type": "repo_releases", "owner": "vllm-project",  "repo": "vllm",   "category": "github-official"},
        {"type": "repo_releases", "owner": "YD4223",       "repo": "aihub",   "category": "chinese-blogger"},
    ],

    # ── Hacker News ──────────────────────────────────────────────────────
    "hackernews": {
        "fetch_top_stories": 30,   # 取前 N 条
        "min_score": 100,          # 最低分数门槛
        "category": "foreign-community",
    },

    # ── Reddit ───────────────────────────────────────────────────────────
    "reddit": {
        "subreddits": [
            {"subreddit": "MachineLearning",  "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "LocalLLaMA",       "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "StableDiffusion",  "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "artificial",       "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "OpenAI",           "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "ChatGPTCoding",    "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
            {"subreddit": "technology",       "fetch_limit": 15, "min_score": 60, "category": "foreign-media"},
            {"subreddit": "ChatGPT",          "fetch_limit": 15, "min_score": 60, "category": "foreign-community"},
        ],
        "fetch_comments": 10,  # 每条帖子抓取评论数，0 为不抓
    },

    # ── Telegram（已关闭）──
    "telegram": {"enabled": False, "channels": []},

    # ── OSS Insight 趋势（已关闭）──
    "ossinsight": {"enabled": False},

    # ── Twitter / X（通过 Playwright + Cookie）─────────────────────
    # 使用前准备：
    #   1. uv sync --extra twitter && uv run playwright install chromium
    #   2. 浏览器装 EditThisCookie 等工具，登录 x.com 后导出 Cookie 为
    #      data/x_cookies_karpathy.json（文件名 x_cookies_*.json 即可）
    "twitter": {
        "enabled": True,
        "mode": "playwright",
        "users": [
            "karpathy",          # Andrej Karpathy
            "fchollet",          # François Chollet
            "simonw",            # Simon Willison
            "rasbt",             # Sebastian Raschka
            "dair_ai",           # DAIR.AI
            "OpenAI",            # OpenAI
            "AnthropicAI",       # Anthropic
            "GoogleDeepMind",    # Google DeepMind
            "GoogleAI",          # Google AI
            "AIatMeta",          # Meta AI
            "MistralAI",         # Mistral AI
            "huggingface",       # Hugging Face
            "NVIDIAAI",          # NVIDIA AI
            "MicrosoftAI",       # Microsoft AI
            "xai",               # xAI
            "cohere",            # Cohere
            "AI21Labs",          # AI21 Labs
        ],
        "fetch_limit": 10,
        "fetch_reply_text": False,
    },

    # ── 微信公众号（内置 we-mp-rss 核心抓取，无需外部服务）────────────────
    "wxmp": {
        "enabled": not _IN_CI,     # CI 中无微信登录态，自动关闭
        "gather_content": True,    # 抓取文章完整正文（需 Playwright chromium）
        "data_dir": "data/wxmp",   # 登录态 / 二维码存放目录
        "feeds": [
            # 加公众号就在这里加一条，feed_id 是公众号的 MP_WXS_ id
            {"name": "36氪Pro",       "feed_id": "MP_WXS_3519073339"},
            {"name": "AI前线",        "feed_id": "MP_WXS_3554086560"},
            {"name": "APPSO",         "feed_id": "MP_WXS_2392024520"},
            {"name": "Founder Park",  "feed_id": "MP_WXS_3895742803"},
            {"name": "GitHubDaily",   "feed_id": "MP_WXS_3019715205"},
            {"name": "PaperWeekly",   "feed_id": "MP_WXS_3201788143"},
            {"name": "中国信通院CAICT","feed_id": "MP_WXS_2393546305"},
            {"name": "乱翻书",        "feed_id": "MP_WXS_2390738373"},
            {"name": "前端之巅",      "feed_id": "MP_WXS_3513713196"},
            {"name": "夕小瑶科技说",  "feed_id": "MP_WXS_3207765945"},
            {"name": "字节跳动",      "feed_id": "MP_WXS_3550827996"},
            {"name": "字节跳动技术团队","feed_id": "MP_WXS_3253632141"},
            {"name": "小米技术",      "feed_id": "MP_WXS_3510410326"},
            {"name": "我爱计算机视觉", "feed_id": "MP_WXS_3201156411"},
            {"name": "新智元",         "feed_id": "MP_WXS_3271041950"},
            {"name": "晚点LatePost",   "feed_id": "MP_WXS_3572959446"},
            {"name": "机器之心",       "feed_id": "MP_WXS_3073282833"},
            {"name": "极客公园",       "feed_id": "MP_WXS_1304308441"},
            {"name": "架构师之路",     "feed_id": "MP_WXS_2398610099"},
            {"name": "海外独角兽",     "feed_id": "MP_WXS_3869640945"},
            {"name": "深科技",         "feed_id": "MP_WXS_3218265689"},
            {"name": "甲子光年",       "feed_id": "MP_WXS_3599245772"},
            {"name": "腾讯技术工程",   "feed_id": "MP_WXS_2398602260"},
            {"name": "腾讯玄武实验室", "feed_id": "MP_WXS_3094624240"},
            {"name": "腾讯研究院",     "feed_id": "MP_WXS_2399148061"},
            {"name": "计算机视觉life", "feed_id": "MP_WXS_3219739384"},
            {"name": "通义实验室",     "feed_id": "MP_WXS_3911621034"},
            {"name": "量子位",         "feed_id": "MP_WXS_3236757533"},
            {"name": "钛媒体",         "feed_id": "MP_WXS_2398235760"},
            {"name": "阿里云",         "feed_id": "MP_WXS_3086283381"},
            {"name": "阿里技术",       "feed_id": "MP_WXS_3885737868"},
            {"name": "阿里研究院",     "feed_id": "MP_WXS_2395844153"},
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# 过滤和评分
# ═══════════════════════════════════════════════════════════════════════════════

filtering = {
    "ai_score_threshold": 7.0,   # AI 评分门槛（0-10），低于此分不进摘要
    "time_window_hours": 24,     # 每次抓取多少小时内的内容
    "max_items": 30,             # 摘要全局条目上限，None 为不限制
}

# ═══════════════════════════════════════════════════════════════════════════════
# 论文库
# ═══════════════════════════════════════════════════════════════════════════════

papers = {
    "enabled": True,
    "openalex": {"enabled": True},          # 经典论文源（基于种子列表）
    "huggingface": {"enabled": True, "top_n": 30},  # HF 每日热门论文
}

# ═══════════════════════════════════════════════════════════════════════════════
# 研究报告库
# ═══════════════════════════════════════════════════════════════════════════════

reports = {
    "enabled": True,
    # 报告源列表：每个项目为 {"name": 源名, "ai_filter": 是否AI过滤}
    "sources": [
        "aliyunreports",                                # 阿里云报告
        {"name": "wxmp", "ai_filter": True,             # 微信公众号报告
         "account_names": ["腾讯研究院", "阿里研究院", "__featured__"]},
    ],
    "aliyunreports_year": "2025年",  # 阿里云报告筛选年份
}

# ═══════════════════════════════════════════════════════════════════════════════
# Webhook 通知
# ═══════════════════════════════════════════════════════════════════════════════

webhook = {
    "url_env": "DINGTALK_WEBHOOK_URL",   # Webhook URL 从哪个环境变量读
    "platform": "dingtalk",               # 平台：generic / feishu / lark / dingtalk / slack / discord
    "delivery": "summary_and_items",      # 投递模式：summary（仅摘要）/ summary_and_items（摘要+每条详情）
    "layout": "markdown",                 # 排版：markdown / collapsible
    "languages": ["zh"],
    "enabled": False,
}
