---
layout: default
title: "Horizon Summary: 2026-07-12 (ZH)"
date: 2026-07-12
lang: zh
---

> 从 26 条内容中筛选出 1 条重要资讯。

---

1. [vLLM v0.25.0 发布：默认 MRv2，移除 PagedAttention](#item-1) ⭐️ 10.0/10

---

<a id="item-1"></a>
## [vLLM v0.25.0 发布：默认 MRv2，移除 PagedAttention](https://github.com/vllm-project/vllm/releases/tag/v0.25.0) ⭐️ 10.0/10

vLLM v0.25.0 将所有密集模型的默认执行路径切换为 Model Runner V2，并移除了传统的 PagedAttention 实现。Transformers 后端性能达到与原生 vLLM 同级别，新增 FP8 MoE 支持及多款新模型。 此次发布标志着架构上的重大转变，简化了代码库并提升了对多种模型的性能。使用 vLLM 进行推理部署的用户将受益于对新模型的更好支持和简化的执行路径。 Model Runner V2 现在支持 EVS、实时嵌入、Mamba 混合模型的前缀缓存以及多模态前缀双向注意力。移除 PagedAttention 是因为 V1/MRv2 后端已成为标准。Transformers 后端通过迁移 GPTBigCode/Starcoder2 和 RoBERTa 等修复达到性能持平。
> **评分理由**: vLLM 0.25.0 默认启用 Model Runner V2 并移除 PagedAttention，这标志着推理引擎架构走向成熟和模块化。对于开发者与运维人员来说，维护更简单、新模型接入更快，但依赖旧版 PagedAttention 的工作流需迁移。

github · khluu · 7月11日 20:06

---