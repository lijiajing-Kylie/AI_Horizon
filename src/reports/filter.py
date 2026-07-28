"""LLM-based relevance filter for the reports library.

Judges whether a fetched report is related to technology, AI, or innovation
before it is saved to the database.  Marketing white papers, product catalogues,
consumer-insight decks and similar non-tech content are rejected.

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

_SYSTEM_PROMPT = (
    "你是一个科技报告过滤器。判断一份内容是否值得作为研究报告收录。"
    "只返回一个JSON对象。"
)

_USER_TEMPLATE = """\
标题：{title}
机构：{institution}
摘要：{summary}
正文（节选）：{content}

这份内容是否值得作为研究报告收录？

必须同时满足以下条件才算「是」：
1. 正文或标题明确说明这是一份「报告」「白皮书」「深度研究」「行业洞察」等，而非普通新闻快讯、推文、产品介绍
2. 阅读后能有很大收获——包含深度分析、数据支撑、前瞻判断，而非浅层信息汇总
3. 受众不限于技术人员，对管理者、投资者、行业从业者同样有价值
4. 优先收录万字长文或同等深度的报告（篇幅越长越好）

以下类型必须拒绝（答「否」）：
- 营销推广、品牌白皮书、消费者洞察、购物指南
- 产品目录、职业装/团服采购、年货消费
- 餐饮/奶茶/零食行业报告（不含食品科技）
- 纯财务/股票/投资策略报告（不含金融科技）
- 人力资源/招聘/薪酬报告
- 房地产/物业/装修报告
- 纯政策/法规解读（不含科技政策）
- 娱乐/游戏/直播行业报告（不含底层技术）
- 某个具体产品/平台的介绍白皮书（如鸿蒙白皮书、某产品安全白皮书、某平台运营报告、某型号技术手册）
- 某一项具体技术或某个使用功能的白皮书（如FastLane详解、Sparse Attention技术报告、某工具使用指南）
- 单一技术点的窄范围白皮书（如某个协议标准、某种特定算法介绍）
- 企业内部流程/管理体系介绍（如流程体系最佳实践、代理商规则）
- 普通新闻资讯、日报周报汇总、活动预告、会议速记
- 纯观点评论、个人博客式文章（缺乏系统研究）

以下类型应该接受（答「是」）：
- AI、大模型、机器学习、深度学习、自动驾驶、机器人等行业的趋势分析
- 芯片半导体、云计算、大数据、物联网、5G/6G等行业研究
- 新能源、电池技术、光伏、储能、碳中和等行业洞察
- 生物医药、基因编辑、航天航空、量子计算等领域报告
- 产业数字化、智能制造、工业互联网、金融科技等宏观分析
- 数字经济发展、数实融合、技术社会影响等综合性报告
- 万字以上的行业深度报告、年度观察、产业全景图

只返回一个JSON对象：{{"r": "是"}} 或 {{"r": "否"}}"""


class ReportFilter:
    """Judges report relevance via an LLM call.

    Instantiate once per pipeline run and call ``is_tech_relevant()`` for
    each candidate report.  The filter is intentionally cheap — input is
    capped at ~300 tokens of summary text and the output is a single token
    (是 / 否).
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
                max_tokens=100,
            )
        except Exception as exc:
            # On AI failure, keep the report (fail-open).
            logger.warning(
                "AI filter call failed for %r — keeping report: %s",
                report.title,
                exc,
            )
            return True

        result = self._parse(raw)
        if not result:
            logger.info("Filtered out non-tech: %s (%s)", report.title, report.institution)
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
    def _parse(text: str) -> bool:
        t = text.strip()
        # Parse JSON response: {"r": "是"} or {"relevant": "是"}
        if "{" in t:
            # Ensure the JSON string is complete (truncation safety)
            if not t.endswith("}"):
                t += '"}'
            try:
                obj = json.loads(t)
                val = obj.get("r") or obj.get("relevant") or ""
                return val == "是"
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        # Fallback: plain text "是" or "否"
        if t and t[0] in ("是", "Y", "y"):
            return True
        return False
