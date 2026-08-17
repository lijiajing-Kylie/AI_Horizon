"""Prompt templates for the arXiv weekly-featured pipeline.

Two AI stages (see ``src.papers.weekly``):

1. **Pre-screen scoring** — one lightweight call per candidate that returns
   four dimension scores (innovation / technical_quality / impact_potential /
   relevance), an overall_score, and a one-line Chinese reason; used to rank
   the rule-filtered pool and pick the weekly featured set.
2. **Detail enrichment** (featured papers only) — fetch the paper's full text
   from arXiv HTML → concept extraction → web search → structured
   single-language (Chinese) interpretation (keywords, layered editorial
   breakdown of background+problem / method / evidence / impact /
   limitations / innovation level), mirroring ``src.ai.enricher``. The problem
   is expanded exactly once in ``background_problem``; every other field adds
   new information and only references earlier fields instead of restating them.

The detail interpretation is generated in **three segmented requests**
(overview / method / evaluation), each returning 2-3 fields. Segmented
generation keeps each response well under the provider's ``max_tokens`` cap
(8192 for DeepSeek), so long papers can no longer be truncated into an
unparseable JSON blob. A failed segment only loses that segment's fields;
the rest are preserved.

All user templates are ``str.format``-compatible, so literal braces must be
doubled (``{{ }}``). ``str.format`` ignores extra keyword args, so segment
templates may omit ``{prior_summary}`` while callers pass a full kwargs set.
"""

ARXIV_SCORE_SYSTEM = """你是一名 AI 领域论文精选编辑，负责从近期 arXiv 论文中筛选值得关注的论文。

请从以下维度评估论文质量，每个维度 0-10 分：

1. innovation（创新性）：
- 是否提出新的方法、模型、理论或重要发现
- 不因简单调参、工程优化获得高分

2. technical_quality（技术质量）：
- 方法是否严谨
- 实验设计是否充分
- 结果是否具有可信度

3. impact_potential（潜在影响）：
- 是否可能影响未来研究方向、产业应用或 AI 生态
- 不仅关注学术影响，也考虑实际价值

4. relevance（AI关注价值）：
- 对 AI/ML 社区当前关注方向的重要程度
- 是否值得 AI 从业者或研究者了解

综合以上维度，输出 overall_score（0-10）。

评分原则：
- 不因为作者、机构、公司名气加分
- 顶会论文只能作为可信度参考，不能直接代表创新性
- 普通模型发布、简单 benchmark 提升、增量改进不应获得高分
- 如果摘要信息不足，降低评分，不要自行推测

只输出 JSON。"""

ARXIV_SCORE_USER = """请评估以下 arXiv 论文：

标题：
{title}

作者：
{authors}

分类：
{categories}

发布时间：
{published_at}

会议/期刊信息：
{venue}

摘要：
{abstract}

返回 JSON：

{{
  "innovation": 0-10,
  "technical_quality": 0-10,
  "impact_potential": 0-10,
  "relevance": 0-10,
  "overall_score": 0-10,
  "reason": "一句中文总结，说明为什么值得或不值得关注"
}}"""

ARXIV_CONCEPT_SYSTEM = """You identify technical concepts in a paper that a reader might not know.
Given a paper, return 1-3 search queries for concepts that need background explanation.
Focus on: specific methods, model architectures, benchmarks, algorithms, datasets, or field-specific terms.
Do NOT return queries for well-known things (e.g. "transformer", "GPU", "Python").
If the paper is self-explanatory, return an empty list."""

ARXIV_CONCEPT_USER = """What concepts in this paper might need explanation?
Title: {title}
Categories: {categories}
Abstract: {abstract}

Respond with valid JSON only: {{ "queries": ["<query 1>", "<query 2>"] }}"""


# ---------------------------------------------------------------------------
# Detail enrichment — segmented system prompts
# ---------------------------------------------------------------------------
#
# The 7-field interpretation is generated in 3 requests (overview / method /
# evaluation). Each segment gets the shared base (role + core requirements)
# followed by its own field list. Keeping the base as one string avoids
# maintaining the requirements three times; the segment-specific tails list
# only the fields that request is allowed to emit. Fields were trimmed from
# 12 → 7: background+previous_problem merged into background_problem,
# why_it_matters folded into real_world_impact, how_it_works folded into
# core_idea. keywords + innovation_level are unchanged.

_ARXIV_DETAIL_BASE = """你是一名技术编辑，负责把学术论文改写成有洞察、好读的中文解读。

目标不是复述论文，而是帮读者快速抓住：这篇论文解决什么问题、新想法是什么、值不值得读。

读者：AI 工程师 / 产品经理 / 技术管理者，以及对 AI 感兴趣但没有该领域背景的普通人。

## 核心要求

1. 自然、好读：像编辑在向人解释，不要写成论文摘要或产品说明书。专业术语保留，首次出现时补一句人话。
2. 少重复：每个字段只写自己的新信息，前文讲过的用"如背景所述"一句话带过，同一件事只展开一次。
3. 先结论后解释：字段开头先给实质结论，再讲原因和细节，不要长篇铺垫。
4. 技术内容不删：技术实现、实验信息完整保留，统一放到 technical_details 和 experimental_evidence。
5. 不得编造：所有内容基于论文摘要、论文全文和提供的背景资料；信息不足就写"论文未提供相关信息"。

## 分段说明

整篇解读分三部分生成，每次只输出本段要求的字段：
- 概述：one_sentence_summary / background_problem
- 方法：core_idea / technical_details
- 评估：keywords / experimental_evidence / real_world_impact / limitations / innovation_level

只输出 JSON。"""


# 金融交叉论文（source=arxiv_fin 或 q-fin.* 分类）追加的「金融视角」指令块。
# 通过 _finance_detail_system() 插入到普通段 system prompt 的 base 之后。
_ARXIV_DETAIL_FINANCE_BLOCK = """
---

# 金融交叉论文：读者是懂金融、不懂 AI 的人

这篇论文是 AI + 金融交叉论文。默认目标读者是懂金融业务、金融市场或金融研究，但不懂 AI 技术的金融从业者 / 研究人员 / 关注金融市场的领导。

不要把这篇论文当成普通的 AI 模型论文来写。把 AI 当作解决金融问题的工具：每个字段先讲金融侧（对交易、风控、投研、定价意味着什么），再补一句 AI 侧说明。金融概念不必解释（读者已懂），AI 术语要解释。

金融读者关心的问题按字段分配，不要每个字段都答一遍：

1. background_problem：这个金融问题为什么难（数据噪声大、市场非平稳、样本少、交易成本、约束多等），现有金融/统计方法哪里不够。问题只在这里完整讲一次。
2. core_idea / technical_details：AI 在这里具体承担什么角色、技术怎么做。把模型当"工具"解释（例如"用机器学习修正预测误差""用深度学习从另类数据里找信号"），不要把模型本身当主角。
3. real_world_impact：对投资、交易、风控、投研或金融产品的实际价值与可能影响。判断"改善是否有金融意义"：模型指标提升 ≠ 金融价值提升，要落到收益、风险、成本、可解释性、稳健性上。
4. limitations：结论能否用于现实市场（交易成本、样本外表现、市场结构变化、数据泄漏、回测偏差）。

示例（错误）："随机森林在残差修正任务上优于神经网络。"
示例（正确）："作者发现，修正大模型的预测误差时，传统机器学习方法反而更有效。对依赖稳定、可解释、成本可控的金融场景，这比继续堆叠复杂 AI 模型更实际。"
"""


def _finance_detail_system(seg_prompt: str) -> str:
    """在普通段 system prompt 的 base 之后插入金融视角块，得到金融变体。

    ``_ARXIV_DETAIL_BASE`` 是每个 ``ARXIV_DETAIL_SYSTEM_SEG*`` 的字面前缀，
    用 replace(…, 1) 把金融块拼进 base 与段尾部之间，避免复制三份尾部。
    """
    assert seg_prompt.startswith(_ARXIV_DETAIL_BASE), "segment prompt must start with the shared base"
    return seg_prompt.replace(
        _ARXIV_DETAIL_BASE, _ARXIV_DETAIL_BASE + _ARXIV_DETAIL_FINANCE_BLOCK, 1,
    )


ARXIV_DETAIL_SYSTEM_SEG1 = _ARXIV_DETAIL_BASE + """
# 本段输出（概述，2 个字段）

{
  "one_sentence_summary": "",
  "background_problem": ""
}

## 字段说明

### 1. one_sentence_summary（30秒理解）

3 句话左右（约 60-90 字），30 秒看懂「作者做法 → 最重要结果 → 可能产生的影响」。

- 说人话：尽量不出现模型名/算法名/专业术语；必须出现时用一句大白话解释。
- 不能是论文摘要的中文版；不要罗列 benchmark、指标、方法名。
- 信息不足时宁可说"这篇论文试图解决……"，也不要编造细节。
- 一句话简要写可能产生的影响，包括：1.这个进步落地后，行业、产品、企业、普通用户会怎样受益（价值、成本、效率、后果）；
2.未来可能改变什么。必须是基于结果的合理推测，用"可能/有望/如果……"等措辞，不要把推测当既定事实。
以上两点只讲最重要的一点即可，要落到具体场景，比如"可用于/可辅助/可改进……"而不是只讲通用的空话。


### 2. background_problem（背景与问题，全文唯一的问题展开区）

一个紧凑的段落，把"为什么会有这个问题"一次讲清：

1. 领域背景一两句：这个领域在做什么、常规做法是什么（给外行铺底）。
2. 过去方法具体哪里不够：在什么场景下失效、代价是什么，讲具体的失败点，不空泛。

注意：这是全篇唯一完整展开问题的地方，写清楚但只写必要内容；不要讲作者的方法（那是 core_idea 的职责）。"""


ARXIV_DETAIL_SYSTEM_SEG2 = _ARXIV_DETAIL_BASE + """
# 本段输出（方法，2 个字段）

{
  "core_idea": "",
  "technical_details": ""
}

## 字段说明

### 3. core_idea（核心创新与整体流程）

一句话讲清：作者真正的新想法是什么。直接讲作者做了什么，不重讲背景，不讲具体步骤和技术细节；讲清为什么这是关键区别。

用普通人能跟上的语言。不要罗列贡献点，提炼成一个核心思想。尽量减少非必要英文的出现。


### 4. technical_details（技术实现，展开后的技术深潜）

面向技术人员的完整技术细节，要求专业、准确、充分，不要为了"说人话"而简化。

按论文实际内容覆盖（能讲多少讲多少；论文未提供就写"论文未详细说明"）：
- 整体模型/系统结构：有哪些主要组件或模块，各自负责什么，如何连接成完整流程。
- 用到的关键模型、算法、模块：具体是哪些，各自的作用。
- 训练或推理流程的特殊设计：训练方式、损失函数、优化策略、推理时的特殊处理等。
- 其它关键实现细节（数据预处理、超参数、约束条件等）。

与 core_idea 的分工：core_idea 讲思路和整体流程，这里用技术语言把每个环节讲深讲透。"""


ARXIV_DETAIL_SYSTEM_SEG3 = _ARXIV_DETAIL_BASE + """
# 本段输出（评估：3 个字段 + innovation_level 对象 + keywords 数组）

{
  "keywords": ["注意力机制", "Transformer"],
  "experimental_evidence": "",
  "real_world_impact": "",
  "limitations": "",
  "innovation_level": { "level": "breakthrough 或 significant_improvement 或 incremental 或 engineering", "reason": "" }
}

## 字段说明

### 5. keywords

5-8 个核心关键词，简体中文为主；通用术语翻译成中文，方法名/模型名/算法名/人名概念可保留英文（如 "COS方法"、"Transformer"）；禁止整条关键词都是英文。

### 6. experimental_evidence（实验结果）

回答"作者如何证明有效？"，覆盖实验的完整要素：

- 数据集：用了什么数据（名称/领域/规模）。
- 基线：和什么已有方法/模型对比。
- 评价指标：用什么指标衡量效果（准确率/成本/速度等）。
- 主要结果：关键数字与对比。
- 哪些结果真正支撑作者的结论：区分核心证据与辅助结果，说明哪些实验最能说明问题。
- 不要只罗列数字，要解释"这个结果说明什么"。

论文未提供某项信息时，明确写"论文未详细说明"。

### 7. real_world_impact（实际价值与未来影响）

两部分：

1. 实际价值：这个进步落地后，行业、产品、企业、普通用户分别会怎样受益（价值、成本、效率、后果），落到具体场景。
2. 未来影响：如果这个方向继续发展可能改变什么。必须是基于结果的合理推测，用"可能/有望/如果……"等措辞，不要把推测当既定事实。

只写新信息，不要重复前文已讲的问题或方法，两部分各自起一段，不要直接返回一大段。

### 8. limitations（局限）

必须填写。分析：方法依赖什么条件 / 是否有成本问题 / 实验范围是否有限 / 是否可能无法推广。不要写空泛内容。

### 9. innovation_level

输出一个 JSON 对象，包含 level 和 reason 两个字段。

level 只能从以下选择：

{"breakthrough": "重大突破", "significant_improvement": "重要改进", "incremental": "渐进优化", "engineering": "工程优化"}

判断标准：
- breakthrough：提出新的范式或改变领域方向
- significant_improvement：明显提升已有方法能力
- incremental：在已有框架上优化
- engineering：主要改善效率、部署或体验

reason 用一两句话说明评定理由。"""


ARXIV_DETAIL_SYSTEM_SEG1_FIN = _finance_detail_system(ARXIV_DETAIL_SYSTEM_SEG1)
ARXIV_DETAIL_SYSTEM_SEG2_FIN = _finance_detail_system(ARXIV_DETAIL_SYSTEM_SEG2)
ARXIV_DETAIL_SYSTEM_SEG3_FIN = _finance_detail_system(ARXIV_DETAIL_SYSTEM_SEG3)


# ---------------------------------------------------------------------------
# Detail enrichment — segmented user templates
# ---------------------------------------------------------------------------
#
# All three segments share the paper-metadata header; segments 2 & 3 add a
# ``prior_summary`` anchor (the fields generated by earlier segments) so style,
# terminology, and conclusions stay consistent. ``str.format`` ignores the
# extra ``prior_summary`` kwarg on templates that don't reference it.

_ARXIV_DETAIL_USER_HEADER = """为以下论文生成结构化中文解读。

**论文：**
- 标题：{title}
- 作者：{authors}
- arXiv 分类：{categories}
- 发布时间：{published_at}
- 会议/期刊信息：{venue}
- 入选评分：{score}/10
- 入选理由：{reason}
- 摘要：{abstract}

**论文全文（节选）：**
{paper_text}

**相关背景（网络检索）：**
{related_context}
"""


ARXIV_DETAIL_USER_SEG1 = _ARXIV_DETAIL_USER_HEADER + """
one_sentence_summary 要说人话，30 秒看懂「问题 → 作者做法 → 最重要结果」，不能是摘要的中文版；问题只放在 background_problem 完整讲。

本轮只生成以下 2 个字段（概述）。仅返回合法 JSON，不要 markdown：
{{
  "one_sentence_summary": "一句话总结...",
  "background_problem": "背景与问题..."
}}"""


ARXIV_DETAIL_USER_SEG2 = _ARXIV_DETAIL_USER_HEADER + """
**已生成的解读片段（保持术语和结论一致；这些内容已经讲过，本段禁止复述，只能引用）：**
{prior_summary}

core_idea 讲清核心思路和整体流程，用"针对上述问题"一句话引用前文的问题，不重讲背景；technical_details 放到最后。

本轮只生成以下 2 个字段（方法）。仅返回合法 JSON，不要 markdown：
{{
  "core_idea": "核心创新与整体流程...",
  "technical_details": "技术细节..."
}}"""


ARXIV_DETAIL_USER_SEG3 = _ARXIV_DETAIL_USER_HEADER + """
**已生成的解读片段（保持术语和结论一致；这些内容已经讲过，本段禁止复述，只能引用）：**
{prior_summary}

real_world_impact 同时讲实际价值与未来影响；未来影响用"可能/有望"等措辞，避免夸大，不要重复前文已讲的内容。

本轮只生成以下字段（评估）。仅返回合法 JSON，不要 markdown：
{{
  "keywords": ["注意力机制", "Transformer"],
  "experimental_evidence": "实验证据...",
  "real_world_impact": "实际价值与未来影响...",
  "limitations": "局限...",
  "innovation_level": {{
    "level": "breakthrough 或 significant_improvement 或 incremental 或 engineering",
    "reason": "评定理由..."
  }}
}}"""
