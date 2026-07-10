---
layout: default
title: "Horizon Summary: 2026-07-10 (EN)"
date: 2026-07-10
lang: en
---

> From 38 items, 6 important content pieces were selected

---

1. [OpenAI releases GPT-5.6 family with ARC-AGI-3 SOTA](#item-1) ⭐️ 10.0/10
2. [Meta launches Muse Spark 1.1 multimodal reasoning model with enhanced tool use](#item-2) ⭐️ 10.0/10
3. [Meta Superintelligence: 1-Year Update After Llama 4 Failure](#item-3) ⭐️ 9.0/10
4. [Ant Lingbo Open-Sources LingBot-Video, First MoE Embodied Video Foundation Model](#item-4) ⭐️ 9.0/10
5. [Tencent Hy3 Model Sparks Community Debate with Cost Efficiency](#item-5) ⭐️ 8.0/10
6. [National Supercomputing Internet core node goes live in Zhengzhou](#item-6) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [OpenAI releases GPT-5.6 family with ARC-AGI-3 SOTA](https://openai.com/index/gpt-5-6/) ⭐️ 10.0/10

OpenAI has released the GPT-5.6 family of models, including Luna, Terra, and Sol, on July 9, 2026. The largest model, Sol, achieves a new state-of-the-art score of 7.8% on the ARC-AGI-3 benchmark. This release marks a significant step in interactive reasoning and agentic AI, as ARC-AGI-3 is designed to measure human-like intelligence in novel environments. The three-tier pricing (Luna/Terra/Sol) also offers developers flexible options for cost and capability. Pricing ranges from $1 (Luna) per 1M input tokens to higher tiers for Terra and Sol. The developer guide highlights improved intent understanding and original image detail preservation. However, the model reportedly falls behind Sonnet 5 in some coding benchmarks according to community tests.
> **Reason**: OpenAI官方发布GPT-5.6新模型，属于重大AI新闻；社区讨论热烈（1133分、815条评论），内容包含技术细节（ARC-AGI-3结果、Benchmark对比等），来源权威且首次披露。

hackernews · logickkk1 · Jul 9, 17:04 · [Discussion](https://news.ycombinator.com/item?id=48849066)

**2 sources covering this event**

**Primary Source**: [logickkk1](https://openai.com/index/gpt-5-6/) `official_company_blog`

**Other Sources** (1):
- [Simon Willison](https://simonwillison.net/2026/Jul/9/gpt-5-6/#atom-everything) — expert_blog

<details><summary>📰 2 sources · logickkk1, Simon Willison</summary>

<ul>
<li>[logickkk1](https://openai.com/index/gpt-5-6/) — GPT-5.6</li>
<li>[Simon Willison](https://simonwillison.net/2026/Jul/9/gpt-5-6/#atom-everything) — The new GPT-5.6 family: Luna, Terra, Sol</li>
</ul>
</details>

**Discussion**: Developers noted the new intent understanding and image detail features in the guide, but some expressed disappointment that Sol scored only 7.8% on ARC-AGI-3, calling it low. Comparisons to Claude Code and Sonnet 5 were mixed, with some preferring GPT-5.6 for certain tasks and others favoring competitors.

---

<a id="item-2"></a>
## [Meta launches Muse Spark 1.1 multimodal reasoning model with enhanced tool use](https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/) ⭐️ 10.0/10

Meta released Muse Spark 1.1, a multimodal reasoning model designed for agentic tasks, with major improvements in tool and computer use, coding, and multimodal understanding. A public preview of the Meta Model API is now available for developers. Muse Spark 1.1 pushes the performance-efficiency frontier for AI agents, enabling more autonomous and capable assistants. This advances Meta's vision of personal superintelligence and intensifies competition in the agentic AI space. The model supports a 1 million token context window, active memory management, and multi-agent orchestration. It zero-shot generalizes to new tools, MCP servers, and custom skills, and performs well on Meta Internal Coding Bench.
> **Reason**: Meta官方博客首次发布Muse Spark 1.1，多模态推理模型提升智能体任务性能，社区讨论热烈（HN 337分176评论），技术实质高，来源权威，行业影响大。

hackernews · ot · Jul 9, 14:10 · [Discussion](https://news.ycombinator.com/item?id=48846184)

**Discussion**: Hacker News commenters express excitement about the model's capabilities, particularly its computer-use and multi-agent orchestration, but some raise concerns about data privacy and the closed API preview. Others compare it favorably to competitors like GPT and Claude.

---

<a id="item-3"></a>
## [Meta Superintelligence: 1-Year Update After Llama 4 Failure](https://newsletter.semianalysis.com/p/the-future-of-meta-superintelligence) ⭐️ 9.0/10

Meta's superintelligence lab (MSL) publicly debuted with Muse Spark but lags behind open-source models like DeepSeek v4 Pro and Kimi K2.6. However, Meta is rebuilding its AI org with massive investments: $14.3B to acquire Scale AI's Alexandr Wang and his team, multi-hundred-million-dollar pay packages for top researchers, and a novel tent datacenter design to expedite compute ramp. This analysis reveals Meta's aggressive strategy to catch up with OpenAI and Anthropic, highlighting that the frontier AI race may expand from a two-horse race to three. Meta's unique advantages in data (from its social platforms), talent acquisition, and compute (via tent datacenters) could reshape competitive dynamics if they succeed. Meta's tent datacenter design aims to cut construction time by half, from 18-36 months to 9-18 months, bypassing permitting delays. The article also notes that Meta is the only hyperscaler/neolab on track to be world-class at data, talent, and compute simultaneously, with compute projections from a new Tokenomics Model.
> **Reason**: 来自权威分析媒体Semianalysis的独家深度报道，首次披露Meta在Llama 4失败后重建AI组织的内部细节，包括巨额投资、人才争夺和新数据中心设计，对行业格局有实质影响。

rss · Semianalysis · Jul 9, 19:16

---

<a id="item-4"></a>
## [Ant Lingbo Open-Sources LingBot-Video, First MoE Embodied Video Foundation Model](https://www.qbitai.com/2026/07/446458.html) ⭐️ 9.0/10

Ant Lingbo has open-sourced LingBot-Video, the first Mixture-of-Experts (MoE) based embodied video generation foundation model. It achieved a total score of 0.620 on the RBench benchmark, surpassing models like Wan2.6 and NVIDIA Cosmos3 Super. This marks a shift in video generation from content creation to physical world understanding for embodied AI, providing an efficient and open-source foundation for robotics applications. The MoE architecture allows large capacity (30B total, 3B active) while maintaining high inference efficiency, critical for real-time robotic control. LingBot-Video uses a DiT+MoE design with 30B total parameters but only ~3B activated per inference, achieving ~3x efficiency over dense models. It was trained on 70,000 hours of embodied data including VLA, VLN, and ego-centric scenarios, and incorporates multi-dimensional RL reward alignment for physical plausibility and task completion.
> **Reason**: 全球首个MoE具身视频基模开源，技术细节丰富（架构、数据、训练），基准测试领先，对具身智能领域有重要影响。来源为量子位报道，权威性中等。

telegram · zaihuapd · Jul 9, 04:30

---

<a id="item-5"></a>
## [Tencent Hy3 Model Sparks Community Debate with Cost Efficiency](https://hy.tencent.com/research/hy3) ⭐️ 8.0/10

Tencent has released Hy3, a 295B-parameter Mixture-of-Experts model with 21B active parameters, now available for free trial on OpenRouter until July 21. The model rivals DeepSeek V4 Flash (284B parameters, 13B active) in capability while offering competitive pricing. Hy3 demonstrates that smaller active-parameter models can achieve performance comparable to much larger models, potentially lowering the barrier for local deployment and making advanced AI more accessible to developers and enterprises. This intensifies competition in the cost-efficient LLM segment. Hy3 has 295B total parameters with 21B active and an additional 3.8B MTP layer parameters. It supports a context length of 1M tokens. Free trials via OpenRouter are offered by Novita Labs until July 21. The model's effective input price on OpenRouter is now similar to DeepSeek-hosted DeepSeek V4 Flash.
> **Reason**: 内容涉及腾讯Hy3大模型，社区讨论热烈（score 413, 89 comments），包含技术细节对比（与DeepSeek V4 Flash），有实质性讨论和免费试用信息，来源为腾讯官方页面，具有行业关注度。

hackernews · andai · Jul 9, 15:27 · [Discussion](https://news.ycombinator.com/item?id=48847552)

**Discussion**: The community is actively comparing Hy3 with DeepSeek V4 Flash, noting their similar sizes. Some users highlight Hy3's surprising capability given its small active parameter count, predicting it could become a popular local model. Others question its competitiveness after initially topping OpenRouter rankings but slipping to 8th/9th.

---

<a id="item-6"></a>
## [National Supercomputing Internet core node goes live in Zhengzhou](https://36kr.com/newsflashes/3887797387344387) ⭐️ 8.0/10

The core node of China's National Supercomputing Internet officially launched in Zhengzhou on July 9, 2026, offering over 100,000 cards of domestic AI computing power, the largest single domestic AI computing resource pool connected to the platform. This marks a critical milestone in China's push to build a self-controlled and unified national computing infrastructure, significantly reducing dependence on foreign chips and providing a massive domestic resource pool for AI model training and scientific computing. The node handles core functions including operations management, resource scheduling, supply-demand matching, and industry incubation services. It aims to build a nationwide unified computing resource scheduling system connecting multiple supercomputing centers.
> **Reason**: 来源为36氪（知名科技媒体），内容具体（10万卡国产算力），涉及AI基础设施，对行业有实际影响，信息明确。

telegram · zaihuapd · Jul 9, 07:00

---