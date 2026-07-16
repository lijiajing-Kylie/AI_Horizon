---
layout: default
title: "Horizon Summary: 2026-07-16 (EN)"
date: 2026-07-16
lang: en
---

> From 33 items, 3 important content pieces were selected

---

1. [Thinking Machines AI Releases Open-Weights MoE Model Inkling](#item-1) ⭐️ 10.0/10
2. [Claude web_fetch tool vulnerability enables data exfiltration](#item-2) ⭐️ 10.0/10
3. [🤖 马斯克 xAI 起诉用户滥用 Grok 生成儿童性虐待深度伪造](#item-3) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [Thinking Machines AI Releases Open-Weights MoE Model Inkling](https://thinkingmachines.ai/news/introducing-inkling/) ⭐️ 10.0/10

Thinking Machines AI released Inkling, an open-weights Mixture-of-Experts transformer with 975B total parameters (41B active), supporting up to 1M token context and multimodal inputs (text, images, audio, video), pretrained on 45 trillion tokens. Inkling provides a strong open-weights foundation for customization, balancing multimodal capabilities, efficient reasoning, and fine-tuning accessibility on Tinker, which could democratize AI customization for developers and enterprises. The model family includes Inkling-Small preview with 12B active parameters. Inkling supports agentic coding, tool use, and controllable thinking effort, and achieved strong open-weights benchmarks on agentic tasks while being designed as a broad generalist.
> **Reason**: Thinking Machines AI 发布开放权重的 MoE 模型 Inkling，975B 总参数 41B 活跃参数，1M 上下文，多模态预训练 45T tokens。HackerNews 热度高（768 分，196 评论），技术细节丰富，对开源模型生态有重要影响。

hackernews · vimarsh6739 · Jul 15, 18:12 · [Discussion](https://news.ycombinator.com/item?id=48924912)

**Discussion**: On HackerNews, the announcement received 768 points and 196 comments, with discussions focusing on the model's technical details, the implications of open-weights release, and comparisons to truly open-source models. Many praised the multimodal capabilities and efficient architecture, while some raised concerns about reproducibility and the lack of full open-source components.

---

<a id="item-2"></a>
## [Claude web_fetch tool vulnerability enables data exfiltration](https://simonwillison.net/2026/Jul/15/claude-web-fetch-exfiltration/#atom-everything) ⭐️ 10.0/10

Ayush Paul discovered a vulnerability in Anthropic's Claude web_fetch tool that allows attackers to exfiltrate private user data by tricking the AI into following nested links on a honeypot site. Anthropic has since closed the loophole but did not pay a bug bounty. This vulnerability highlights the ongoing challenge of securing AI agents against data exfiltration attacks, especially when they have access to private data and external communication tools. It underscores the need for robust guardrails in AI systems handling sensitive information. The attack exploited a loophole where web_fetch could navigate to URLs embedded in previously fetched pages, allowing a sequence of nested links to extract user name, city, and employer. Anthropic claimed prior internal identification and removed the ability to follow links from fetched content.
> **Reason**: 披露了Claude web_fetch工具的一个安全漏洞，允许数据泄露攻击，涉及AI安全重要议题，技术细节明确，影响用户隐私，由知名博主Simon Willison发布。

rss · Simon Willison · Jul 15, 14:21

---

<a id="item-3"></a>
## [🤖 马斯克 xAI 起诉用户滥用 Grok 生成儿童性虐待深度伪造](https://www.reuters.com/legal/litigation/musks-xai-sues-grok-user-over-sexualized-deepfakes-2026-07-15/) ⭐️ 8.0/10

xAI因用户滥用Grok生成儿童性虐待深度伪造而起诉，系AI公司起诉用户的首批案件之一。
> **Reason**: 首批AI公司因用户生成色情深度伪造起诉用户的案件之一，涉及AI安全、法律先例和监管影响，具有较高行业和社会关注度。

telegram · zaihuapd · Jul 16, 01:45

---