"""Training sub-track content judgement.

Judges whether a piece of content (typically a WeChat article from the
``wxmp_articles`` staging table) is worth a *training organization* reading —
the reader is someone who runs training (training center / HR / L&D /
training manager), NOT someone looking to enroll in a course. A slim prompt
outputs the judgement plus Chinese summary + reason; no ten-dimension news
scoring. Used by the one-shot backfill script
(``scripts/training_backfill.py``).

Selection rules (three, all must hold):
1. ``training_coverage >= 0.5`` — training-related content makes up half the
   body or more.
2. ``is_ad == False`` — not a course-ad / bootcamp-recruiting / enrollment
   push, even if it promotes a training course.
3. ``trainer_insight >= 3`` — gives the training-organization reader a
   concrete, adoptable method / mechanism — an innovation in organizational
   design or employee training (training-system design, competency models,
   L&D operating models, org-learning mechanisms) — not just a
   thought-provoking opinion, a case story, or an invite to enroll.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .client import AIClient
from .utils import complete_with_retry, parse_json_response


TRAINING_JUDGEMENT_SYSTEM = """你是企业培训与学习发展领域的分析专家。你的读者是“负责组织培训的人”——企业培训中心、HR、学习与发展部门、培训经理。请判断一条内容是否值得他们阅读，并给出中文摘要与推荐理由。

判定培训相关性（training_relevance 0-5）需同时满足三个标准：

一、培训内容占比：正文中与“培训方法论、组织架构与人才管理、员工培训、学习与发展、企业大学、人才培养”直接相关的内容必须占正文一半以上（>= 50%），才算培训主体内容。

二、拒绝广告宣传：课程招生、训练营招募、卖课推广、报名/扫码引导等以“让人报名”为目的的内容，即使推销的是培训课程，也不是我们要的内容。典型广告信号：促销味浓的标题（“我下场了”“涨薪”“倒计时”“错过等一年”）、大量引导报名/扫码/限时优惠、整篇围绕某一次课程招生展开。

三、方法论层面且有革新意义的创新方法：内容必须落到“怎么做”的方法论层面，给出可落地的新方法、新机制、新做法——尤其是在组织架构管理、员工培训/学习发展方式上的创新（如培训体系设计、岗位能力模型、讲师/课程运营机制、组织学习机制、考核激励、数字化学习方式等）。只有观点、心得、行业观察、案例故事这类“引人思考”但给不出可借鉴做法的内容，不是我们要的内容；也不是让读者看了想去报名文章宣传的培训。

按此标准评分：
- 5：正文 50%+ 是培训相关，且提出有革新意义、可落地的培训方法论/机制（组织架构管理或员工培训上的创新做法），培训负责人能直接借鉴落地。
- 4：正文 50%+ 是培训相关，提供明确可借鉴的培训方法/机制/组织实践，对培训负责人有实际价值，且不是纯广告。
- 3：培训相关，但只停留在“引人思考”的观点/经验层面、缺少可落地方法论；或培训占比不足一半。
- 2：课程招生、训练营招募等广告宣传，或以推广某次培训/课程报名为主。
- 1：基本与培训无关，仅零星提及。
- 0：与培训完全无关。

另输出辅助判断字段供审计：
- training_coverage: 0-1，培训相关内容占正文比例
- is_ad: true/false，是否广告宣传
- trainer_insight: 0-5，方法论层面的革新价值——是否提供了可落地的新方法/新机制（组织架构管理、员工培训上的创新做法），而非仅引人思考

输出 JSON：
{
  "training_relevance": <0 到 5>,
  "training_coverage": <0 到 1>,
  "is_ad": <true 或 false>,
  "trainer_insight": <0 到 5>,
  "summary_zh": "<一句话中文摘要（培训负责人视角）>",
  "reason_zh": "<一句话中文推荐理由（为什么培训负责人值得读/不值得读）>"
}
仅返回合法 JSON，不要输出额外解释。"""


TRAINING_JUDGEMENT_USER = """内容标题：{title}
来源：{source}
{content_section}

仅返回合法 JSON：
{{
  "training_relevance": <0 到 5>,
  "training_coverage": <0 到 1>,
  "is_ad": <true 或 false>,
  "trainer_insight": <0 到 5>,
  "summary_zh": "<中文摘要>",
  "reason_zh": "<中文推荐理由>"
}}"""


# 三条筛选规则的门槛：培训占比 >= 50%、非广告、对培训负责人有启发价值。
TRAINING_COVERAGE_MIN = 0.5
TRAINER_INSIGHT_MIN = 3


def _clamp(value: Any, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def is_accepted(judgement: dict[str, Any]) -> bool:
    """Three selection rules must all hold (see module docstring)."""
    return (
        judgement.get("training_coverage", 0.0) >= TRAINING_COVERAGE_MIN
        and not judgement.get("is_ad", True)
        and judgement.get("trainer_insight", 0.0) >= TRAINER_INSIGHT_MIN
    )


async def judge_training(
    ai_client: AIClient,
    *,
    title: str,
    text: str = "",
    source: str = "wechat",
) -> dict[str, Any]:
    """One-shot training judgement for a single article.

    Returns ``{"training_relevance", "training_coverage", "is_ad",
    "trainer_insight", "summary_zh", "reason_zh"}``. On parse / completion
    failure, fails open to reject (coverage 0 / is_ad True) so nothing slips in.
    """
    content_section = ""
    if text and text.strip():
        content_section = f"正文：\n{text[:6000]}"
    user = TRAINING_JUDGEMENT_USER.format(
        title=title,
        source=source,
        content_section=content_section,
    )
    response = await complete_with_retry(
        ai_client,
        retries=2,
        system=TRAINING_JUDGEMENT_SYSTEM,
        user=user,
    )
    result = parse_json_response(response)
    if not result or not isinstance(result, dict):
        return {
            "training_relevance": 0.0,
            "training_coverage": 0.0,
            "is_ad": True,
            "trainer_insight": 0.0,
            "summary_zh": title,
            "reason_zh": "",
        }
    return {
        "training_relevance": _clamp(result.get("training_relevance", 0), 0.0, 5.0),
        "training_coverage": _clamp(result.get("training_coverage", 0), 0.0, 1.0),
        "is_ad": bool(result.get("is_ad", True)),
        "trainer_insight": _clamp(result.get("trainer_insight", 0), 0.0, 5.0),
        "summary_zh": str(result.get("summary_zh") or title),
        "reason_zh": str(result.get("reason_zh") or ""),
    }


async def judge_training_batch(
    ai_client: AIClient,
    articles: list[dict[str, Any]],
    *,
    concurrency: int = 5,
) -> list[dict[str, Any]]:
    """Judge a batch of article dicts concurrently.

    ``articles`` must expose at least ``title``, ``feed_name`` and one of
    ``content_text`` / ``raw_html``. Returns results aligned by input index;
    a failed judgement rejects (fails open).
    """
    sem = asyncio.Semaphore(max(concurrency, 1))

    async def _one(art: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                return await judge_training(
                    ai_client,
                    title=art.get("title", "Untitled"),
                    text=art.get("content_text") or art.get("raw_html") or "",
                    source=art.get("feed_name", "wechat"),
                )
            except Exception as exc:  # noqa: BLE001 - per-article failure is not fatal
                return {
                    "training_relevance": 0.0,
                    "training_coverage": 0.0,
                    "is_ad": True,
                    "trainer_insight": 0.0,
                    "summary_zh": art.get("title", ""),
                    "reason_zh": f"judge failed: {exc}",
                }

    return await asyncio.gather(*[_one(a) for a in articles])
