---
layout: default
title: "Horizon Summary: 2026-07-07 (EN)"
date: 2026-07-07
lang: en
---

> From 33 items, 2 important content pieces were selected

---

1. [Global workspace in language models](#item-1) ⭐️ 8.0/10
2. [Tencent releases Hy3, a 295B MoE model under Apache 2.0](#item-2) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [Global workspace in language models](https://www.anthropic.com/research/global-workspace) ⭐️ 8.0/10

Anthropic research reveals an abstract reasoning subspace in language models that functions like a global workspace, sharing information across contexts. This finding bridges artificial neural networks and cognitive science, offering a new perspective on how LLMs perform abstract reasoning and potentially informing future model interpretability and architecture design. The researchers identified a subspace (J-Space) where changes in layer activations correspond to changes in final logits, indicating shared abstract representations across diverse tasks.
> **Reason**: Anthropic官方博客，研究LLM内部全局工作空间，社区讨论活跃（266分，97评论），具有技术深度和新颖性。

hackernews · in-silico · Jul 6, 17:44 · [Discussion](https://news.ycombinator.com/item?id=48808002)

**Discussion**: Community comments are mixed: some find the comparison to human consciousness intriguing but caution against over-interpretation (e.g., 'it's all in how you interpret it'), while others appreciate the technical depth and see it as a step toward better model understanding.

---

<a id="item-2"></a>
## [Tencent releases Hy3, a 295B MoE model under Apache 2.0](https://simonwillison.net/2026/Jul/6/hy3/#atom-everything) ⭐️ 8.0/10

Tencent has released Hy3, a 295B-parameter Mixture-of-Experts model with 21B active parameters, under the Apache 2.0 license. It outperforms similar-size models and rivals open-source flagships with 2-5x parameters. This release significantly lowers the barrier to accessing a state-of-the-art MoE model, as it is fully open-source and available for free on OpenRouter until July 21st. It demonstrates Tencent's commitment to open-source AI and provides a strong alternative to other large models, benefiting researchers and developers. The full model weighs 598GB on Hugging Face, while an FP8 quantized version is 300GB. The context length is 256K tokens, supporting long-context applications.
> **Reason**: 腾讯发布295B参数MoE模型Hy3，Apache 2.0开源，性能优于同类模型，上下文256K，对AI研究者和工程师有重要参考价值。

rss · Simon Willison · Jul 6, 23:57

---