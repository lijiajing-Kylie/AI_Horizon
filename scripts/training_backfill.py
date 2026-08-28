#!/usr/bin/env python3
"""一次性培训内容回填脚本。

从微信中间表(``wxmp_articles``)读最近 N 天的文章，用培训判定判断培训相关性，
培训相关的条目按文章发布时间回填进 ``items`` 表（``is_training=1, selected=1``），
供「培训」栏目 / ``/training`` 页展示。

用法：
    uv run python scripts/training_backfill.py --days 30 --dry-run   # 只打印判定结果，不落库
    uv run python scripts/training_backfill.py --days 30

背景：正常 ``horizon`` 运行时培训内容随日报一起抓取（普通源里 training_relevance
判定）。本脚本只用于一次性补充微信中间表里积累的历史培训内容；跑完即可删除。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 允许从任意 cwd 运行：把项目根加入 sys.path（uv run 默认只含脚本所在目录）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai.client import create_ai_client  # noqa: E402
from src.ai.training import is_accepted, judge_training_batch  # noqa: E402
from src.storage.db import HorizonDB  # noqa: E402
from src.storage.manager import StorageManager  # noqa: E402


def _build_row(art: dict, judge: dict, run_date: str) -> tuple:
    """中间表文章 + 判定结果 → items 表完整 INSERT 行。"""
    text = art.get("content_text") or ""
    metadata = {
        "feed_name": art.get("feed_name"),
        "weread_mp_id": art.get("weread_mp_id"),
        "training_relevance": judge["training_relevance"],
        "training_coverage": judge["training_coverage"],
        "is_ad": judge["is_ad"],
        "trainer_insight": judge["trainer_insight"],
        "category": "",
        "original_language": "zh",
    }
    return (
        art["id"],                      # 1  id
        "wechat",                       # 2  source_type
        art["title"],                   # 3  title
        art["url"],                     # 4  url
        text or None,                   # 5  content
        text or None,                   # 6  raw_content
        art.get("raw_html"),            # 7  raw_html
        art.get("display_html"),        # 8  display_html
        art.get("cover_image"),         # 9  cover_image
        "[]",                           # 10 images_json
        art.get("feed_name"),           # 11 author
        art["published_at"],            # 12 published_at
        art["published_at"],            # 13 fetched_at
        1,                              # 14 ai_relevant
        None,                           # 15 ai_score（培训不打分）
        judge["reason_zh"],             # 16 ai_reason
        judge["summary_zh"],            # 17 ai_summary
        "[]",                           # 18 ai_tags_json
        json.dumps(metadata, ensure_ascii=False),  # 19 metadata_json
        run_date,                       # 20 run_date
        datetime.now(timezone.utc).isoformat(),   # 21 created_at
        1,                              # 22 selected
        None,                           # 23 drop_reason
        None,                           # 24 category
        1,                              # 25 is_training
    )


_INSERT_SQL = """INSERT INTO items (
    id, source_type, title, url, content, raw_content, raw_html,
    display_html, cover_image, images_json, author, published_at,
    fetched_at, ai_relevant, ai_score, ai_reason, ai_summary,
    ai_tags_json, metadata_json, run_date, created_at, selected,
    drop_reason, category, is_training
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _upsert_training_rows(db: HorizonDB, rows: list[tuple]) -> tuple[int, int]:
    """落库：已存在 id 只标记 is_training=1（不动 run_date/selected），
    新 id 完整插入。返回 (inserted, updated)。"""
    conn = db.conn
    inserted = 0
    updated = 0
    for row in rows:
        exists = conn.execute("SELECT id FROM items WHERE id = ?", (row[0],)).fetchone()
        if exists:
            conn.execute(
                """UPDATE items SET is_training = 1, ai_relevant = 1,
                   ai_summary = ?, ai_reason = ?, metadata_json = ?,
                   selected = 1, drop_reason = NULL WHERE id = ?""",
                (row[16], row[15], row[18], row[0]),
            )
            updated += 1
        else:
            conn.execute(_INSERT_SQL, row)
            inserted += 1
    conn.commit()
    return inserted, updated


async def main() -> None:
    parser = argparse.ArgumentParser(description="从微信中间表回填培训内容到 items")
    parser.add_argument("--days", type=int, default=30, help="回看中间表的天数（默认 30）")
    parser.add_argument(
        "--min-age-days", type=int, default=0,
        help="跳过最近 N 天（窗口终点），用于只补更早的历史窗口；默认 0=取到今天",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印判定结果，不落库")
    args = parser.parse_args()

    config = StorageManager().load_config()
    if not config.filtering.training_enabled:
        print("[warn] filtering.training_enabled 未开启，跳过回填")
        return
    threshold = config.filtering.training_relevance_threshold

    db = HorizonDB()
    ai_client = create_ai_client(config.ai)

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    articles = db.get_wxmp_articles_window(since_ts=since.timestamp())
    if args.min_age_days > 0:
        # 跳过最近 min-age-days 天（已处理过的窗口），只补更早的历史段。
        # published_at 与 cutoff 都是同格式 UTC ISO 串，字典序比较可靠。
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.min_age_days)).replace(microsecond=0)
        articles = [a for a in articles if (a.get("published_at") or "") <= cutoff.isoformat()]
    window_desc = (
        f"{args.days} 天前 ~ {args.min_age_days} 天前"
        if args.min_age_days > 0
        else f"最近 {args.days} 天"
    )
    if not articles:
        print(f"中间表{window_desc}没有文章，无需回填")
        return
    print(f"中间表{window_desc}: {len(articles)} 篇文章")

    results = await judge_training_batch(
        ai_client, articles, concurrency=config.ai.analysis_concurrency or 5,
    )
    selected = [
        (a, r) for a, r in zip(articles, results)
        if is_accepted(r)
    ]
    print(f"判定完成: 通过培训筛选(正文 50%+ / 非广告 / 方法论层面有革新意义) {len(selected)} 篇")

    if args.dry_run:
        for a, r in selected[:30]:
            print(
                f"  [coverage={r['training_coverage']:.0%} is_ad={r['is_ad']} "
                f"insight={r['trainer_insight']:.1f}] {a['title']}"
            )
        print(f"(dry-run) 未落库，共 {len(selected)} 篇候选")
        return

    rows = [_build_row(a, r, a["published_at"][:10]) for a, r in selected]
    inserted, updated = _upsert_training_rows(db, rows)
    print(f"落库完成: 新增 {inserted} 条，已有 {updated} 条标记 is_training=1")


if __name__ == "__main__":
    asyncio.run(main())
