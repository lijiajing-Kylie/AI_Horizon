#!/usr/bin/env python3
"""Export horizon.db to static JSON files for the frontend (GitHub Pages).

Produces ``docs/data/`` with:
  - daily.json              — daily report list
  - daily-{date}.json       — each daily detail (items, stats, tags, topics)
  - topics.json             — all news topics grouped
  - categories.json         — category counts
  - tags.json               — tag counts
  - stats.json              — aggregate stats
  - runs.json               — run history
  - runs-dates.json         — list of dates with data
  - papers.json             — all papers (page 1)
  - paper-topics.json       — paper topic groups
  - reports.json            — all reports (page 1)
  - report-institutions.json — institution list

Usage:
    python scripts/export_static_data.py [--db data/horizon.db] [--out docs/data]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _split_institutions(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\s*[&,、;；]\s*", raw)
    return [p.strip() for p in parts if p.strip()]


def _row_to_item(row: sqlite3.Row) -> dict:
    """Mirrors ``_row_to_item`` in ``src/storage/db.py``."""
    return {
        "id": row["id"],
        "source_type": row["source_type"],
        "title": row["title"],
        "url": row["url"],
        "content": row["content"],
        "raw_content": row["raw_content"] if "raw_content" in row.keys() else None,
        "raw_html": row["raw_html"] if "raw_html" in row.keys() else None,
        "display_html": row["display_html"] if "display_html" in row.keys() else None,
        "display_html_zh": row["display_html_zh"] if "display_html_zh" in row.keys() else None,
        "cover_image": row["cover_image"] if "cover_image" in row.keys() else None,
        "images": json.loads(row["images_json"]) if "images_json" in row.keys() and row["images_json"] else [],
        "author": row["author"],
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "ai_relevant": bool(row["ai_relevant"]) if row["ai_relevant"] is not None else None,
        "ai_score": row["ai_score"],
        "ai_reason": row["ai_reason"],
        "ai_summary": row["ai_summary"],
        "ai_tags": json.loads(row["ai_tags_json"]),
        "metadata": json.loads(row["metadata_json"]),
        "run_date": row["run_date"],
        "selected": bool(row["selected"]) if "selected" in row.keys() else False,
        "drop_reason": row["drop_reason"] if "drop_reason" in row.keys() else None,
    }


def _build_content_block(item: dict) -> dict:
    """Mirrors ``_build_content`` in ``src/api/server.py``."""
    meta: dict = item.get("metadata") or {}
    original = meta.get("original_language", "unknown")
    available = meta.get("available_languages", [])
    if not available:
        if meta.get("title_zh"):
            available.append("zh")
        if meta.get("title_en"):
            available.append("en")
        if not available:
            available.append("en")

    content: dict[str, dict] = {}
    for lang in available:
        content[lang] = {
            "title": meta.get(f"title_{lang}") or item.get("title", ""),
            "summary": meta.get(f"detailed_summary_{lang}") or item.get("ai_summary", ""),
            "reason": meta.get(f"reason_{lang}") or item.get("ai_reason", ""),
            "community_discussion": meta.get(f"community_discussion_{lang}") or meta.get("community_discussion", ""),
        }

    return {
        "original_language": original,
        "default_language": meta.get("default_display_language", "zh"),
        "is_ai_translated": meta.get("is_ai_translated", False),
        "content": content,
        "enrichment_sources": meta.get("enrichment_sources", []),
        "discussion_url": meta.get("discussion_url"),
        "source_provenance": meta.get("source_provenance"),
        "source_attribution": meta.get("source_attribution"),
    }


def _row_to_paper(row: sqlite3.Row) -> dict:
    """Mirrors ``_row_to_paper`` in ``src/storage/db.py``."""
    return {
        "id": row["id"],
        "source": row["source"],
        "native_id": row["native_id"],
        "title": row["title"],
        "authors": json.loads(row["authors_json"]),
        "abstract": row["abstract"],
        "url": row["url"],
        "pdf_url": row["pdf_url"],
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
        "publication_year": row["publication_year"],
        "categories": json.loads(row["categories_json"]),
        "category": row["category"],
        "comment": row["comment"],
        "journal_ref": row["journal_ref"],
        "doi": row["doi"],
        "open_access": bool(row["open_access"]) if row["open_access"] is not None else None,
        "citation_count": row["citation_count"],
        "citation_percentile": row["citation_percentile"],
        "upvote_count": row["upvote_count"],
        "title_zh": row["title_zh"],
        "abstract_zh": row["abstract_zh"],
        "original_language": row["original_language"],
        "fetched_at": row["fetched_at"],
    }


def _row_to_report(row: sqlite3.Row) -> dict:
    """Mirrors ``_row_to_report`` in ``src/storage/db.py``."""
    pdf_urls: list[dict] = json.loads(row["pdf_urls_json"])
    for entry in pdf_urls:
        lp = entry.get("local_path")
        if lp and lp.startswith("data/"):
            entry["local_path"] = "/api/reports/pdfs/" + lp.removeprefix("data/reports_pdfs/")
    has_local_pdf = any("local_path" in entry for entry in pdf_urls)
    return {
        "id": row["id"],
        "source": row["source"],
        "native_id": row["native_id"],
        "title": row["title"],
        "institution": row["institution"],
        "institutions": _split_institutions(row["institution"]),
        "author": row["author"],
        "url": row["url"],
        "pdf_urls": pdf_urls,
        "has_local_pdf": has_local_pdf,
        "summary": row["summary"],
        "content_text": row["content_text"],
        "categories": json.loads(row["categories_json"]),
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
        "view_count": row["view_count"],
        "download_count": row["download_count"],
        "fetched_at": row["fetched_at"],
    }


# ── main ─────────────────────────────────────────────────────────────────────

def export(db_path: str, out_dir: str) -> int:
    """Export data from SQLite to JSON files. Returns number of files written."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = 0

    def write_json(name: str, data) -> None:
        with open(out / name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        nonlocal written
        written += 1
        print(f"  wrote {name}  ({len(json.dumps(data, ensure_ascii=False, default=str))} bytes)")

    def paginated(items_data: list, total: int, page: int = 1, per_page: int = 200) -> dict:
        return {
            "items": items_data,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    # ── runs / daily ───────────────────────────────────────────────────────
    runs = conn.execute(
        "SELECT * FROM daily_runs ORDER BY date DESC LIMIT 30"
    ).fetchall()

    runs_list = [
        {
            "date": r["date"],
            "total_fetched": r["total_fetched"],
            "total_selected": r["total_selected"],
            "languages": json.loads(r["languages"]),
            "created_at": r["created_at"],
        }
        for r in runs
    ]
    write_json("runs.json", runs_list)

    run_dates = [
        r["run_date"] for r in conn.execute(
            "SELECT DISTINCT run_date FROM items ORDER BY run_date DESC LIMIT 30"
        ).fetchall()
    ]
    write_json("runs-dates.json", run_dates)

    daily_reports = [
        {
            "date": r["date"],
            "total_fetched": r["total_fetched"],
            "total_selected": r["total_selected"],
            "languages": json.loads(r["languages"]),
        }
        for r in runs
    ]
    write_json("daily.json", {"reports": daily_reports})

    # ── items + daily-{date} per run date ────────────────────────────────
    items_by_date: dict[str, list[dict]] = {}

    all_selected = conn.execute(
        "SELECT * FROM items WHERE selected = 1 ORDER BY run_date DESC, ai_score DESC"
    ).fetchall()

    for row in all_selected:
        item = _row_to_item(row)
        date = item["run_date"]
        items_by_date.setdefault(date, []).append(item)

    # Attach topics to items
    topic_map: dict[str, list[dict]] = {}
    topic_rows = conn.execute(
        """SELECT nt.news_id, t.id, t.name, t.slug, t.group_name,
                  t.description, nt.confidence, nt.reason
           FROM news_topics nt
           JOIN topics t ON t.id = nt.topic_id
           WHERE t.is_active = 1"""
    ).fetchall()
    for tr in topic_rows:
        tid = tr["news_id"]
        topic_map.setdefault(tid, []).append({
            "id": tr["id"],
            "name": tr["name"],
            "slug": tr["slug"],
            "group_name": tr["group_name"],
            "description": tr["description"],
            "confidence": tr["confidence"],
            "reason": tr["reason"],
        })

    # Also store a flat items-index for quick lookup (no heavy content fields)
    items_index: list[dict] = []
    for date, items_list in items_by_date.items():
        items_with_topics = []
        for it in items_list:
            topics = topic_map.get(it["id"], [])
            it["topics"] = topics
            it["content_block"] = _build_content_block(it)
            items_with_topics.append(it)

            items_index.append({
                "id": it["id"],
                "title": it["title"],
                "source_type": it["source_type"],
                "url": it["url"],
                "published_at": it["published_at"],
                "ai_score": it["ai_score"],
                "ai_tags": it["ai_tags"],
                "run_date": it["run_date"],
                "category": it.get("metadata", {}).get("category"),
                "topics": [{"slug": t["slug"], "name": t["name"]} for t in topics],
            })

        # Write daily-{date}.json
        daily_items = items_with_topics

        # Stats for this date
        stats_row = conn.execute(
            """SELECT COUNT(*) AS total_items,
                      AVG(ai_score) AS avg_score,
                      MAX(ai_score) AS max_score,
                      COUNT(DISTINCT source_type) AS source_types
               FROM items WHERE run_date = ? AND selected = 1""",
            (date,),
        ).fetchone()
        stats = {
            "total_items": stats_row["total_items"],
            "avg_score": round(stats_row["avg_score"], 2) if stats_row["avg_score"] else None,
            "max_score": stats_row["max_score"],
            "source_types": stats_row["source_types"],
        }

        # Tags for this date
        tags = [
            {"tag": r["tag"], "count": r["count"]}
            for r in conn.execute(
                """SELECT value AS tag, COUNT(*) AS count
                   FROM items, json_each(ai_tags_json)
                   WHERE run_date = ? AND selected = 1
                   GROUP BY value HAVING COUNT(*) >= 1
                   ORDER BY count DESC""",
                (date,),
            ).fetchall()
        ]

        daily_detail = {
            "date": date,
            "stats": stats,
            "tags": tags,
            "topics": {},  # populated below
            "items": daily_items,
            "total": len(daily_items),
        }
        write_json(f"daily-{date}.json", daily_detail)

    # ── topics ────────────────────────────────────────────────────────────
    topic_rows_raw = conn.execute(
        """SELECT t.*, COUNT(i.id) AS count
           FROM topics t
           LEFT JOIN news_topics nt ON t.id = nt.topic_id
           LEFT JOIN items i ON nt.news_id = i.id AND i.selected = 1
           WHERE t.is_active = 1
           GROUP BY t.id
           ORDER BY t.group_name, t.sort_order, t.name"""
    ).fetchall()

    topics_all = []
    for t in topic_rows_raw:
        topic_dict = {
            "id": t["id"],
            "name": t["name"],
            "slug": t["slug"],
            "group_name": t["group_name"],
            "description": t["description"],
            "keywords": json.loads(t["keywords"]),
            "aliases": json.loads(t["aliases"]),
            "sort_order": t["sort_order"],
            "is_active": bool(t["is_active"]),
            "count": t["count"],
        }
        topics_all.append(topic_dict)

    # Grouped
    groups: dict[str, list[dict]] = {}
    for t in topics_all:
        groups.setdefault(t["group_name"], []).append(t)
    topics_grouped = {
        "groups": [
            {"group_name": gn, "topics": groups[gn]}
            for gn in groups
        ]
    }
    write_json("topics.json", topics_grouped)

    # Also backfill topics into daily-{date} files
    for date in items_by_date:
        daily_path = out / f"daily-{date}.json"
        if daily_path.exists():
            with open(daily_path, "r") as f:
                daily_data = json.load(f)
            # Filter topics to only those with items in this date
            date_topic_slugs = set()
            for it in daily_data.get("items", []):
                for tp in it.get("topics", []):
                    date_topic_slugs.add(tp["slug"])
            filtered_groups = []
            for group in topics_grouped["groups"]:
                filtered_topics = [t for t in group["topics"] if t["slug"] in date_topic_slugs]
                if filtered_topics:
                    filtered_groups.append({"group_name": group["group_name"], "topics": filtered_topics})
            daily_data["topics"] = {"groups": filtered_groups}
            with open(daily_path, "w", encoding="utf-8") as f:
                json.dump(daily_data, f, ensure_ascii=False, default=str)

    # ── items index (lightweight, id → run_date mapping) ────────────────
    write_json("items-index.json", items_index)

    # ── categories ────────────────────────────────────────────────────────
    cat_rows = conn.execute(
        """SELECT category, COUNT(*) AS count
           FROM items WHERE selected = 1
           GROUP BY category ORDER BY count DESC"""
    ).fetchall()
    write_json("categories.json", [
        {"category": r["category"] or "unknown", "count": r["count"]}
        for r in cat_rows
    ])

    # ── tags (global) ─────────────────────────────────────────────────────
    tag_rows = conn.execute(
        """SELECT value AS tag, COUNT(*) AS count
           FROM items, json_each(ai_tags_json)
           WHERE selected = 1
           GROUP BY value HAVING COUNT(*) >= 1
           ORDER BY count DESC"""
    ).fetchall()
    write_json("tags.json", [
        {"tag": r["tag"], "count": r["count"]} for r in tag_rows
    ])

    # ── stats (global) ────────────────────────────────────────────────────
    stats_row = conn.execute(
        """SELECT COUNT(*) AS total_items,
                  AVG(ai_score) AS avg_score,
                  MAX(ai_score) AS max_score,
                  COUNT(DISTINCT source_type) AS source_types
           FROM items WHERE selected = 1"""
    ).fetchone()
    write_json("stats.json", {
        "total_items": stats_row["total_items"],
        "avg_score": round(stats_row["avg_score"], 2) if stats_row["avg_score"] else None,
        "max_score": stats_row["max_score"],
        "source_types": stats_row["source_types"],
    })

    # ── papers ────────────────────────────────────────────────────────────
    total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    paper_rows = conn.execute(
        f"SELECT * FROM papers ORDER BY published_at DESC"
    ).fetchall()
    papers = [_row_to_paper(r) for r in paper_rows]

    # Batch-attach topics
    paper_ids = [p["id"] for p in papers]
    paper_topics_map: dict[str, list[dict]] = {}
    if paper_ids:
        placeholders = ",".join("?" * len(paper_ids))
        pt_rows = conn.execute(
            f"""SELECT pt.paper_id, t.id, t.name, t.slug, t.group_name,
                       t.description, pt.confidence, pt.reason
               FROM paper_topics pt
               JOIN topics t ON t.id = pt.topic_id
               WHERE pt.paper_id IN ({placeholders})""",
            paper_ids,
        ).fetchall()
        for ptr in pt_rows:
            paper_topics_map.setdefault(ptr["paper_id"], []).append({
                "id": ptr["id"],
                "name": ptr["name"],
                "slug": ptr["slug"],
                "group_name": ptr["group_name"],
                "description": ptr["description"],
                "confidence": ptr["confidence"],
                "reason": ptr["reason"],
            })
    for p in papers:
        p["topics"] = paper_topics_map.get(p["id"], [])

    write_json("papers.json", paginated(papers, total_papers))

    # ── paper topics ──────────────────────────────────────────────────────
    paper_topic_groups: dict[str, list[dict]] = {}
    pt_rows = conn.execute(
        """SELECT t.*, COUNT(pt.paper_id) AS paper_count
           FROM topics t
           JOIN paper_topics pt ON t.id = pt.topic_id
           WHERE t.is_active = 1
           GROUP BY t.id
           ORDER BY t.group_name, t.sort_order, t.name"""
    ).fetchall()
    for ptr in pt_rows:
        entry = {
            "id": ptr["id"],
            "name": ptr["name"],
            "slug": ptr["slug"],
            "group_name": ptr["group_name"],
            "description": ptr["description"],
            "paper_count": ptr["paper_count"],
        }
        paper_topic_groups.setdefault(ptr["group_name"], []).append(entry)
    write_json("paper-topics.json", {
        "groups": [
            {"group_name": gn, "topics": paper_topic_groups[gn]}
            for gn in paper_topic_groups
        ]
    })

    # ── reports ───────────────────────────────────────────────────────────
    total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    report_rows = conn.execute(
        "SELECT * FROM reports ORDER BY published_at DESC"
    ).fetchall()
    reports = [_row_to_report(r) for r in report_rows]
    write_json("reports.json", paginated(reports, total_reports))

    # ── report institutions ───────────────────────────────────────────────
    inst_rows = conn.execute("SELECT source, institution FROM reports").fetchall()
    inst_count: dict[str, int] = {}
    for ir in inst_rows:
        for inst in _split_institutions(ir["institution"]):
            key = f"{ir['source']}::{inst}"
            inst_count[key] = inst_count.get(key, 0) + 1
    inst_list = []
    for key, cnt in inst_count.items():
        src, inst = key.split("::", 1)
        inst_list.append({"institution": inst, "source": src, "count": cnt})
    inst_list.sort(key=lambda x: -x["count"])
    write_json("report-institutions.json", inst_list)

    conn.close()
    print(f"\n✓ Exported {written} files to {out}")
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export horizon.db to static JSON")
    parser.add_argument("--db", default="data/horizon.db", help="Path to horizon.db")
    parser.add_argument("--out", default="docs/data", help="Output directory")
    args = parser.parse_args()
    sys.exit(export(args.db, args.out))