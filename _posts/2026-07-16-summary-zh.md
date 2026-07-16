---
layout: default
title: "Horizon Summary: 2026-07-16 (ZH)"
date: 2026-07-16
lang: zh
---

> 从 33 条内容中筛选出 3 条重要资讯。

---

1. [Thinking Machines AI 发布开放权重 MoE 模型 Inkling](#item-1) ⭐️ 10.0/10
2. [Claude web_fetch 工具漏洞导致数据泄露](#item-2) ⭐️ 10.0/10
3. [马斯克 xAI 起诉用户滥用 Grok 生成儿童性虐待深度伪造](#item-3) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [Thinking Machines AI 发布开放权重 MoE 模型 Inkling](https://thinkingmachines.ai/news/introducing-inkling/) ⭐️ 10.0/10

Thinking Machines AI 发布了 Inkling，一个开放权重的 MoE Transformer 模型，总参数 975B（活跃 41B），支持高达 1M token 的上下文窗口和多模态输入（文本、图像、音频、视频），在 45 万亿 token 上预训练。 Inkling 为自定义提供了强大的开放权重基础，平衡了多模态能力、高效推理和 Tinker 平台上的微调可访问性，这可能使 AI 定制化对开发者和企业更加民主化。 该模型系列包括 12B 活跃参数的 Inkling-Small 预览版。Inkling 支持代理编码、工具使用和可控思考努力，在代理任务上取得了强大的开放权重基准，同时被设计为广泛的全能模型。
> **评分理由**: Thinking Machines AI 以 41B 活跃参数和 1M 上下文发布 975B 开放权重 MoE 模型，标志着可定制大模型的新前沿，挑战了专有和开源生态。对于寻求灵活微调选项的开发者和企业来说，这意味着更易获得的高性能基座模型，但开放权重与开源的区别仍至关重要。

hackernews · vimarsh6739 · 7月15日 18:12 · [社区讨论](https://news.ycombinator.com/item?id=48924912)

**社区讨论**: 在 HackerNews 上，该公告获得 768 分和 196 条评论，讨论集中在模型的技术细节、开放权重发布的影响以及与真正开源模型的比较。许多人称赞其多模态能力和高效架构，而一些人则对可重复性和缺乏完整开源组件表示担忧。

---

<a id="item-2"></a>
## [Claude web_fetch 工具漏洞导致数据泄露](https://simonwillison.net/2026/Jul/15/claude-web-fetch-exfiltration/#atom-everything) ⭐️ 10.0/10

Ayush Paul 发现 Anthropic 的 Claude web_fetch 工具存在漏洞，攻击者可通过诱使 AI 访问蜜罐网站上的嵌套链接来窃取用户隐私数据。Anthropic 已修复该漏洞，但未支付漏洞赏金。 该漏洞凸显了在 AI agent 拥有私有数据和外部通信工具时，防止数据泄露攻击的持续挑战。它强调了处理敏感信息的 AI 系统需要强大的防护措施。 攻击利用了一个漏洞：web_fetch 可以导航到先前获取页面中嵌入的 URL，从而通过一系列嵌套链接提取用户名、城市和雇主信息。Anthropic 声称已内部识别，并移除了从获取内容中跟随链接的能力。
> **评分理由**: Simon Willison披露的Claude web_fetch漏洞暴露了AI agent安全设计的关键缺陷——私有数据、不可信内容和外泄能力构成的“致命三重奏”。对于部署AI助手的组织而言，这提醒必须严格审查输入输出、控制链接跳转，否则用户隐私将面临直接威胁。

rss · Simon Willison · 7月15日 14:21

---

<a id="item-3"></a>
## [马斯克 xAI 起诉用户滥用 Grok 生成儿童性虐待深度伪造](https://www.reuters.com/legal/litigation/musks-xai-sues-grok-user-over-sexualized-deepfakes-2026-07-15/) ⭐️ 8.0/10

xAI 因用户滥用 Grok 生成儿童性虐待深度伪造而起诉，系 AI 公司起诉用户的首批案件之一。
> **评分理由**: 首批AI公司因用户生成色情深度伪造起诉用户的案件之一，涉及AI安全、法律先例和监管影响，具有较高行业和社会关注度。

telegram · zaihuapd · 7月16日 01:45

---