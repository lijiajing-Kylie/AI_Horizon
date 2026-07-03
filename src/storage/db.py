"""SQLite database for persisting scored/enriched items and daily runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from ..models import ContentItem


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    content         TEXT,
    author          TEXT,
    published_at    TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    ai_relevant     INTEGER,
    ai_score        REAL,
    ai_reason       TEXT,
    ai_summary      TEXT,
    ai_tags_json    TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    run_date        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_items_run_date ON items(run_date);
CREATE INDEX IF NOT EXISTS idx_items_ai_score ON items(ai_score);
CREATE INDEX IF NOT EXISTS idx_items_source_type ON items(source_type);
CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, ai_summary, ai_reason, ai_tags_json,
    content='items', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, ai_summary, ai_reason, ai_tags_json)
    VALUES (new.rowid, new.title, new.ai_summary, new.ai_reason, new.ai_tags_json);
END;

CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, ai_summary, ai_reason, ai_tags_json)
    VALUES ('delete', old.rowid, old.title, old.ai_summary, old.ai_reason, old.ai_tags_json);
END;

CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, ai_summary, ai_reason, ai_tags_json)
    VALUES ('delete', old.rowid, old.title, old.ai_summary, old.ai_reason, old.ai_tags_json);
    INSERT INTO items_fts(rowid, title, ai_summary, ai_reason, ai_tags_json)
    VALUES (new.rowid, new.title, new.ai_summary, new.ai_reason, new.ai_tags_json);
END;

CREATE TABLE IF NOT EXISTS daily_runs (
    date            TEXT PRIMARY KEY,
    total_fetched   INTEGER NOT NULL DEFAULT 0,
    total_selected  INTEGER NOT NULL DEFAULT 0,
    languages       TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    group_name      TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    keywords        TEXT NOT NULL DEFAULT '[]',
    aliases         TEXT NOT NULL DEFAULT '[]',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_topics_slug ON topics(slug);
CREATE INDEX IF NOT EXISTS idx_topics_group_name ON topics(group_name);

CREATE TABLE IF NOT EXISTS news_topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id         TEXT NOT NULL,
    topic_id        INTEGER NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.0,
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (news_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    UNIQUE(news_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_news_topics_news_id ON news_topics(news_id);
CREATE INDEX IF NOT EXISTS idx_news_topics_topic_id ON news_topics(topic_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a DB row to a JSON-serializable dict matching the ContentItem shape."""
    return {
        "id": row["id"],
        "source_type": row["source_type"],
        "title": row["title"],
        "url": row["url"],
        "content": row["content"],
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
    }


class HorizonDB:
    """SQLite persistence for Horizon pipeline outputs."""

    def __init__(self, db_path: str = "data/horizon.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- write ----------------------------------------------------------------

    def save_items(self, items: List[ContentItem], run_date: str, total_fetched: int) -> int:
        """Persist scored/enriched items for a given date.

        Replaces any existing items for the same run_date (idempotent).
        """
        # Delete existing items for this date first
        self.conn.execute("DELETE FROM items WHERE run_date = ?", (run_date,))

        rows: list[tuple] = []
        for item in items:
            rows.append((
                item.id,
                item.source_type.value,
                item.title,
                str(item.url),
                item.content,
                item.author,
                _dt_iso(item.published_at),
                _dt_iso(item.fetched_at),
                1 if item.ai_relevant else 0,
                item.ai_score,
                item.ai_reason,
                item.ai_summary,
                json.dumps(item.ai_tags, ensure_ascii=False),
                json.dumps(item.metadata, ensure_ascii=False, default=str),
                run_date,
                _now_iso(),
            ))

        self.conn.executemany(
            """INSERT INTO items (
                id, source_type, title, url, content, author,
                published_at, fetched_at, ai_relevant, ai_score,
                ai_reason, ai_summary, ai_tags_json, metadata_json,
                run_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        # Upsert daily run record
        languages = list({item.metadata.get("language", "unknown") for item in items}) if items else []
        self.conn.execute(
            """INSERT INTO daily_runs (date, total_fetched, total_selected, languages)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               total_fetched = excluded.total_fetched,
               total_selected = excluded.total_selected,
               languages = excluded.languages""",
            (run_date, total_fetched, len(items), json.dumps(languages)),
        )

        self.conn.commit()
        return len(items)

    # -- read ----------------------------------------------------------------

    def get_items(
        self,
        *,
        run_date: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        source_type: Optional[str] = None,
        search: Optional[str] = None,
        min_score: Optional[float] = None,
        sort: str = "ai_score",
        order: str = "desc",
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Paginated item query with optional filters."""
        where = []
        params: list[Any] = []

        if run_date:
            where.append("run_date = ?")
            params.append(run_date)

        if category:
            where.append("json_extract(metadata_json, '$.category') = ?")
            params.append(category)

        if source_type:
            where.append("source_type = ?")
            params.append(source_type)

        if min_score is not None:
            where.append("ai_score >= ?")
            params.append(min_score)

        where_clause = " AND ".join(where) if where else "1=1"

        # Build the base query
        if search:
            # FTS5 search — join on rowid
            base_from = (
                "FROM items JOIN items_fts ON items.rowid = items_fts.rowid "
                f"WHERE items_fts MATCH ? AND {where_clause}"
            )
            params.insert(0, search)
        elif tag:
            # Tag filter via JSON array containment
            tag_clause = "EXISTS (SELECT 1 FROM json_each(ai_tags_json) WHERE value = ?)"
            base_from = f"FROM items WHERE {tag_clause} AND {where_clause}"
            params.insert(0, tag)
        else:
            base_from = f"FROM items WHERE {where_clause}"

        # Count
        count_row = self.conn.execute(
            f"SELECT COUNT(*) as cnt {base_from}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # Fetch page
        allowed_sort = {"ai_score", "published_at", "created_at", "run_date"}
        sort_col = sort if sort in allowed_sort else "ai_score"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        offset = (page - 1) * per_page

        rows = self.conn.execute(
            f"SELECT * {base_from} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        items = [_row_to_item(r) for r in rows]
        # Batch-fill topics for each item
        topics_map = self._batch_get_news_topics([item["id"] for item in items])
        for item in items:
            item["topics"] = topics_map.get(item["id"], [])

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        """Get a single item by ID with topics."""
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = _row_to_item(row)
        item["topics"] = self.get_news_topics(item_id)
        return item

    def get_tags(self, run_date: Optional[str] = None, min_count: int = 1) -> list[dict[str, Any]]:
        """Get all tags with occurrence counts."""
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)

        rows = self.conn.execute(
            f"""SELECT value AS tag, COUNT(*) AS count
                FROM items, json_each(ai_tags_json)
                WHERE {where}
                GROUP BY value
                HAVING COUNT(*) >= ?
                ORDER BY count DESC""",
            params + [min_count],
        ).fetchall()
        return [{"tag": r["tag"], "count": r["count"]} for r in rows]

    def get_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        """Get recent daily runs."""
        rows = self.conn.execute(
            "SELECT * FROM daily_runs ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "date": r["date"],
                "total_fetched": r["total_fetched"],
                "total_selected": r["total_selected"],
                "languages": json.loads(r["languages"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_run_dates(self, limit: int = 30) -> list[str]:
        """Get list of dates that have data."""
        rows = self.conn.execute(
            "SELECT DISTINCT run_date FROM items ORDER BY run_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["run_date"] for r in rows]

    def get_category_counts(self, run_date: Optional[str] = None) -> list[dict[str, Any]]:
        """Get item counts by category."""
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)

        rows = self.conn.execute(
            f"""SELECT json_extract(metadata_json, '$.category') AS category,
                       COUNT(*) AS count
                FROM items
                WHERE {where}
                GROUP BY category
                ORDER BY count DESC""",
            params,
        ).fetchall()
        return [{"category": r["category"] or "unknown", "count": r["count"]} for r in rows]

    def get_stats(self, run_date: Optional[str] = None) -> dict[str, Any]:
        """Get aggregate statistics."""
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)

        row = self.conn.execute(
            f"""SELECT
                    COUNT(*) AS total_items,
                    AVG(ai_score) AS avg_score,
                    MAX(ai_score) AS max_score,
                    COUNT(DISTINCT source_type) AS source_types
                FROM items WHERE {where}""",
            params,
        ).fetchone()

        return {
            "total_items": row["total_items"],
            "avg_score": round(row["avg_score"], 2) if row["avg_score"] else None,
            "max_score": row["max_score"],
            "source_types": row["source_types"],
        }

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across title, summary, reason, and tags."""
        rows = self.conn.execute(
            """SELECT items.* FROM items
               JOIN items_fts ON items.rowid = items_fts.rowid
               WHERE items_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        items = [_row_to_item(r) for r in rows]
        # Batch-fill topics
        topics_map = self._batch_get_news_topics([item["id"] for item in items])
        for item in items:
            item["topics"] = topics_map.get(item["id"], [])
        return items

    # -- topics ----------------------------------------------------------------

    def seed_topics(self, topics_data: list[dict[str, Any]]) -> int:
        """Insert or update topics from a seed data list (idempotent by slug).

        Each entry should have: name, slug, group_name, description,
        keywords (list), aliases (list), sort_order, is_active.
        Returns the number of topics upserted.
        """
        count = 0
        for t in topics_data:
            self.conn.execute(
                """INSERT INTO topics (name, slug, group_name, description,
                       keywords, aliases, sort_order, is_active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(slug) DO UPDATE SET
                       name = excluded.name,
                       group_name = excluded.group_name,
                       description = excluded.description,
                       keywords = excluded.keywords,
                       aliases = excluded.aliases,
                       sort_order = excluded.sort_order,
                       is_active = excluded.is_active,
                       updated_at = excluded.updated_at""",
                (
                    t["name"],
                    t["slug"],
                    t["group_name"],
                    t.get("description", ""),
                    json.dumps(t.get("keywords", []), ensure_ascii=False),
                    json.dumps(t.get("aliases", []), ensure_ascii=False),
                    t.get("sort_order", 0),
                    t.get("is_active", 1),
                    _now_iso(),
                ),
            )
            count += 1
        self.conn.commit()
        return count

    def get_topics(self, *, grouped: bool = True) -> dict[str, Any]:
        """Get all active topics, optionally grouped by group_name.

        When grouped=True, returns:
            {"groups": [{"group_name": "...", "topics": [...]}, ...]}

        When grouped=False, returns:
            {"topics": [...]}

        Each topic includes a `count` of associated news items.
        """
        rows = self.conn.execute(
            """SELECT t.*, COUNT(nt.news_id) AS count
               FROM topics t
               LEFT JOIN news_topics nt ON t.id = nt.topic_id
               WHERE t.is_active = 1
               GROUP BY t.id
               ORDER BY t.group_name, t.sort_order, t.name""",
        ).fetchall()

        topics = [
            {
                "id": r["id"],
                "name": r["name"],
                "slug": r["slug"],
                "group_name": r["group_name"],
                "description": r["description"],
                "keywords": json.loads(r["keywords"]),
                "aliases": json.loads(r["aliases"]),
                "sort_order": r["sort_order"],
                "is_active": bool(r["is_active"]),
                "count": r["count"],
            }
            for r in rows
        ]

        if not grouped:
            return {"topics": topics}

        # Group by group_name, preserving insertion order
        groups: dict[str, list[dict]] = {}
        for t in topics:
            groups.setdefault(t["group_name"], []).append(t)

        group_names = list(groups.keys())
        return {"groups": [{"group_name": gn, "topics": groups[gn]} for gn in group_names]}

    def get_topic_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        """Get a single topic by its slug."""
        row = self.conn.execute(
            "SELECT * FROM topics WHERE slug = ? AND is_active = 1", (slug,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "group_name": row["group_name"],
            "description": row["description"],
            "keywords": json.loads(row["keywords"]),
            "aliases": json.loads(row["aliases"]),
            "sort_order": row["sort_order"],
            "is_active": bool(row["is_active"]),
        }

    def save_news_topics(
        self, news_id: str, topics_data: list[dict[str, Any]]
    ) -> int:
        """Save topic associations for a news item.

        topics_data is a list of dicts with keys: slug, confidence, reason.
        Upserts by (news_id, topic_id) — re-running on the same news_id
        updates confidence and reason instead of creating duplicates.

        Returns the number of topic associations saved.
        """
        count = 0
        for td in topics_data:
            slug = td.get("slug", "").strip()
            if not slug:
                continue

            topic = self.conn.execute(
                "SELECT id FROM topics WHERE slug = ? AND is_active = 1", (slug,)
            ).fetchone()

            if topic is None:
                # Topic slug not in our database — log and skip
                print(f"Warning: unknown topic slug '{slug}' for item {news_id}, skipping")
                continue

            self.conn.execute(
                """INSERT INTO news_topics (news_id, topic_id, confidence, reason)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(news_id, topic_id) DO UPDATE SET
                       confidence = excluded.confidence,
                       reason = excluded.reason""",
                (
                    news_id,
                    topic["id"],
                    td.get("confidence", 0.0),
                    td.get("reason", ""),
                ),
            )
            count += 1

        self.conn.commit()
        return count

    def get_news_topics(self, news_id: str) -> list[dict[str, Any]]:
        """Get all topics associated with a single news item."""
        rows = self.conn.execute(
            """SELECT t.*, nt.confidence, nt.reason AS classification_reason
               FROM news_topics nt
               JOIN topics t ON nt.topic_id = t.id
               WHERE nt.news_id = ?
               ORDER BY t.group_name, t.sort_order""",
            (news_id,),
        ).fetchall()

        return [
            {
                "id": r["id"],
                "name": r["name"],
                "slug": r["slug"],
                "group_name": r["group_name"],
                "description": r["description"],
                "confidence": r["confidence"],
                "reason": r["classification_reason"],
            }
            for r in rows
        ]

    def _batch_get_news_topics(
        self, news_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-fetch topics for multiple news items.

        Returns a dict mapping news_id -> list of topic dicts.
        """
        if not news_ids:
            return {}

        placeholders = ",".join("?" for _ in news_ids)
        rows = self.conn.execute(
            f"""SELECT nt.news_id, t.id, t.name, t.slug, t.group_name,
                       t.description, nt.confidence, nt.reason AS classification_reason
                FROM news_topics nt
                JOIN topics t ON nt.topic_id = t.id
                WHERE nt.news_id IN ({placeholders})
                ORDER BY t.group_name, t.sort_order""",
            news_ids,
        ).fetchall()

        result: dict[str, list[dict[str, Any]]] = {nid: [] for nid in news_ids}
        for r in rows:
            result.setdefault(r["news_id"], []).append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "slug": r["slug"],
                    "group_name": r["group_name"],
                    "description": r["description"],
                    "confidence": r["confidence"],
                    "reason": r["classification_reason"],
                }
            )
        return result

    def get_topic_news(
        self,
        slug: str,
        *,
        page: int = 1,
        per_page: int = 20,
        sort: str = "ai_score",
        order: str = "desc",
    ) -> dict[str, Any]:
        """Get paginated news items for a specific topic by slug."""
        topic = self.conn.execute(
            "SELECT id, name, slug, group_name, description FROM topics WHERE slug = ?",
            (slug,),
        ).fetchone()

        if topic is None:
            return {"topic": None, "items": [], "total": 0, "page": 1, "per_page": per_page, "pages": 0}

        allowed_sort = {"ai_score", "published_at", "created_at", "run_date"}
        sort_col = sort if sort in allowed_sort else "ai_score"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        offset = (page - 1) * per_page

        count_row = self.conn.execute(
            """SELECT COUNT(*) AS cnt FROM news_topics nt
               JOIN items i ON nt.news_id = i.id
               WHERE nt.topic_id = ?""",
            (topic["id"],),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = self.conn.execute(
            f"""SELECT i.* FROM news_topics nt
                JOIN items i ON nt.news_id = i.id
                WHERE nt.topic_id = ?
                ORDER BY i.{sort_col} {order_dir}
                LIMIT ? OFFSET ?""",
            (topic["id"], per_page, offset),
        ).fetchall()

        items = [_row_to_item(r) for r in rows]
        # Batch-fill topics
        topics_map = self._batch_get_news_topics([item["id"] for item in items])
        for item in items:
            item["topics"] = topics_map.get(item["id"], [])

        return {
            "topic": {
                "id": topic["id"],
                "name": topic["name"],
                "slug": topic["slug"],
                "group_name": topic["group_name"],
                "description": topic["description"],
            },
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }
