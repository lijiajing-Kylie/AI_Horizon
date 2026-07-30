"""LLM-based relevance filter for the reports library.

Uses an exemplar-based evaluation approach: instead of relying on a rigid
rule checklist, the LLM is given a set of "benchmark reports" (标杆报告样本)
and asked to judge whether the candidate report belongs to the same category.
Only reports scoring 4+ (on a 1-5 scale) are kept.

Marketing white papers, product catalogues, consumer-insight decks, narrow
technical manuals, and similar non-tech/decision-level content are rejected.

Uses the same AI client abstraction as the main news pipeline
(``src.ai.client.create_ai_client``), so any configured provider works.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ai.client import AIClient

from .models import Report

logger = logging.getLogger(__name__)

# ── Prompt templates ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是一个科技类研究报告的评估专家。你的任务不是对照规则清单，而是判断一份内容是否与以下“标杆报告”属于同一类别：

【标杆报告样本】
1.《超级个体时代｜腾讯研究院3万字报告》—— 机构：腾讯研究院；特征：3万字宏观社会趋势研究，探讨个体能力放大后的社会经济变革，极度适合决策层。
2.《从超级个体到超级团队》—— 特征：承上启下的深度分析，聚焦组织形态与协作模式演进，对企业家和管理者极具参考价值。
3.《协同进化：2026年人工智能十大趋势研判》—— 特征：年度技术前瞻，兼具技术深度与产业战略视角，是科技决策者必读的趋势清单。

共同特征概括为：
- 由权威研究机构（如顶级企业研究院、国家级智库）发布。
- 属于正式的“报告/白皮书/趋势研判/深度研究”，而非新闻、教程、产品说明、单一技术手册。
- 内容具有系统性、前瞻性，能提供对技术或产业未来3-5年的判断。
- 阅读后能让CTO、投资人、企业战略负责人获得“原来如此，接下来该这样做”的洞察。
- 篇幅通常较长，万字左右或更甚，信息密度高。"""

_USER_TEMPLATE = """\
标题：{title}
机构：{institution}
摘要：{summary}
正文（节选）：{content}

现在，请根据给出的标题、机构、摘要和正文节选，评估该内容与标杆报告的相似程度。先在内部进行比较分析，然后只输出一个JSON对象（不要带Markdown标记），格式如下：
{{
  "score": 1-5,
  "reason": "一句话说明相似或差异的关键点",
  "is_report": true
}}

要求：
- score=5：与标杆报告高度同类，应优先收录
- score=4：与标杆报告较为相似，建议收录
- score=3：部分相似但不足以作为高质量研究报告收录
- score=2：与标杆报告差异较大
- score=1：完全不属于此类
- is_report 仅当 score>=4 时为 true"""


class ReportFilter:
    """Judges report relevance via an LLM call using exemplar-based evaluation.

    Instantiate once per pipeline run and call ``is_tech_relevant()`` for
    each candidate report.  The filter uses "benchmark report" samples to
    determine whether the candidate belongs to the same category.

    Returns a score (1-5) internally; only reports scoring >= 4 are kept.
    The filter is intentionally cheap — input is capped at ~300 tokens of
    summary text and ~2000 tokens of content excerpt.
    """

    def __init__(self, ai_client: AIClient):
        self._client = ai_client

    # ── Public API ──────────────────────────────────────────────────────

    async def is_tech_relevant(self, report: Report) -> bool:
        """Return ``True`` if the report should be kept."""
        user = self._build_user_prompt(report)
        try:
            raw = await self._client.complete(
                system=_SYSTEM_PROMPT,
                user=user,
                temperature=0.0,
                max_tokens=300,
            )
        except Exception as exc:
            # On AI failure, keep the report (fail-open).
            logger.warning(
                "AI filter call failed for %r — keeping report: %s",
                report.title,
                exc,
            )
            return True

        result, reason, score = self._parse(raw)
        if not result:
            logger.info("Filtered out [score=%d]: %s (%s) — %s",
                         score, report.title, report.institution, reason)
        return result

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_user_prompt(report: Report) -> str:
        summary = (report.summary or "")[:300]
        content = (report.content_text or "")[:2000]
        return _USER_TEMPLATE.format(
            title=report.title,
            institution=report.institution,
            summary=summary,
            content=content,
        )

    @staticmethod
    def _parse(text: str) -> tuple[bool, str, int]:
        """Parse LLM output into (keep: bool, reason: str, score: int)."""
        t = text.strip()
        # Extract JSON object from the response
        if "{" in t:
            # Find the outermost JSON object
            start = t.index("{")
            # Try to find the matching closing brace with basic truncation handling
            if "}" in t[start:]:
                end = start + t[start:].index("}") + 1
                json_str = t[start:end]
            else:
                json_str = t[start:]
            try:
                obj = json.loads(json_str)
                score = int(obj.get("score", 0))
                reason = str(obj.get("reason", "") or "")
                is_report = obj.get("is_report", score >= 4)
                if isinstance(is_report, bool):
                    return is_report, reason, score
                return score >= 4, reason, score
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        # Fallback: plain text "是" (keep) or "否"/scores (reject)
        if t and t[0] in ("是", "Y", "y"):
            return True, "fallback: yes", 3
        if "4" in t or "5" in t:
            return True, "fallback: score 4/5", 4
        return False, f"fallback: unparseable — {t[:60]}", 0
