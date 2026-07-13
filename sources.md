---
layout: default
title: Sources
---

# 数据源清单

本文档整理 `data/config.json` 中当前配置的全部数据源，按采集器类型分组，并对每个源做简要中文说明，方便长期维护时对照增删。若增删了源，请同步更新本文档。

统计：共 85 个已配置数据源，79 个当前启用，7 种采集器类型。

## GitHub Releases

| 仓库 | 简介 | 分类 | 状态 |
|---|---|---|---|
| `sgl-project/sglang` | 高性能 LLM 推理引擎发布 | github-official | 启用 |
| `vllm-project/vllm` | vLLM 推理引擎版本更新 | github-official | 启用 |
| `YD4223/aihub` | 国内博主的 AI 资源仓库 | chinese-blogger | 启用 |

## Hacker News

| 参数 | 值 |
|---|---|
| 抓取范围 | Top 30 stories |
| 最低分数 | min_score ≥ 100 |
| 分类 | foreign-community |
| 简介 | 科技极客社区热门讨论 |

## Reddit

统一参数：`sort=hot`，`time_filter=day`，`fetch_limit=15`，`min_score≥60`。

| Subreddit | 简介 | 分类 | 状态 |
|---|---|---|---|
| r/MachineLearning | 机器学习学术社区 | foreign-community | 启用 |
| r/LocalLLaMA | 本地部署 LLM 爱好者社区 | foreign-community | 启用 |
| r/StableDiffusion | AI 绘画/图像生成社区 | foreign-community | 启用 |
| r/artificial | AI 综合讨论社区 | foreign-community | 启用 |
| r/OpenAI | OpenAI 用户讨论社区 | foreign-community | 启用 |
| r/ChatGPTCoding | AI 辅助编程讨论社区 | foreign-community | 启用 |
| r/ChatGPT | ChatGPT 使用讨论社区 | foreign-community | 启用 |
| r/technology | 科技新闻综合社区 | foreign-media | 启用 |

## RSS 订阅源

按 `category` 字段分组；「状态」为 `disabled` 的行对应 `data/config.json` 中 `enabled: false`。

### 海外官方博客 — foreign-official（12 条，10 启用）

| 名称 | 简介 | 状态 |
|---|---|---|
| Anthropic Research | Anthropic 官方研究博客 | 关闭 |
| BAIR Blog | 伯克利 AI 研究院博客 | 启用 |
| GitHub AI & ML | GitHub 官方 AI 资讯 | 启用 |
| GitHub Changelog | GitHub 产品更新日志 | 启用 |
| Google AI Blog | 谷歌官方 AI 博客 | 启用 |
| Google DeepMind | DeepMind 官方研究博客 | 启用 |
| Hugging Face Blog | HuggingFace 官方博客 | 启用 |
| OpenAI Blog | OpenAI 官方博客 | 启用 |
| OpenAI News | OpenAI 官方新闻 | 启用 |
| OpenAI Skills | OpenAI 技能库更新 | 启用 |
| Stanford AI Lab (SAIL) | 斯坦福 AI 实验室博客 | 启用 |
| The Batch | 吴恩达团队 AI 周报 | 关闭 |

### 海外科技媒体 — foreign-media（5 条，4 启用）

| 名称 | 简介 | 状态 |
|---|---|---|
| Ars Technica AI | 老牌科技媒体 AI 板块 | 启用 |
| TechCrunch AI | 硅谷创投媒体 AI 板块 | 启用 |
| The Economist | 经济学人时政媒体 | 关闭 |
| The Verge | 科技生活方式媒体 | 启用 |
| VentureBeat AI | 企业科技媒体 AI 板块 | 启用 |

### 海外社区 — foreign-community（1 条 RSS，关闭；另见上方 HN / Reddit）

| 名称 | 简介 | 状态 |
|---|---|---|
| Lobsters | 程序员精选链接社区 | 关闭 |

### 海外独立博主 — foreign-blogger（12 条，全部启用）

| 名称 | 简介 | 状态 |
|---|---|---|
| Ahead of AI (Sebastian Raschka) | AI 研究者个人博客 | 启用 |
| Chip Huyen | 机器学习工程师博客 | 启用 |
| Interconnects | AI 政策/技术评论博客 | 启用 |
| Jay Alammar | AI 可视化讲解博主 | 启用 |
| Latent Space | AI 工程师访谈/评论 | 启用 |
| Lilian Weng | 前 OpenAI 研究员博客 | 启用 |
| Machine Learning Mastery | 机器学习教程博客 | 启用 |
| Sebastian Raschka | 深度学习研究者博客 | 启用 |
| Simon Willison | 开源开发者技术博客 | 启用 |
| The Gradient | AI 学术评论杂志 | 启用 |
| The Pragmatic Engineer | 资深工程师职业博客 | 启用 |
| Matthew Garrett / mjg59 | Linux 内核开发者博客 | 启用 |

### AI 资讯聚合 — ai-aggregator（8 条，全部启用）

| 名称 | 简介 | 状态 |
|---|---|---|
| AI Hot | AI 热点资讯聚合 | 启用 |
| AI News | AI 行业新闻聚合站 | 启用 |
| AI Weekly | AI 资讯周刊邮件 | 启用 |
| AINews (Buttondown) | AI 新闻邮件简报 | 启用 |
| Anavem.com | AI 资讯聚合站 | 启用 |
| Last Week in AI | AI 周报播客配套博客 | 启用 |
| MarkTechPost | AI 技术新闻聚合站 | 启用 |
| The Decoder | AI 科技新闻站 | 启用 |

### 中文媒体 / 聚合 / 官方（5 条，全部启用）

| 名称 | 简介 | 分类 | 状态 |
|---|---|---|---|
| InfoQ CN | 中文技术媒体 | chinese-media | 启用 |
| 36氪 | 创投科技媒体 | chinese-media | 启用 |
| 少数派 | 数字生活媒体 | chinese-media | 启用 |
| ReadHub | 中文科技资讯聚合 | chinese-aggregator | 启用 |
| 美团技术团队 | 美团技术团队博客 | chinese-official | 启用 |

### 微信公众号 — wechat-account（28 条，全部启用）

经由第三方 RSS 转换服务（`decemberpei.cyou` / `wechat2rss.xlab.app`）订阅。

| 名称 | 简介 | 状态 |
|---|---|---|
| 机器之心 | AI 领域头部媒体 | 启用 |
| 深科技 | MIT 科技评论中文版 | 启用 |
| PaperWeekly | NLP/AI 论文分享号 | 启用 |
| 计算机视觉life | 计算机视觉技术号 | 启用 |
| AI前线 | InfoQ 旗下 AI 媒体 | 启用 |
| 夕小瑶科技说 | AI 技术自媒体 | 启用 |
| 海外独角兽 | 海外科技投研媒体 | 启用 |
| 甲子光年 | 科技产业媒体 | 启用 |
| 极智俱乐部 | AI 技术分享号 | 启用 |
| 量子位 | 头部 AI 科技媒体 | 启用 |
| 新智元 | 头部 AI 科技媒体 | 启用 |
| 晚点 LatePost | 深度商业报道媒体 | 启用 |
| 36氪Pro | 36氪付费栏目 | 启用 |
| 虎嗅APP | 商业科技媒体 | 启用 |
| 极客公园 | 科技创新媒体 | 启用 |
| APPSO | 数字生活科技媒体 | 启用 |
| 爱范儿 | 科技生活方式媒体 | 启用 |
| 差评 | 泛科技评测媒体 | 启用 |
| 钛媒体 | 科技财经媒体 | 启用 |
| 阿里云开发者 | 阿里云官方技术号 | 启用 |
| 腾讯技术工程 | 腾讯官方技术号 | 启用 |
| 前端之巅 | 前端技术社区号 | 启用 |
| 架构师之路 | 后端架构技术号 | 启用 |
| GitHubDaily | 开源项目推荐号 | 启用 |
| 经纬创投 | VC 机构投研号 | 启用 |
| 红杉汇 | 红杉资本投研号 | 启用 |
| 乱翻书 | 科技评论播客号 | 启用 |
| Founder Park | 极客公园旗下创业号 | 启用 |

## 已关闭 / 未配置的采集器

| 采集器 | 状态 | 说明 |
|---|---|---|
| Telegram | 已配置，关闭 | `enabled: false`，`channels` 列表为空 |
| OSSInsight | 已配置，关闭 | `enabled: false`（GitHub Trending 类，`min_stars` 5 / `max_items` 30） |
| Twitter / X | 未接入 | 配置为 `null` |
| OpenBB | 未接入 | 配置为 `null`（金融资讯） |
| GDELT | 未接入 | 配置为 `null` |
| Google News | 未接入 | 配置为 `null` |

## 影响简报生成的流水线参数

| 参数 | 值 |
|---|---|
| AI Provider | deepseek / deepseek-v4-flash |
| `ai_score_threshold` | ≥ 7.0 |
| `time_window_hours` | 24h |
| `max_items`（简报上限） | 30 |
| 输出语言 | zh |
| Webhook | dingtalk（关闭中） |
