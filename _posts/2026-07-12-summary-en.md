---
layout: default
title: "Horizon Summary: 2026-07-12 (EN)"
date: 2026-07-12
lang: en
---

> From 26 items, 1 important content pieces were selected

---

1. [vLLM v0.25.0 Released with Model Runner V2 Default, PagedAttention Removed](#item-1) ⭐️ 10.0/10

---

<a id="item-1"></a>
## [vLLM v0.25.0 Released with Model Runner V2 Default, PagedAttention Removed](https://github.com/vllm-project/vllm/releases/tag/v0.25.0) ⭐️ 10.0/10

vLLM v0.25.0 makes Model Runner V2 the default execution path for all dense models and removes the legacy PagedAttention implementation. The Transformers backend is now as fast as native vLLM, with FP8 MoE support and new model additions. This release marks a significant architectural shift, simplifying the codebase and improving performance for a wide range of models. Users deploying vLLM for inference will benefit from better support for new models and streamlined execution. Model Runner V2 now supports EVS, realtime embeddings, prefix caching for Mamba hybrid models, and multimodal-prefix bidirectional attention. The removal of PagedAttention aligns with the V1/MRv2 backends becoming standard. Transformers backend achieved parity through fixes like GPTBigCode/Starcoder2 migration and RoBERTa migration.
> **Reason**: vLLM 0.25.0 版本发布，引入 Model Runner V2 默认、移除 PagedAttention、Transformers 后端性能提升等重大变化，对推理引擎用户和开发者有重要影响。

github · khluu · Jul 11, 20:06

---