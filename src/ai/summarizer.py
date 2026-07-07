"""Daily summary generation — pure programmatic rendering."""

import re
from typing import List, Dict

from ..models import ContentItem


_CJK = r"[\u4e00-\u9fff\u3400-\u4dbf]"
_ASCII = r"[A-Za-z0-9]"


def _pangu(text: str) -> str:
    """Insert a space between CJK and ASCII letters/digits (Pangu spacing)."""
    text = re.sub(rf"({_CJK})({_ASCII})", r"\1 \2", text)
    text = re.sub(rf"({_ASCII})({_CJK})", r"\1 \2", text)
    return text


LABELS = {
    "en": {
        "header": "Horizon Daily",
        "source": "Source",
        "background": "Background",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "selected_items": "From {total} items, {selected} important content pieces were selected",
        "empty_analyzed": "Analyzed {total} items, but none met the importance threshold.",
        "empty_body": (
            "No significant developments today. This might indicate:\n"
            "- A quiet day in your tracked sources\n"
            "- The AI score threshold is too high\n"
            "- Your information sources need expansion\n\n"
            "Consider:\n"
            "1. Lowering the `ai_score_threshold` in config.json\n"
            "2. Adding more diverse information sources\n"
            "3. Checking if the AI model is working correctly\n"
        ),
    },
    "zh": {
        "header": "Horizon 每日速递",
        "source": "来源",
        "background": "背景",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "empty_analyzed": "已分析 {total} 条内容，但没有达到重要性阈值的条目。",
        "empty_body": (
            "今日暂无重要动态，可能原因：\n"
            "- 今天关注的信息源较平静\n"
            "- AI 评分阈值设置过高\n"
            "- 信息源种类有待扩充\n\n"
            "建议：\n"
            "1. 在 config.json 中降低 `ai_score_threshold`\n"
            "2. 添加更多多样化的信息源\n"
            "3. 检查 AI 模型是否正常工作\n"
        ),
    },
}


class DailySummarizer:
    """Generates daily Markdown summaries from pre-analyzed content items."""

    def __init__(self):
        pass

    async def generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary in Markdown format.

        Items are rendered in score-descending order (already sorted by orchestrator).

        Args:
            items: High-scoring content items (already enriched)
            date: Date string (YYYY-MM-DD)
            total_fetched: Total number of items fetched before filtering
            language: Output language, either "en" or "zh"

        Returns:
            str: Markdown formatted summary
        """
        labels = LABELS.get(language, LABELS["en"])

        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        header = (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['selected_items'].format(total=total_fetched, selected=len(items))}\n\n"
            "---\n\n"
        )

        # TOC
        toc_entries = []
        for i, item in enumerate(items):
            _t = item.metadata.get(f"title_{language}") or item.title
            t = str(_t).replace("[", "(").replace("]", ")")
            if language == "zh":
                t = _pangu(t)
            score = item.ai_score or "?"
            toc_entries.append(f"{i + 1}. [{t}](#item-{i + 1}) \u2b50\ufe0f {score}/10")
        toc = "\n".join(toc_entries) + "\n\n---\n\n"

        parts = [self._format_item(item, labels, language, i + 1) for i, item in enumerate(items)]

        return header + toc + "".join(parts)

    def generate_webhook_overview(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate a compact overview for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        if language == "zh":
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> 从 {total_fetched} 条内容中筛选出 {len(items)} 条重要资讯。\n\n"
                "下面会按新闻逐条发送详情，你可以只看感兴趣的标题。\n\n"
            )
        else:
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> Selected {len(items)} important items from {total_fetched} fetched items.\n\n"
                "Details will be sent item by item so you can read only the topics you care about.\n\n"
            )

        entries = []
        for i, item in enumerate(items, start=1):
            title = str(item.metadata.get(f"title_{language}") or item.title).replace("[", "(").replace("]", ")")
            if language == "zh":
                title = _pangu(title)
            score = item.ai_score or "?"
            entries.append(f"{i}. [{title}]({item.url}) \u2b50\ufe0f {score}/10")

        return header + "\n".join(entries)

    def generate_webhook_item(
        self,
        item: ContentItem,
        language: str,
        index: int,
        total: int,
    ) -> str:
        """Generate one item message for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        prefix = f"第 {index}/{total} 条\n\n" if language == "zh" else f"Item {index}/{total}\n\n"
        return prefix + self._format_item(item, labels, language, index).rstrip("-\n ")

    def _format_item(self, item: ContentItem, labels: dict, language: str, index: int) -> str:
        """Format a single ContentItem into Markdown."""
        _title = item.metadata.get(f"title_{language}") or item.title
        title = str(_title).replace("[", "(").replace("]", ")")
        url = str(item.url)
        score = item.ai_score or "?"
        meta = item.metadata

        summary = (
            meta.get(f"detailed_summary_{language}")
            or meta.get("detailed_summary")
            or item.ai_summary
            or ""
        )
        discussion = (
            meta.get(f"community_discussion_{language}")
            or meta.get("community_discussion")
            or ""
        )

        if language == "zh":
            title = _pangu(title)
            summary = _pangu(summary)
            discussion = _pangu(discussion)

        # Source line with parts joined by " · ", link appended at end
        source_type = item.source_type.value
        source_parts = [source_type]
        if meta.get("subreddit"):
            source_parts.append(f"r/{meta['subreddit']}")
        if meta.get("feed_name"):
            source_parts.append(meta["feed_name"])
        else:
            source_parts.append(item.author or "unknown")
        if item.published_at:
            if language == "zh":
                source_parts.append(
                    f"{item.published_at.month}月{item.published_at.day}日 "
                    f"{item.published_at:%H:%M}"
                )
            else:
                day = item.published_at.strftime("%d").lstrip("0")
                source_parts.append(item.published_at.strftime(f"%b {day}, %H:%M"))
        source_line = " \u00b7 ".join(source_parts)  # ·

        discussion_url = meta.get("discussion_url")
        if discussion_url:
            discussion_url = str(discussion_url)
            if discussion_url != url:
                source_line += f' · [{labels["discussion"]}]({discussion_url})'

        # Source provenance (new rich multi-source display)
        provenance = meta.get("source_provenance")
        provenance_html = ""
        if provenance and provenance.get("source_count", 0) > 1:
            primary_name = provenance.get("primary_source_name", "")
            primary_url = provenance.get("primary_source_url", "")
            primary_type = provenance.get("primary_source_type", "unknown")
            count = provenance["source_count"]
            sources = provenance.get("sources", [])

            # Primary source
            if language == "zh":
                primary_line = f"**主要来源**: [{primary_name}]({primary_url}) `{primary_type}`"
            else:
                primary_line = f"**Primary Source**: [{primary_name}]({primary_url}) `{primary_type}`"

            # Other sources
            other_sources = [s for s in sources if not s.get("is_primary")]
            other_lines = []
            if other_sources:
                if language == "zh":
                    other_lines.append(f"**其他来源** ({len(other_sources)}):")
                else:
                    other_lines.append(f"**Other Sources** ({len(other_sources)}):")
                for s in other_sources:
                    s_name = s.get("source_name", "")
                    s_url = s.get("source_url", "")
                    s_role = s.get("role", "unknown")
                    s_title = s.get("title", "")
                    if len(s_title) > 50:
                        s_title = s_title[:47] + "..."
                    other_lines.append(f"- [{s_name}]({s_url}) — {s_role}")
                other_block = "\n".join(other_lines)

            if language == "zh":
                provenance_html = (
                    f"\n\n**共 {count} 个来源报道**\n\n"
                    f"{primary_line}\n\n{other_block}"
                )
            else:
                provenance_html = (
                    f"\n\n**{count} sources covering this event**\n\n"
                    f"{primary_line}\n\n{other_block}"
                )

        # Source attribution (multi-source coverage) — backward-compat fallback
        attribution = meta.get("source_attribution")
        attribution_html = ""
        if attribution and attribution.get("count", 0) > 1:
            count = attribution["count"]
            disp_labels = attribution.get("labels", [])
            if len(disp_labels) > 2:
                label_summary = ", ".join(disp_labels[:2])
                if language == "zh":
                    attribution_summary = f"📰 {label_summary} 等 {count} 家报道"
                else:
                    attribution_summary = f"📰 {count} sources · {', '.join(disp_labels[:3])}"
            else:
                if language == "zh":
                    attribution_summary = f"📰 {', '.join(disp_labels)} 等 {count} 家报道"
                else:
                    attribution_summary = f"📰 {count} sources · {', '.join(disp_labels)}"

            detail_lines = []
            for d in attribution.get("detail", []):
                detail_lines.append(f"<li>[{d['label']}]({d['url']}) — {d['title']}</li>")
            detail_block = "\n".join(detail_lines)
            attribution_html = (
                f'\n\n<details><summary>{attribution_summary}</summary>\n\n'
                f'<ul>\n{detail_block}\n</ul>\n</details>'
            )

        lines = [
            f'<a id="item-{index}"></a>',
            f"## [{title}]({url}) ⭐️ {score}/10",  # ⭐️
            "",
            summary,
            "",
            source_line + provenance_html + attribution_html,
        ]

        reason = item.ai_reason or ""
        if reason:
            reason_zh = item.metadata.get("reason_zh") or reason
            if language == "zh":
                lines.insert(4, f"> **评分理由**: {reason_zh}")
            else:
                lines.insert(4, f"> **Reason**: {reason}")

        if discussion:
            lines.append("")
            lines.append(f"**{labels['discussion']}**: {discussion}")

        lines.append("")
        lines.append("---")

        return "\n".join(lines) + "\n\n"

    def _generate_empty_summary(self, date: str, total_fetched: int, labels: dict) -> str:
        """Generate summary when no high-scoring items were found."""
        return (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['empty_analyzed'].format(total=total_fetched)}\n\n"
            + labels["empty_body"]
        )
