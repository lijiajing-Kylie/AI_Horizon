#!/usr/bin/env python
"""从 DB 中已打分的 items 重新渲染指定日期的日报，不调用任何 LLM。

背景：orchestrator 重跑某一天会重新抓取 + AI 分析（消耗 token），并把该天
items 快照 DELETE 重建、覆盖当天日报文件。本脚本绕开 AI，只复用库里已经
落盘的打分结果，用新的过滤阈值（min-score）重新渲染日报。

用法：
  # 只预览条数与标题（不写文件）
  uv run python scripts/rerender_daily.py --date 2026-08-27 --min-score 6.5

  # 写到临时文件（不覆盖现有日报）
  uv run python scripts/rerender_daily.py --date 2026-08-27 --min-score 6.0 \
      --out /tmp/horizon-2026-08-27-rich.md

  # 直接写回 data/summaries/ 与 docs/_posts/（覆盖当天 zh 日报）
  uv run python scripts/rerender_daily.py --date 2026-08-27 --min-score 6.0 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.ai.summarizer import DailySummarizer
from src.filtering import select_training_items
from src.models import ContentItem
from src.storage.db import HorizonDB
from src.storage.manager import StorageManager

# get_items 返回的 dict 里这些键不是 ContentItem 字段，需剔除
_NON_MODEL_KEYS = ("topics", "is_favorited", "note", "selected", "drop_reason", "run_date")


def load_items(db: HorizonDB, date: str) -> tuple[list[dict], int]:
    """加载某天全部已打分 items（含被丢弃项）。返回 (raw dicts, 抓取总数)。"""
    res = db.get_items(run_date=date, selected_only=False, per_page=500)
    raw = res["items"]
    # 抓取总数优先用 daily_runs 记录（与原日报 header 一致），否则用 items 数
    try:
        row = db.conn.execute(
            "SELECT total_fetched FROM daily_runs WHERE date = ?", (date,)
        ).fetchone()
        total = int(row[0]) if row else len(raw)
    except Exception:
        total = len(raw)
    return raw, total


def to_content_items(raw_items: list[dict]) -> list[ContentItem]:
    items: list[ContentItem] = []
    for d in raw_items:
        d = {k: v for k, v in d.items() if k not in _NON_MODEL_KEYS}
        try:
            item = ContentItem.model_validate(d)
        except Exception as exc:  # 单条失败不中断整批
            print(f"  [skip] {d.get('id', '?')}: {exc}", file=sys.stderr)
            continue
        # training_relevance 只持久化在 metadata，DB 行没有顶层列——恢复回顶层，
        # 否则 select_training_items 读不到（它用 item.training_relevance）。
        if item.training_relevance is None and item.metadata.get("training_relevance") is not None:
            item.training_relevance = item.metadata["training_relevance"]
        items.append(item)
    return items


def build_digest(
    items: list[ContentItem],
    min_score: float,
    max_items: int | None,
    filtering,
) -> tuple[list[ContentItem], list[ContentItem]]:
    """按培训子轨 + 新闻主轨过滤。

    培训子轨：training_relevance >= threshold 即入选（与 orchestrator 一致）。
    新闻主轨：ai_relevant=True 且 ai_score >= min_score，分数降序。
    """
    training, _ = select_training_items(items, filtering)

    news = [
        i
        for i in items
        if not i.is_training
        and i.ai_relevant is True
        and (i.ai_score or 0.0) >= min_score
    ]
    news.sort(key=lambda i: i.ai_score or 0.0, reverse=True)
    if max_items is not None:
        news = news[:max_items]
    return news, training


def render(summary_items: list[ContentItem], date: str, total: int, language: str) -> str:
    return asyncio.run(
        DailySummarizer().generate_summary(
            summary_items, date, total, language=language
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default="2026-08-27", help="run_date (YYYY-MM-DD)")
    ap.add_argument("--min-score", type=float, default=6.0, help="新闻最低分（默认 6.0）")
    ap.add_argument("--max-items", type=int, default=None, help="新闻条数上限（默认不限制）")
    ap.add_argument("--language", default="zh", help="输出语言（zh/en）")
    ap.add_argument("--out", default=None, help="写到临时文件（不覆盖现有日报）")
    ap.add_argument("--apply", action="store_true", help="写回 data/summaries/ + docs/_posts/（覆盖）")
    ap.add_argument("--sync-db", action="store_true", help="同步 DB 的 selected/drop_reason 标记（不写文件）")
    ap.add_argument("--no-training", action="store_true", help="日报不含培训子轨（培训只在 /training 页）")
    args = ap.parse_args()

    config = StorageManager().load_config()
    db = HorizonDB()
    raw_items, total_fetched = load_items(db, args.date)

    items = to_content_items(raw_items)
    if not items:
        print(f"没有 {args.date} 的已打分 items", file=sys.stderr)
        sys.exit(1)

    news, training = build_digest(items, args.min_score, args.max_items, config.filtering)
    if args.no_training:
        final = news
    else:
        final = news + training

    print(
        f"{args.date}: 库中 {len(items)} 条，相关 {sum(1 for i in items if i.ai_relevant)} 条，"
        f">= {args.min_score} 分新闻 {len(news)} 条 + 培训 {len(training)} 条 = {len(final)} 条"
    )

    if args.sync_db:
        # 与 orchestrator 的 mark_selected 同语义：重置当日标记后写幸存者与丢弃原因。
        # 前端 /api/daily 按 selected=1 读条目，不同步则页面与 md 文件不一致。
        selected_ids = {i.id for i in final}
        drop: dict[str, str] = {}
        for it in items:
            if it.id in selected_ids or it.is_training:
                continue
            if it.ai_relevant is not True:
                drop[it.id] = "relevance"
            elif (it.ai_score or 0.0) < args.min_score:
                drop[it.id] = "score"
            else:
                drop[it.id] = "category_quota"
        updated = db.mark_selected(selected_ids, drop, args.date)
        print(f"已同步 DB：selected={len(selected_ids)}，drop 标注 {updated} 条")
        return

    summary = render(final, args.date, total_fetched, args.language)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(summary, encoding="utf-8")
        print(f"已写入 {out}")
        print("---- 预览（前 28 行）----")
        print("\n".join(summary.splitlines()[:28]))
    elif args.apply:
        mgr = StorageManager()
        path = mgr.save_daily_summary(args.date, summary, language=args.language)
        dest = mgr.publish_to_github_pages(args.date, summary, language=args.language)
        print(f"已覆盖 {path}")
        print(f"已发布 {dest}")
    else:
        print("---- 预览（前 32 行）----")
        print("\n".join(summary.splitlines()[:32]))
        print("...")
        print("（未写文件。加 --out 写临时文件，或 --apply 直接覆盖当天日报）")


if __name__ == "__main__":
    main()
