---
layout: default
title: "Horizon Summary: 2026-07-17 (ZH)"
date: 2026-07-17
lang: zh
---

> 从 43 条内容中筛选出 5 条重要资讯。

---

1. [Kimi K3：首个开源 3T 级模型发布](#item-1) ⭐️ 9.0/10
2. [AI 音乐视频对决：Claude Fable 5 vs GPT-5.6 Sol](#item-2) ⭐️ 8.0/10
3. [Inkling：Thinking Machines Lab 的开放权重混合专家模型](#item-3) ⭐️ 8.0/10
4. [知网将下架将 AI 列为作者的论文](#item-4) ⭐️ 8.0/10
5. [日本购 2.75 万块英伟达 Rubin 芯片打造机器人主权 AI](#item-5) ⭐️ 8.0/10

---

<a id="item-1"></a>
## [Kimi K3：首个开源 3T 级模型发布](https://www.kimi.com/blog/kimi-k3) ⭐️ 9.0/10

Kimi 发布了 K3 模型，参数量达 2.8 万亿，具备原生视觉能力和百万 token 上下文窗口，成为首个达到 3T 规模的开源模型。 Kimi K3 将开源 AI 推向前沿，为开发者和企业提供接近顶尖的性能，可能重塑与闭源模型的竞争格局。 K3 采用混合专家架构，896 个专家中激活 16 个，通过 Kimi Delta Attention 和 Attention Residuals 实现相比 K2 的 2.5 倍扩展效率提升。性能仍落后于 Claude Fable 5 和 GPT 5.6 Sol，但优于其他测试模型。
> **评分理由**: Kimi 发布2.8T开源模型，首个达到3T级别，说明开源AI正式迈入万亿参数时代。对开发者和创业公司来说，这意味着无需绑定厂商就能获得前沿能力，与闭源巨头的竞争将更加激烈。

hackernews · vincent_s · 7月16日 14:46 · [社区讨论](https://news.ycombinator.com/item?id=48935342)

---

<a id="item-2"></a>
## [AI 音乐视频对决：Claude Fable 5 vs GPT-5.6 Sol](https://www.tryai.dev/blog/ai-music-video-arena-claude-vs-gpt-5.6) ⭐️ 8.0/10

一项实验对比了 Claude Fable 5 和 GPT-5.6 Sol 在 25 美元或 100 美元预算下自主制作音乐视频的能力，记录了每次工具调用。两个模型都使用自定义的 agentic harness（含六个工具）完成了《Uptown Funk》的完整视频制作。 这次正面比较揭示了前沿模型在开放式长周期任务中工具使用的差异，对 AI agent 设计至关重要。该实验为不同模型在 agentic harness 中的行为和成本效率提供了可复现的基准。 GPT-5.6 Sol 在 25 美元时使用了图生视频，100 美元时混合使用了三种视频模型；而 Claude Fable 5 全程使用文生视频。Claude Fable 5 的 token 成本（16.99–25.05 美元）远高于 GPT-5.6 Sol（3–4 美元），尽管视频生成支出相近。
> **评分理由**: 该实验罕见地详细对比了两个前沿模型在真实自主任务中的工具调用行为，揭示了直接影响agentic harness设计的战略差异。对AI agent开发者来说，这些发现凸显了成本与性能的权衡，以及模型选择对于长周期自动化的重要性。

hackernews · hershyb_ · 7月16日 20:03 · [社区讨论](https://news.ycombinator.com/item?id=48939524)

**社区讨论**: Hacker News 上的讨论（163 分，177 条评论）赞扬了实验的透明度和方法论，许多人讨论了这对 agentic 工作流程的影响。一些用户指出，Claude Fable 5 的较高 token 成本是长期运行 agent 的实际问题。

---

<a id="item-3"></a>
## [Inkling：Thinking Machines Lab 的开放权重混合专家模型](https://simonwillison.net/2026/Jul/16/inkling/#atom-everything) ⭐️ 8.0/10

Thinking Machines Lab 发布了 Inkling，一个开放权重的混合专家多模态模型，总参数 975B，活跃参数 41B，训练于 45 万亿 token，采用 Apache-2.0 许可。 Inkling 为美国开放权重生态系统注入了新的有力竞争者，与 NVIDIA Nemotron 和 Gemma 4 等模型竞争。其 Apache-2.0 许可和多模态能力使其成为通过 Tinker 平台进行微调的良好基础。 模型卡片异常简洁，训练数据文档除了表明使用公共领域和公开可用内容外几乎未提供细节。该模型并非前沿模型，而是定位为可定制的基础模型。
> **评分理由**: Thinking Machines Lab 以 Apache-2.0 许可发布其首个开放权重模型 Inkling，总参数 975B，直接挑战中国开源模型。对美国 AI 生态而言，这意味着一个宽松许可的新竞争者可能通过 Tinker 平台重塑微调工作流。

rss · Simon Willison · 7月16日 15:35

---

<a id="item-4"></a>
## [知网将下架将 AI 列为作者的论文](https://www.zaobao.com.sg/news/china/story20260716-9371836) ⭐️ 8.0/10

中国知网宣布将下架将 DeepSeek、Gemini 等 AI 列为作者的论文，理由是 AI 不具备民事主体资格，不能享有著作权。 这是中国主要学术平台首次明确禁止 AI 列为作者，为 AI 时代的学术出版规范和版权执行树立了先例。 知网声明作者必须是自然人、法人或非法人组织，AI 工具仅作为辅助工具使用，且需在研究方法或致谢中披露。
> **评分理由**: 知网首次明确禁止AI列为论文作者，这标志着中国学术出版对AI署名权的政策收紧——AI不具备著作权和学术责任能力。对出版商和研究者而言，这划清了边界，也带来AI辅助写作的合规挑战。

telegram · zaihuapd · 7月16日 07:45

---

<a id="item-5"></a>
## [日本购 2.75 万块英伟达 Rubin 芯片打造机器人主权 AI](https://www.bloomberg.com/news/articles/2026-07-16/japan-to-buy-nvidia-rubin-chips-to-build-sovereign-ai-for-robots) ⭐️ 8.0/10

日本宣布计划购入 2.75 万块英伟达下一代 Rubin 芯片，并由新成立的 Noetra 公司牵头建设大型数据中心，目标是开发面向机器人的主权 AI 模型，政府拨款约 3873 亿日元（24 亿美元）。 这标志着 G7 国家在主权 AI 上的重大投入，直接挑战美中在 AI 和机器人领域的主导地位。它释放出一个战略信号：政府正大力投资自有 AI 基础设施以减少对外依赖，并争夺未来机器人市场份额。 Noetra 总裁田场广信计划明年 3 月发布首个 AI 模型，数年内推出机器人专用版本。软银、丰田支持的 Preferred Networks、NEC 等参与其中。日本目标是到 2040 年占据全球机器人市场 30%以上份额。
> **评分理由**: 日本斥资24亿美元购入2.75万块英伟达Rubin芯片打造机器人主权AI，不只是一笔采购订单，更是地缘政治表态——日本从AI使用者转向建设者，挑战美中双头垄断。对全球AI芯片需求和机器人创业公司而言，这意味着新一轮国家支持型竞争的到来。

telegram · zaihuapd · 7月16日 10:59

---