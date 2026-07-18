---
layout: default
title: "Horizon Summary: 2026-07-18 (ZH)"
date: 2026-07-18
lang: zh
---

> 从 35 条内容中筛选出 4 条重要资讯。

---

1. [豆包手机放弃 GUI 模拟，转向 MCP 服务，备货量提升至数十万台](#item-1) ⭐️ 9.0/10
2. [Kimi K3：2.8 万亿参数开源模型超越 GPT-5 和 Claude Opus](#item-2) ⭐️ 8.0/10
3. [EU AI Act OpenRAG：933 个法律结构分块与 BGE-M3 嵌入](#item-3) ⭐️ 8.0/10
4. [华为昇腾 950 超节点首展，算力达英伟达 6.7 倍](#item-4) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [豆包手机放弃 GUI 模拟，转向 MCP 服务，备货量提升至数十万台](https://www.latepost.com/news/dj_detail?id=3648) ⭐️ 9.0/10

字节跳动的豆包手机放弃了基于 GUI 的屏幕读取和模拟点击策略来控制第三方应用，转而要求这些应用提供 MCP 服务进行集成，并将备货量从 3 万台提升至数十万台。 这一转变标志着 AI 手机助手与超级应用交互方式的重大变化，从对抗性的屏幕抓取转向基于 API 的合作集成。它可能重新定义设备制造商、应用开发商和 AI 平台之间的权力动态，从而在智能手机上实现更稳定、更安全的 AI 自动化。 最初的 GUI 方法立即遭到微信、淘宝等主要应用的封禁，迫使字节跳动缩减规模。新的基于 MCP 的方法要求应用开发者自愿暴露数据和控件，这与苹果的 App Intents 框架类似。7 月 15 日获得的独立 AI 服务备案可能有助于未来与更多厂商的合作。
> **评分理由**: 字节跳动豆包手机放弃对抗性GUI自动化，转向合作式MCP集成，备货量从3万台升至数十万台。这标志着从对抗性应用控制到合作生态模式的战略转变，重塑AI手机厂商与超级应用的谈判格局。对应用开发者和手机厂商而言，这预示了端侧AI的新行为准则。

telegram · zaihuapd · 7月18日 00:29

---

<a id="item-2"></a>
## [Kimi K3：2.8 万亿参数开源模型超越 GPT-5 和 Claude Opus](https://simonwillison.net/2026/Jul/16/kimi-k3/) ⭐️ 8.0/10

Moonshot AI 发布了 Kimi K3，这是一个拥有 2.8 万亿参数的开源权重模型，声称在多个基准测试中超越了 GPT-5 和 Claude Opus。权重将于 2026 年 7 月 27 日前发布。 Kimi K3 是首个超过 2 万亿参数的开源模型，标志着开源 AI 能够与专有前沿模型竞争。其每百万令牌 3/15 美元的定价将其定位为高端产品，挑战了 AI 市场的成本格局。 该模型使用 2.8 万亿参数，支持 100 万上下文窗口，在 Artificial Analysis 的长时知识工作评估中达到 1547 的 Elo 分数。然而，在某些基准测试上仍落后于 Claude Fable 5 和 GPT-5.6 Sol。
> **评分理由**: Moonshot AI 发布 2.8 万亿参数开源模型 Kimi K3，在多个基准上超越 GPT-5 和 Claude Opus，直接挑战闭源前沿；但其每百万令牌 3/15 美元的定价高于此前中国模型，可能限制企业大规模部署。对开源社区，这表明开源模型在规模上已能匹敌最先进的闭源模型；对企业，这预示着顶级 AI 能力进入了一个新的成本层级。

hackernews · droidjj · 7月17日 14:21 · [社区讨论](https://news.ycombinator.com/item?id=48947717)

**共 2 个来源报道**

**主要来源**: [@zaihuapd](https://t.me/zaihuapd/42637) `social_post`

**其他来源** (1):
- [droidjj](https://simonwillison.net/2026/Jul/16/kimi-k3/) — expert_blog

<details><summary>📰 @zaihuapd, droidjj 等 2 家报道</summary>

<ul>
<li>[@zaihuapd](https://t.me/zaihuapd/42637) — 🌙 Kimi K3 发布：开源 2.8T 模型，前端编程在 Arena 中超越 Fable 5 跃居第一  月之暗...</li>
<li>[droidjj](https://simonwillison.net/2026/Jul/16/kimi-k3/) — Kimi K3, and what we can still learn from the pelican ben...</li>
</ul>
</details>

---

<a id="item-3"></a>
## [EU AI Act OpenRAG：933 个法律结构分块与 BGE-M3 嵌入](https://www.reddit.com/r/MachineLearning/comments/1uytlac/eu_ai_act_openrag_933_legally_structured_chunks/) ⭐️ 8.0/10

作者发布了 EU AI Act OpenRAG 语料库，将法规按法律结构分块为 933 个块，并为每个块提供 BGE-M3 嵌入，存储于 SQLite 数据库中。 该数据集通过结构化分块将法律领域知识与 RAG 结合，召回率高于滑动窗口方法，对法律 NLP 和 AI 法案合规系统至关重要。 语料库包含精确的 EUR-Lex 链接、第 113 条应用日期元数据，以及直接文本分类和广泛监管关联的独立存储。检索评估显示场景文章 recall@20 为 0.541（结构化）对比 0.449（基线）。
> **评分理由**: 作者发布法律结构化分块的RAG语料库并证明其检索效果优于滑动窗口，这意味着结构化知识组织是法律NLP的关键方向。对构建EU AI Act合规工具的研究者来说，该数据集提供了可直接使用的可复现基准。

reddit · r/MachineLearning · /u/Automatic-Forever-63 · 7月17日 08:18

---

<a id="item-4"></a>
## [华为昇腾 950 超节点首展，算力达英伟达 6.7 倍](https://www.ithome.com/0/978/019.htm) ⭐️ 8.0/10

华为在 2026 世界人工智能大会上首次公开展示昇腾 950 超节点，提供 1 EFLOPS FP8 和 2 EFLOPS FP4 算力，通过灵衢互联协议实现 1024 卡规模互联，宣称性能达到英伟达同级产品的 6.7 倍。 这是国产 AI 芯片的重大突破，挑战英伟达在高性能 AI 算力领域的统治地位。在出口限制背景下，昇腾 950 超节点可能重塑中国企业和政府客户的 AI 基础设施格局。 该系统配备 256 TB 全局统一内存、TB 级 NPU 互联带宽和 3μs 超低 RTT 时延。此前昇腾 384 超节点已商用落地 750 多套，应用于互联网、运营商、金融、医疗等行业。
> **评分理由**: 华为昇腾950超节点首次公开亮相，明确宣称性能达英伟达6.7倍且公布了详细技术参数，标志着国产AI算力从追赶转向实质性竞争。对国内云厂商和企业来说，这提供了英伟达H100/B200之外的可选方案，在芯片限制下可能加速国内AI部署，此前384超节点750多套的商用落地也为这一突破增添了可信度。

telegram · zaihuapd · 7月17日 10:27

---