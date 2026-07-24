"""SQLite database for persisting scored/enriched items and daily runs."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

from ..models import ContentItem
from ..papers.models import Paper
from ..reports.models import Report


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    content         TEXT,
    raw_content     TEXT,
    raw_html        TEXT,
    display_html    TEXT,
    display_html_zh TEXT,
    cover_image     TEXT,
    images_json     TEXT NOT NULL DEFAULT '[]',
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
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    selected        INTEGER NOT NULL DEFAULT 0,
    drop_reason     TEXT,
    category        TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_selected ON items(selected);
CREATE INDEX IF NOT EXISTS idx_items_drop_reason ON items(drop_reason);
CREATE INDEX IF NOT EXISTS idx_items_run_date_selected ON items(run_date, selected);

CREATE INDEX IF NOT EXISTS idx_items_run_date ON items(run_date);
CREATE INDEX IF NOT EXISTS idx_items_ai_score ON items(ai_score);
CREATE INDEX IF NOT EXISTS idx_items_source_type ON items(source_type);
CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, ai_summary, ai_reason, ai_tags_json,
    content='items', content_rowid='rowid', tokenize='trigram'
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

CREATE TABLE IF NOT EXISTS user_item_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    state           TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    UNIQUE(user_id, item_id, state)
);

CREATE INDEX IF NOT EXISTS idx_user_item_state_user ON user_item_state(user_id);
CREATE INDEX IF NOT EXISTS idx_user_item_state_item ON user_item_state(item_id);

CREATE TABLE IF NOT EXISTS user_paper_favorites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    paper_id        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_user_paper_fav_user ON user_paper_favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_user_paper_fav_paper ON user_paper_favorites(paper_id);

CREATE TABLE IF NOT EXISTS user_report_favorites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    report_id       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, report_id)
);

CREATE INDEX IF NOT EXISTS idx_user_report_fav_user ON user_report_favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_user_report_fav_report ON user_report_favorites(report_id);

CREATE TABLE IF NOT EXISTS user_topic_prefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    topic_id        INTEGER NOT NULL,
    state           TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    UNIQUE(user_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_user_topic_prefs_user ON user_topic_prefs(user_id);
CREATE INDEX IF NOT EXISTS idx_user_topic_prefs_topic ON user_topic_prefs(topic_id);

CREATE TABLE IF NOT EXISTS papers (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    native_id           TEXT NOT NULL,
    title               TEXT NOT NULL,
    authors_json        TEXT NOT NULL DEFAULT '[]',
    abstract            TEXT NOT NULL DEFAULT '',
    url                 TEXT NOT NULL,
    pdf_url             TEXT,
    published_at        TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    publication_year    INTEGER,
    categories_json     TEXT NOT NULL DEFAULT '[]',
    category            TEXT,
    comment             TEXT,
    journal_ref         TEXT,
    doi                 TEXT,
    open_access         INTEGER,
    citation_count      INTEGER,
    citation_percentile REAL,
    upvote_count        INTEGER,
    raw_metadata_json   TEXT,
    fetched_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_row_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
CREATE INDEX IF NOT EXISTS idx_papers_published_at ON papers(published_at);

CREATE TABLE IF NOT EXISTS paper_topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        TEXT NOT NULL,
    topic_id        INTEGER NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
    UNIQUE(paper_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_topics_paper_id ON paper_topics(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_topics_topic_id ON paper_topics(topic_id);

CREATE TABLE IF NOT EXISTS reports (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    native_id           TEXT NOT NULL,
    title               TEXT NOT NULL,
    institution         TEXT NOT NULL DEFAULT '',
    author              TEXT,
    url                 TEXT NOT NULL,
    pdf_urls_json       TEXT NOT NULL DEFAULT '[]',
    summary             TEXT,
    content_text        TEXT NOT NULL,
    categories_json     TEXT NOT NULL DEFAULT '[]',
    published_at        TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    view_count          INTEGER,
    download_count      INTEGER,
    fetched_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_row_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reports_source ON reports(source);
CREATE INDEX IF NOT EXISTS idx_reports_published_at ON reports(published_at);
"""


# Columns added after the initial schema — applied via ALTER TABLE for
# existing DB files, since CREATE TABLE IF NOT EXISTS won't add them.
_ITEMS_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("cover_image", "TEXT"),
    ("images_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("raw_html", "TEXT"),
    ("display_html", "TEXT"),
    ("display_html_zh", "TEXT"),
    ("raw_content", "TEXT"),
    ("category", "TEXT"),
]


# Columns added to the papers table after its initial schema — same pattern
# as _ITEMS_COLUMN_MIGRATIONS. Applied via ALTER TABLE for existing DB files.
_PAPERS_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("publication_year", "INTEGER"),
    ("category", "TEXT"),
    ("arxiv_id", "TEXT"),
    ("semantic_scholar_id", "TEXT"),
    ("canonical_doi", "TEXT"),
    ("reprint_doi", "TEXT"),
    ("source_version_type", "TEXT"),
    ("openalex_id_override", "TEXT"),
    ("open_access", "INTEGER"),
    ("title_zh", "TEXT"),
    ("abstract_zh", "TEXT"),
    ("original_language", "TEXT"),
]


def _migrate_papers_table(conn: sqlite3.Connection) -> None:
    """Add any columns that were added to papers after the initial schema,
    then create indexes that depend on those columns (which can't live in
    _SCHEMA because on a pre-existing DB the column doesn't exist yet when
    executescript() runs)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(papers)")}
    for column, ddl in _PAPERS_COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {ddl}")
    # Safe to run here — the column now always exists.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(category)")
    conn.commit()


def _migrate_items_table(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    for column, ddl in _ITEMS_COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {column} {ddl}")
            if column == "category":
                # One-time backfill from the legacy metadata_json location —
                # only runs the moment this column is first added.
                conn.execute(
                    "UPDATE items SET category = json_extract(metadata_json, '$.category') "
                    "WHERE category IS NULL"
                )
    # Not part of _SCHEMA: on a pre-existing DB, executescript() runs before
    # this migration, so an index referencing a not-yet-added column would
    # fail. Safe to run unconditionally here since the column now always exists.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)")
    conn.commit()


def _migrate_fts_tokenizer(conn: sqlite3.Connection) -> None:
    """Rebuild items_fts with the trigram tokenizer if it's still on the
    default (unicode61). unicode61 doesn't segment CJK text into words —
    a run of Chinese characters between punctuation becomes a single token,
    so a query only matched documents where it happened to land on an exact
    token boundary. trigram indexes character n-grams instead, which makes
    substring search work correctly for Chinese (and any other script).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='items_fts'"
    ).fetchone()
    if row is None or (row["sql"] and "trigram" in row["sql"]):
        return
    conn.execute("DROP TABLE items_fts")
    conn.execute(
        "CREATE VIRTUAL TABLE items_fts USING fts5("
        "title, ai_summary, ai_reason, ai_tags_json, "
        "content='items', content_rowid='rowid', tokenize='trigram')"
    )
    conn.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
    conn.commit()


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so search input is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _to_sqlite_param(value: Any) -> Any:
    """Coerce a value to a type sqlite3 can bind (str/int/float/bytes/None).

    ``date``/``datetime`` values (which sqlite3 cannot bind directly and
    raises ``InterfaceError: bad parameter or other API misuse`` for) are
    converted to their ISO string form. Anything else that isn't already a
    primitive sqlite3 type is stringified as a last resort.
    """
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a DB row to a JSON-serializable dict matching the ContentItem shape."""
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


def _row_to_paper(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a papers-table row to a JSON-serializable dict matching the Paper shape."""
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
        "raw_metadata": json.loads(row["raw_metadata_json"]) if row["raw_metadata_json"] else None,
        "canonical_doi": row["canonical_doi"],
        "reprint_doi": row["reprint_doi"],
        "source_version_type": row["source_version_type"],
        "openalex_id_override": row["openalex_id_override"],
        "arxiv_id": row["arxiv_id"],
        "semantic_scholar_id": row["semantic_scholar_id"],
        "title_zh": row["title_zh"],
        "abstract_zh": row["abstract_zh"],
        "original_language": row["original_language"],
        "fetched_at": row["fetched_at"],
    }


def _split_institutions(raw: str) -> list[str]:
    """Split a combined institution string into individual institutions.

    AliResearch returns institutions joined by ``&`` or ``、``, e.g.
    ``"阿里云研究院 & 阿里云公共云技术服务部"`` or
    ``"阿里云研究院、中央广播电视总台视听新媒体中心"``.

    Returns a list of stripped, non-empty institution names.
    """
    if not raw:
        return []
    parts = re.split(r"\s*[&,、;；]\s*", raw)
    return [p.strip() for p in parts if p.strip()]


def _first_institution(raw: str) -> str:
    """Return only the first institution from a possibly multi-valued string.

    Source fetchers sometimes persist institution strings joined by ``、``
    or ``&`` (e.g. ``"阿里云研究院、中央广播电视总台研究院"``).  Callers
    that want the raw list still use ``_split_institutions()``; this
    normalizes the stored value to the primary institution only.
    """
    parts = _split_institutions(raw)
    return parts[0] if parts else raw


def _row_to_report(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a reports-table row to a JSON-serializable dict matching the Report shape."""
    pdf_urls: list[dict] = json.loads(row["pdf_urls_json"])
    # Transform legacy filesystem ``local_path`` values (e.g.
    # ``data/reports_pdfs/…``) into serveable URL paths under the
    # ``/api/reports/pdfs/`` StaticFiles mount.  New downloads from
    # ``pdf_downloader.py`` already store URL-path format, so this
    # is purely a one-way backward-compatibility shim.
    for entry in pdf_urls:
        lp = entry.get("local_path")
        if lp and lp.startswith("data/reports_pdfs/"):
            entry["local_path"] = "/api/reports/pdfs/" + lp.removeprefix("data/reports_pdfs/")
        elif lp and lp.startswith("data/"):
            entry["local_path"] = "/api/reports/pdfs/" + lp.removeprefix("data/")
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


class HorizonDB:
    """SQLite persistence for Horizon pipeline outputs."""

    def __init__(self, db_path: str = "data/horizon.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI's sync endpoints run in a threadpool, so concurrent requests
        # can call into HorizonDB from different threads at the same time.
        # A single shared sqlite3.Connection is not safe for concurrent use
        # from multiple threads (even with check_same_thread=False) — it
        # intermittently raises "sqlite3.InterfaceError: bad parameter or
        # other API misuse" under concurrent execute() calls. Give each
        # thread its own connection instead.
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            _migrate_items_table(conn)
            _migrate_papers_table(conn)
            _migrate_fts_tokenizer(conn)
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- write ----------------------------------------------------------------

    def save_items(
        self,
        items: List[ContentItem],
        run_date: str,
        total_fetched: int,
        *,
        selected: bool = True,
        replace: bool = True,
    ) -> int:
        """Persist scored/enriched items for a given date.

        By default (``replace=True``) existing items for *run_date* are
        deleted first — the original behaviour that keeps the table as a
        point-in-time snapshot.  Set ``replace=False`` to UPSERT without
        deleting siblings; used by the orchestrator to refresh enrichment
        data for final items while preserving dropped-item audit trails.

        Args:
            items: Items to persist.
            run_date: Date key for this run (YYYY-MM-DD).
            total_fetched: Total items fetched (for daily_runs tracking).
            selected: Whether these items passed all filters (default True,
                keeps backward compat with callers that only write final items).
            replace: When True (default), DELETE all items for *run_date*
                before inserting.  Set to False for incremental updates.
        """
        if replace:
            self.conn.execute("DELETE FROM items WHERE run_date = ?", (run_date,))

        rows: list[tuple] = []
        for item in items:
            # Real drop reasons are written later by mark_selected(); nothing
            # ever sets "_drop_reason" on item.metadata, so this is always None.
            drop_reason = None
            category = item.metadata.get("category")
            # Extraction-provenance fields have no dedicated columns — fold
            # them into metadata_json alongside the item's own metadata dict
            # (same precedent as source_provenance/original_language).
            metadata_out = dict(item.metadata)
            metadata_out.update({
                "rss_summary": item.rss_summary,
                "content_source": item.content_source,
                "extraction_status": item.extraction_status,
                "extraction_error": item.extraction_error,
                "http_status": item.http_status,
                "final_url": item.final_url,
                "text_length": item.text_length,
                "extracted_at": _dt_iso(item.extracted_at),
                "extractor_version": item.extractor_version,
            })
            rows.append((
                item.id,
                item.source_type.value,
                item.title,
                str(item.url),
                item.content,
                item.raw_content,
                item.raw_html,
                item.display_html,
                item.display_html_zh,
                item.cover_image,
                json.dumps(item.images, ensure_ascii=False, default=str),
                item.author,
                _dt_iso(item.published_at),
                _dt_iso(item.fetched_at),
                1 if item.ai_relevant else 0,
                item.ai_score,
                item.ai_reason,
                item.ai_summary,
                json.dumps(item.ai_tags, ensure_ascii=False),
                json.dumps(metadata_out, ensure_ascii=False, default=str),
                run_date,
                _now_iso(),
                1 if selected else 0,
                drop_reason,
                category,
            ))

        # Extraction-stage columns are set once (step 2.5, before analysis)
        # and must survive the later incremental enrichment write (step 6.5,
        # replace=False) even if the item object passed in that time didn't
        # carry them — COALESCE keeps whatever's already stored instead of
        # nulling it out. The replace=True snapshot write (preceded by a
        # DELETE) keeps today's exact blind-overwrite behavior.
        extraction_cols = (
            "content", "raw_content", "raw_html", "display_html",
            "display_html_zh", "cover_image", "images_json",
        )
        def _update_expr(col: str) -> str:
            if not replace and col in extraction_cols:
                # Unqualified `col` refers to the pre-update (existing) row;
                # `excluded.col` is the value from this INSERT attempt.
                return f"{col} = COALESCE(excluded.{col}, {col})"
            return f"{col} = excluded.{col}"

        update_clause = ",\n                ".join(
            _update_expr(col) for col in (
                "source_type", "title", "url", "content", "raw_content",
                "raw_html", "display_html", "display_html_zh", "cover_image",
                "images_json", "author", "published_at", "fetched_at",
                "ai_relevant", "ai_score", "ai_reason", "ai_summary",
                "ai_tags_json", "metadata_json", "run_date", "created_at",
                "selected", "drop_reason", "category",
            )
        )

        self.conn.executemany(
            f"""INSERT INTO items (
                id, source_type, title, url, content, raw_content, raw_html,
                display_html, display_html_zh, cover_image, images_json, author,
                published_at, fetched_at, ai_relevant, ai_score,
                ai_reason, ai_summary, ai_tags_json, metadata_json,
                run_date, created_at, selected, drop_reason, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                {update_clause}""",
            rows,
        )

        # Upsert daily run record
        languages = list({item.metadata.get("original_language", "unknown") for item in items}) if items else []
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

    def mark_selected(
        self,
        selected_ids: set[str],
        drop_reason_map: dict[str, str],
        run_date: str,
    ) -> int:
        """Mark which items survived all filtering stages and tag dropped items.

        After ``save_items(items, selected=False)`` writes the full scored set,
        call this to mark the survivors and annotate why each other item was
        dropped.

        Args:
            selected_ids: Item IDs that passed all filters.
            drop_reason_map: Mapping from item ID to drop reason
                (``"relevance"``, ``"score"``, ``"topic_duplicate"``,
                ``"category_quota"``).
            run_date: Date key for this run.

        Returns:
            Number of items updated.
        """
        # Reset all items for this run_date to not-selected
        self.conn.execute(
            "UPDATE items SET selected = 0, drop_reason = NULL WHERE run_date = ?",
            (run_date,),
        )

        # Mark selected items
        if selected_ids:
            placeholders = ",".join("?" for _ in selected_ids)
            self.conn.execute(
                f"UPDATE items SET selected = 1, drop_reason = NULL "
                f"WHERE run_date = ? AND id IN ({placeholders})",
                (run_date, *selected_ids),
            )

        # Tag dropped items with their reason
        updated = 0
        for item_id, reason in drop_reason_map.items():
            cur = self.conn.execute(
                "UPDATE items SET drop_reason = ? WHERE run_date = ? AND id = ?",
                (reason, run_date, item_id),
            )
            updated += cur.rowcount

        self.conn.execute(
            """INSERT INTO daily_runs (date, total_fetched, total_selected, languages)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               total_selected = excluded.total_selected""",
            (run_date, 0, len(selected_ids), "[]"),
        )

        self.conn.commit()
        return updated

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
        selected_only: bool = True,
        blocked_topic_ids: Optional[Iterable[int]] = None,
    ) -> dict[str, Any]:
        """Paginated item query with optional filters.

        Args:
            selected_only: When True (default), only return items that passed
                all filtering stages. Set to False to include dropped items
                for auditing.
            blocked_topic_ids: When given, excludes items associated with any
                of these topic ids. Callers resolve this from a user's
                ``user_topic_prefs`` (see ``get_blocked_topic_ids``) — this
                method itself has no notion of "user".
        """
        where = []
        params: list[Any] = []

        if run_date:
            where.append("run_date = ?")
            params.append(run_date)

        if blocked_topic_ids:
            blocked_topic_ids = list(blocked_topic_ids)
            placeholders = ",".join("?" for _ in blocked_topic_ids)
            where.append(
                f"id NOT IN (SELECT news_id FROM news_topics WHERE topic_id IN ({placeholders}))"
            )
            params.extend(blocked_topic_ids)

        if selected_only:
            where.append("selected = 1")

        if category:
            where.append("category = ?")
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

        # Ensure every bound value is a type sqlite3 can bind (str/int/float/
        # bytes/None) — e.g. a stray date/datetime never reaches execute().
        params = [_to_sqlite_param(p) for p in params]

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

        page_params = params + [per_page, offset]
        rows = self.conn.execute(
            f"SELECT * {base_from} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?",
            page_params,
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

    # -- papers -----------------------------------------------------------

    def save_papers(self, papers: List[Paper]) -> int:
        """UPSERT papers keyed on the source-namespaced id.

        Unlike ``save_items()``, this is not a ``run_date``-scoped snapshot —
        the papers table accumulates across fetches (each source's fetch is
        idempotent and safe to re-run on any cadence), so writes are a plain
        upsert keyed on id rather than a delete+insert.
        """
        for p in papers:
            self.conn.execute(
                """
                INSERT INTO papers (
                    id, source, native_id, title, authors_json, abstract, url, pdf_url,
                    published_at, updated_at, publication_year, categories_json, category,
                    comment, journal_ref, doi, canonical_doi, reprint_doi,
                    source_version_type, openalex_id_override,
                    arxiv_id, semantic_scholar_id,
                    open_access, citation_count, citation_percentile,
                    upvote_count, raw_metadata_json,
                    title_zh, abstract_zh, original_language,
                    fetched_at, updated_row_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    authors_json=excluded.authors_json,
                    abstract=excluded.abstract,
                    url=excluded.url,
                    pdf_url=excluded.pdf_url,
                    updated_at=excluded.updated_at,
                    publication_year=excluded.publication_year,
                    categories_json=excluded.categories_json,
                    category=excluded.category,
                    comment=excluded.comment,
                    journal_ref=excluded.journal_ref,
                    doi=excluded.doi,
                    canonical_doi=excluded.canonical_doi,
                    reprint_doi=excluded.reprint_doi,
                    source_version_type=excluded.source_version_type,
                    openalex_id_override=excluded.openalex_id_override,
                    arxiv_id=excluded.arxiv_id,
                    semantic_scholar_id=excluded.semantic_scholar_id,
                    open_access=excluded.open_access,
                    citation_count=excluded.citation_count,
                    citation_percentile=excluded.citation_percentile,
                    upvote_count=excluded.upvote_count,
                    raw_metadata_json=excluded.raw_metadata_json,
                    title_zh=excluded.title_zh,
                    abstract_zh=excluded.abstract_zh,
                    original_language=excluded.original_language,
                    fetched_at=excluded.fetched_at,
                    updated_row_at=datetime('now')
                """,
                (
                    p.id,
                    p.source,
                    p.native_id,
                    p.title,
                    json.dumps(p.authors, ensure_ascii=False),
                    p.abstract,
                    p.url,
                    p.pdf_url,
                    _dt_iso(p.published_at),
                    _dt_iso(p.updated_at),
                    p.publication_year,
                    json.dumps(p.categories, ensure_ascii=False),
                    p.category,
                    p.comment,
                    p.journal_ref,
                    p.doi,
                    p.canonical_doi,
                    p.reprint_doi,
                    p.source_version_type,
                    p.openalex_id_override,
                    p.arxiv_id,
                    p.semantic_scholar_id,
                    p.open_access,
                    p.citation_count,
                    p.citation_percentile,
                    p.upvote_count,
                    json.dumps(p.raw_metadata, ensure_ascii=False) if p.raw_metadata is not None else None,
                    p.title_zh,
                    p.abstract_zh,
                    p.original_language,
                    _dt_iso(p.fetched_at),
                ),
            )
        self.conn.commit()
        return len(papers)

    def get_papers(
        self,
        *,
        source: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        topic_slug: Optional[str] = None,
        publication_month: Optional[str] = None,
        sort: str = "published_at",
        order: str = "desc",
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Paginated papers query with optional filters.

        When *topic_slug* is given, only papers associated with that topic are
        returned (via JOIN on paper_topics + topics).
        """
        where = []
        params: list[Any] = []

        # ── topic_slug filter (JOIN path) ──
        topic_join = ""
        if topic_slug:
            topic_join = (
                "JOIN paper_topics pt_filter ON p.id = pt_filter.paper_id "
                "JOIN topics t_filter ON pt_filter.topic_id = t_filter.id AND t_filter.slug = ?"
            )
            params.append(topic_slug)

        if source:
            where.append("p.source = ?")
            params.append(source)

        if category:
            cats = [c.strip() for c in category.split(",") if c.strip()]
            if len(cats) == 1:
                where.append("p.category = ?")
                params.append(cats[0])
            else:
                placeholders = ", ".join("?" for _ in cats)
                where.append(f"p.category IN ({placeholders})")
                params.extend(cats)

        if publication_month is not None:
            where.append("strftime('%Y-%m', p.published_at) = ?")
            params.append(publication_month)

        if search:
            escaped = _escape_like(search)
            where.append("(p.title LIKE ? ESCAPE '\\' OR p.abstract LIKE ? ESCAPE '\\')")
            like_pattern = f"%{escaped}%"
            params.extend([like_pattern, like_pattern])

        where_clause = " AND ".join(where) if where else "1=1"
        base_from = f"FROM papers p {topic_join} WHERE {where_clause}"

        count_row = self.conn.execute(
            f"SELECT COUNT(*) as cnt {base_from}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        allowed_sort = {"published_at", "updated_at", "fetched_at", "citation_count", "upvote_count"}
        sort_col = sort if sort in allowed_sort else "published_at"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        offset = (page - 1) * per_page

        page_params = params + [per_page, offset]
        rows = self.conn.execute(
            f"SELECT p.* {base_from} ORDER BY p.{sort_col} {order_dir} LIMIT ? OFFSET ?",
            page_params,
        ).fetchall()

        papers = [_row_to_paper(r) for r in rows]

        # Batch-attach topic associations
        paper_ids = [p["id"] for p in papers]
        topics_map = self._batch_get_paper_topics(paper_ids)
        for paper in papers:
            paper["topics"] = topics_map.get(paper["id"], [])

        return {
            "items": papers,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def get_paper_month_counts(self) -> list[dict[str, Any]]:
        """Return month-by-month paper counts across all sources, newest first."""
        rows = self.conn.execute(
            "SELECT strftime('%Y-%m', published_at) AS ym, COUNT(*) AS cnt FROM papers GROUP BY ym ORDER BY ym DESC"
        ).fetchall()
        return [{"ym": r["ym"], "cnt": r["cnt"]} for r in rows]

    def get_paper(self, paper_id: str) -> Optional[dict[str, Any]]:
        """Get a single paper by its source-namespaced id, with topics attached."""
        row = self.conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            return None
        paper = _row_to_paper(row)
        paper["topics"] = self.get_paper_topics(paper_id)
        return paper

    # -- reports ------------------------------------------------------------

    def save_reports(self, reports: List[Report]) -> int:
        """UPSERT reports keyed on the source-namespaced id.

        Like `save_papers()`, this accumulates across fetches rather than
        being a `run_date`-scoped snapshot — a report can be re-fetched (e.g.
        its view/download counts change) and should just update in place.
        """
        for r in reports:
            # Normalize multi-institution strings to only the first institution.
            institution = _first_institution(r.institution)

            self.conn.execute(
                """
                INSERT INTO reports (
                    id, source, native_id, title, institution, author, url,
                    pdf_urls_json, summary, content_text, categories_json,
                    published_at, updated_at, view_count, download_count,
                    fetched_at, updated_row_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    institution=excluded.institution,
                    author=excluded.author,
                    url=excluded.url,
                    pdf_urls_json=excluded.pdf_urls_json,
                    summary=excluded.summary,
                    content_text=excluded.content_text,
                    categories_json=excluded.categories_json,
                    updated_at=excluded.updated_at,
                    view_count=excluded.view_count,
                    download_count=excluded.download_count,
                    fetched_at=excluded.fetched_at,
                    updated_row_at=datetime('now')
                """,
                (
                    r.id,
                    r.source,
                    r.native_id,
                    r.title,
                    institution,
                    r.author,
                    r.url,
                    json.dumps(r.pdf_urls, ensure_ascii=False),
                    r.summary,
                    r.content_text,
                    json.dumps(r.categories, ensure_ascii=False),
                    _dt_iso(r.published_at),
                    _dt_iso(r.updated_at),
                    r.view_count,
                    r.download_count,
                    _dt_iso(r.fetched_at),
                ),
            )
        self.conn.commit()
        return len(reports)

    def get_reports(
        self,
        *,
        source: Optional[str] = None,
        institution: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        sort: str = "published_at",
        order: str = "desc",
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Paginated reports query with optional filters."""
        where = []
        params: list[Any] = []

        if source:
            where.append("source = ?")
            params.append(source)

        if institution:
            where.append("institution LIKE '%' || ? || '%'")
            params.append(institution)

        if category:
            where.append(
                "EXISTS (SELECT 1 FROM json_each(categories_json) WHERE value = ?)"
            )
            params.append(category)

        if search:
            escaped = _escape_like(search)
            where.append("(title LIKE ? ESCAPE '\\' OR content_text LIKE ? ESCAPE '\\')")
            like_pattern = f"%{escaped}%"
            params.extend([like_pattern, like_pattern])

        where_clause = " AND ".join(where) if where else "1=1"
        base_from = f"FROM reports WHERE {where_clause}"

        count_row = self.conn.execute(
            f"SELECT COUNT(*) as cnt {base_from}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        allowed_sort = {"published_at", "updated_at", "fetched_at"}
        sort_col = sort if sort in allowed_sort else "published_at"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        offset = (page - 1) * per_page

        page_params = params + [per_page, offset]
        rows = self.conn.execute(
            f"SELECT * {base_from} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?",
            page_params,
        ).fetchall()

        return {
            "items": [_row_to_report(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def get_report(self, report_id: str) -> Optional[dict[str, Any]]:
        """Get a single report by its source-namespaced id."""
        row = self.conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return _row_to_report(row) if row is not None else None

    def get_report_institutions(self, source: Optional[str] = None) -> List[dict[str, Any]]:
        """Return distinct individual institutions (split on ``&``, ``、``) with report counts."""
        where = "1=1"
        params: list[Any] = []
        if source:
            where = "source = ?"
            params.append(source)
        rows = self.conn.execute(
            f"SELECT institution, source FROM reports WHERE {where}",
            params,
        ).fetchall()
        counts: dict[tuple[str, str], int] = {}
        for r in rows:
            insts = _split_institutions(r["institution"])
            for inst in insts:
                key = (inst, r["source"])
                counts[key] = counts.get(key, 0) + 1
        return [
            {"institution": inst, "source": src, "count": cnt}
            for (inst, src), cnt in sorted(counts.items(), key=lambda x: -x[1])
        ]

    def get_tags(self, run_date: Optional[str] = None, min_count: int = 1, *, selected_only: bool = True) -> list[dict[str, Any]]:
        """Get all tags with occurrence counts.

        Args:
            selected_only: When True (default), only count tags from selected items.
        """
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)
        if selected_only:
            where += " AND selected = 1"

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

    def get_category_counts(self, run_date: Optional[str] = None, *, selected_only: bool = True) -> list[dict[str, Any]]:
        """Get item counts by category.

        Args:
            selected_only: When True (default), only count selected items.
        """
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)
        if selected_only:
            where += " AND selected = 1"

        rows = self.conn.execute(
            f"""SELECT category, COUNT(*) AS count
                FROM items
                WHERE {where}
                GROUP BY category
                ORDER BY count DESC""",
            params,
        ).fetchall()
        return [{"category": r["category"] or "unknown", "count": r["count"]} for r in rows]

    def get_stats(self, run_date: Optional[str] = None, *, selected_only: bool = True) -> dict[str, Any]:
        """Get aggregate statistics.

        Args:
            selected_only: When True (default), only aggregate selected items.
                Set to False to include dropped items in stats.
        """
        where = "1=1"
        params: list[Any] = []
        if run_date:
            where = "run_date = ?"
            params.append(run_date)
        if selected_only:
            where += " AND selected = 1"

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

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        page: Optional[int] = None,
        sort: str = "relevance",
        order: str = "desc",
        selected_only: bool = True,
        blocked_topic_ids: Optional[Iterable[int]] = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Substring search across title, summary, reason, and tags.

        Uses LIKE against the trigram-tokenized FTS columns (index-accelerated)
        rather than MATCH, since MATCH requires the pattern to be at least
        ngram-length (3) and trigram isn't designed to be queried with MATCH.

        Args:
            selected_only: When True (default), only search across selected items.
            blocked_topic_ids: See get_items().
            page: When provided, return paginated results as a dict with
                ``items``, ``total``, ``page``, and ``per_page`` keys.
                When None (default), return a flat list of items.
            sort: Sort column — "relevance" (ai_score), "published_at".
            order: Sort direction — "asc" or "desc".
        """
        like = f"%{_escape_like(query)}%"
        where = [
            "(items_fts.title LIKE ? ESCAPE '\\' "
            "OR items_fts.ai_summary LIKE ? ESCAPE '\\' "
            "OR items_fts.ai_reason LIKE ? ESCAPE '\\' "
            "OR items_fts.ai_tags_json LIKE ? ESCAPE '\\')"
        ]
        params: list[Any] = [like, like, like, like]

        if selected_only:
            where.append("items.selected = 1")

        if blocked_topic_ids:
            blocked_topic_ids = list(blocked_topic_ids)
            placeholders = ",".join("?" for _ in blocked_topic_ids)
            where.append(
                f"items.id NOT IN (SELECT news_id FROM news_topics WHERE topic_id IN ({placeholders}))"
            )
            params.extend(blocked_topic_ids)

        base_from = (
            f"FROM items JOIN items_fts ON items.rowid = items_fts.rowid "
            f"WHERE {' AND '.join(where)}"
        )

        sort_col = "items.ai_score" if sort == "relevance" else "items.published_at"
        sort_dir = "DESC" if order == "desc" else "ASC"
        order_clause = f"ORDER BY {sort_col} {sort_dir}"

        if page is not None:
            # Count total matching rows
            count_row = self.conn.execute(
                f"SELECT COUNT(*) as cnt {base_from}", params
            ).fetchone()
            total = count_row["cnt"] if count_row else 0

            offset = (page - 1) * limit
            page_params = params + [limit, offset]
            rows = self.conn.execute(
                f"SELECT items.* {base_from} {order_clause} LIMIT ? OFFSET ?",
                page_params,
            ).fetchall()
            items = [_row_to_item(r) for r in rows]
            topics_map = self._batch_get_news_topics([item["id"] for item in items])
            for item in items:
                item["topics"] = topics_map.get(item["id"], [])
            return {
                "items": items,
                "total": total,
                "page": page,
                "per_page": limit,
            }
        else:
            params.append(limit)
            rows = self.conn.execute(
                f"SELECT items.* {base_from} {order_clause} LIMIT ?",
                params,
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

        Each topic includes a `count` of associated news items — only items
        that made the final digest (``selected = 1``) are counted, so this
        matches what ``get_topic_news`` actually returns for the same topic.
        """
        rows = self.conn.execute(
            """SELECT t.*, COUNT(i.id) AS count
               FROM topics t
               LEFT JOIN news_topics nt ON t.id = nt.topic_id
               LEFT JOIN items i ON nt.news_id = i.id AND i.selected = 1
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

    # -- paper topics ----------------------------------------------------

    def seed_paper_topics(self, topics_data: list[dict[str, Any]]) -> int:
        """Idempotent upsert of paper topic seed rows into ``topics``.

        Delegates to ``seed_topics()`` — paper topics live in the same table
        as news topics, distinguished by ``group_name``.
        """
        return self.seed_topics(topics_data)

    def save_paper_topics(
        self, paper_id: str, topics_data: list[dict[str, Any]]
    ) -> int:
        """Save topic associations for a paper.

        *topics_data* is a list of dicts with keys: slug, confidence, reason.
        Upserts by (paper_id, topic_id).
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
                print(f"Warning: unknown topic slug '{slug}' for paper {paper_id}, skipping")
                continue

            self.conn.execute(
                """INSERT INTO paper_topics (paper_id, topic_id, confidence, reason)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(paper_id, topic_id) DO UPDATE SET
                       confidence = excluded.confidence,
                       reason = excluded.reason""",
                (
                    paper_id,
                    topic["id"],
                    td.get("confidence", 1.0),
                    td.get("reason", ""),
                ),
            )
            count += 1

        self.conn.commit()
        return count

    def get_paper_topics(self, paper_id: str) -> list[dict[str, Any]]:
        """Get all topics associated with a single paper."""
        rows = self.conn.execute(
            """SELECT t.*, pt.confidence, pt.reason AS classification_reason
               FROM paper_topics pt
               JOIN topics t ON pt.topic_id = t.id
               WHERE pt.paper_id = ?
               ORDER BY t.group_name, t.sort_order""",
            (paper_id,),
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

    def _batch_get_paper_topics(
        self, paper_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-fetch topics for multiple papers.

        Returns a dict mapping paper_id -> list of topic dicts.
        """
        if not paper_ids:
            return {}

        placeholders = ",".join("?" for _ in paper_ids)
        rows = self.conn.execute(
            f"""SELECT pt.paper_id, t.id, t.name, t.slug, t.group_name,
                       t.description, pt.confidence, pt.reason AS classification_reason
                FROM paper_topics pt
                JOIN topics t ON pt.topic_id = t.id
                WHERE pt.paper_id IN ({placeholders})
                ORDER BY t.group_name, t.sort_order""",
            paper_ids,
        ).fetchall()

        result: dict[str, list[dict[str, Any]]] = {pid: [] for pid in paper_ids}
        for r in rows:
            result.setdefault(r["paper_id"], []).append(
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

    def get_topic_papers(
        self,
        slug: str,
        *,
        page: int = 1,
        per_page: int = 20,
        sort: str = "published_at",
        order: str = "desc",
        search: Optional[str] = None,
        source: Optional[str] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """Get paginated papers for a specific topic by slug."""
        topic = self.conn.execute(
            "SELECT id, name, slug, group_name, description FROM topics WHERE slug = ?",
            (slug,),
        ).fetchone()

        if topic is None:
            return {
                "topic": None, "papers": [],
                "total": 0, "page": 1, "per_page": per_page, "pages": 0,
            }

        topic_block = {
            "id": topic["id"],
            "name": topic["name"],
            "slug": topic["slug"],
            "group_name": topic["group_name"],
            "description": topic["description"],
        }

        allowed_sort = {"published_at", "updated_at", "fetched_at", "citation_count", "upvote_count"}
        sort_col = sort if sort in allowed_sort else "published_at"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"

        where = "WHERE pt.topic_id = ?"
        params: list[Any] = [topic["id"]]

        if search:
            where += " AND (p.title LIKE ? OR p.abstract LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term])

        if source:
            where += " AND p.source = ?"
            params.append(source)

        if year is not None:
            where += " AND p.publication_year = ?"
            params.append(year)

        total = self.conn.execute(
            f"SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id = p.id {where}",
            params,
        ).fetchone()[0]

        pages = max(1, (total + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        rows = self.conn.execute(
            f"""SELECT p.* FROM paper_topics pt
                JOIN papers p ON pt.paper_id = p.id
                {where}
                ORDER BY p.{sort_col} {order_dir}
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

        paper_ids = [r["id"] for r in rows]
        topics_map = self._batch_get_paper_topics(paper_ids)

        papers = [_row_to_paper(r) for r in rows]
        for paper in papers:
            paper["topics"] = topics_map.get(paper["id"], [])

        return {
            "topic": topic_block,
            "papers": papers,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    def get_paper_topic_counts(self) -> dict[str, int]:
        """Return a mapping of topic slug → paper count for active paper topics."""
        rows = self.conn.execute(
            """SELECT t.slug, COUNT(pt.paper_id) AS cnt
               FROM topics t
               LEFT JOIN paper_topics pt ON t.id = pt.topic_id
               WHERE t.group_name IN (?, ?, ?, ?, ?) AND t.is_active = 1
               GROUP BY t.slug
               ORDER BY t.sort_order""",
            ("基础与模型", "语言与视觉", "生成与智能体", "系统与机器人", "其他"),
        ).fetchall()
        return {r["slug"]: r["cnt"] for r in rows}

    # -- topic news ------------------------------------------------------

    def get_topic_news(
        self,
        slug: str,
        *,
        page: int = 1,
        per_page: int = 20,
        sort: str = "ai_score",
        order: str = "desc",
        blocked_topic_ids: Optional[Iterable[int]] = None,
    ) -> dict[str, Any]:
        """Get paginated news items for a specific topic by slug.

        Only items that made the final digest (``selected = 1``) are
        returned — items dropped after topic classification (e.g. by the
        balanced-digest category quota) keep their ``news_topics`` rows for
        audit purposes but were never enriched/published, so they must not
        surface here.

        Args:
            blocked_topic_ids: When given and this topic's own id is in the
                set, returns the topic (so the page doesn't 404) with an
                empty item list — the caller blocked this exact topic.
        """
        topic = self.conn.execute(
            "SELECT id, name, slug, group_name, description FROM topics WHERE slug = ?",
            (slug,),
        ).fetchone()

        if topic is None:
            return {"topic": None, "items": [], "total": 0, "page": 1, "per_page": per_page, "pages": 0}

        topic_block = {
            "id": topic["id"],
            "name": topic["name"],
            "slug": topic["slug"],
            "group_name": topic["group_name"],
            "description": topic["description"],
        }

        if blocked_topic_ids and topic["id"] in blocked_topic_ids:
            return {
                "topic": topic_block,
                "items": [], "total": 0, "page": 1, "per_page": per_page, "pages": 0,
            }

        allowed_sort = {"ai_score", "published_at", "created_at", "run_date"}
        sort_col = sort if sort in allowed_sort else "ai_score"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        offset = (page - 1) * per_page

        count_row = self.conn.execute(
            """SELECT COUNT(*) AS cnt FROM news_topics nt
               JOIN items i ON nt.news_id = i.id
               WHERE nt.topic_id = ? AND i.selected = 1""",
            (topic["id"],),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = self.conn.execute(
            f"""SELECT i.* FROM news_topics nt
                JOIN items i ON nt.news_id = i.id
                WHERE nt.topic_id = ? AND i.selected = 1
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
            "topic": topic_block,
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    # -- favorites & topic preferences ------------------------------------------
    #
    # `user_id` is an opaque caller-supplied string (an anonymous per-browser
    # id today; a real account id if Horizon ever grows auth) — these methods
    # don't validate or interpret it, they just scope rows by it.

    def set_favorite(self, user_id: str, item_id: str, favorited: bool) -> None:
        """Add or remove a favorite for a user."""
        if favorited:
            self.conn.execute(
                """INSERT OR IGNORE INTO user_item_state (user_id, item_id, state)
                   VALUES (?, ?, 'favorited')""",
                (user_id, item_id),
            )
        else:
            self.conn.execute(
                """DELETE FROM user_item_state
                   WHERE user_id = ? AND item_id = ? AND state = 'favorited'""",
                (user_id, item_id),
            )
        self.conn.commit()

    def get_favorited_ids(self, user_id: str, item_ids: list[str]) -> set[str]:
        """Batch-check which of item_ids are favorited by user_id (avoids N+1)."""
        if not item_ids:
            return set()
        placeholders = ",".join("?" for _ in item_ids)
        rows = self.conn.execute(
            f"""SELECT item_id FROM user_item_state
                WHERE user_id = ? AND state = 'favorited' AND item_id IN ({placeholders})""",
            (user_id, *item_ids),
        ).fetchall()
        return {r["item_id"] for r in rows}

    def get_favorites(self, user_id: str, *, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        """Paginated list of a user's favorited items, most recently favorited first."""
        offset = (page - 1) * per_page

        count_row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_item_state WHERE user_id = ? AND state = 'favorited'",
            (user_id,),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = self.conn.execute(
            """SELECT items.* FROM user_item_state
               JOIN items ON items.id = user_item_state.item_id
               WHERE user_item_state.user_id = ? AND user_item_state.state = 'favorited'
               ORDER BY user_item_state.created_at DESC
               LIMIT ? OFFSET ?""",
            (user_id, per_page, offset),
        ).fetchall()

        items = [_row_to_item(r) for r in rows]
        topics_map = self._batch_get_news_topics([item["id"] for item in items])
        for item in items:
            item["topics"] = topics_map.get(item["id"], [])
            item["is_favorited"] = True

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    # -- paper & report favorites -----------------------------------------------

    def set_paper_favorite(self, user_id: str, paper_id: str, favorited: bool) -> None:
        """Add or remove a paper favorite for a user."""
        if favorited:
            self.conn.execute(
                """INSERT OR IGNORE INTO user_paper_favorites (user_id, paper_id)
                   VALUES (?, ?)""",
                (user_id, paper_id),
            )
        else:
            self.conn.execute(
                "DELETE FROM user_paper_favorites WHERE user_id = ? AND paper_id = ?",
                (user_id, paper_id),
            )
        self.conn.commit()

    def set_report_favorite(self, user_id: str, report_id: str, favorited: bool) -> None:
        """Add or remove a report favorite for a user."""
        if favorited:
            self.conn.execute(
                """INSERT OR IGNORE INTO user_report_favorites (user_id, report_id)
                   VALUES (?, ?)""",
                (user_id, report_id),
            )
        else:
            self.conn.execute(
                "DELETE FROM user_report_favorites WHERE user_id = ? AND report_id = ?",
                (user_id, report_id),
            )
        self.conn.commit()

    def get_favorited_paper_ids(self, user_id: str, paper_ids: list[str]) -> set[str]:
        """Batch-check which of paper_ids are favorited by user_id (avoids N+1)."""
        if not paper_ids:
            return set()
        placeholders = ",".join("?" for _ in paper_ids)
        rows = self.conn.execute(
            f"""SELECT paper_id FROM user_paper_favorites
                WHERE user_id = ? AND paper_id IN ({placeholders})""",
            (user_id, *paper_ids),
        ).fetchall()
        return {r["paper_id"] for r in rows}

    def get_favorited_report_ids(self, user_id: str, report_ids: list[str]) -> set[str]:
        """Batch-check which of report_ids are favorited by user_id (avoids N+1)."""
        if not report_ids:
            return set()
        placeholders = ",".join("?" for _ in report_ids)
        rows = self.conn.execute(
            f"""SELECT report_id FROM user_report_favorites
                WHERE user_id = ? AND report_id IN ({placeholders})""",
            (user_id, *report_ids),
        ).fetchall()
        return {r["report_id"] for r in rows}

    def get_favorited_papers(self, user_id: str, *, page: int = 1, per_page: int = 20, source: str | None = None) -> dict[str, Any]:
        """Paginated list of a user's favorited papers, most recently favorited first."""
        offset = (page - 1) * per_page

        count_params: list[str | int] = [user_id]
        query_params: list[str | int] = [user_id]
        source_clause = ""
        if source:
            source_clause = " AND papers.source = ?"
            count_params.append(source)
            query_params.append(source)

        count_row = self.conn.execute(
            f"""SELECT COUNT(*) AS cnt FROM user_paper_favorites
               JOIN papers ON papers.id = user_paper_favorites.paper_id
               WHERE user_paper_favorites.user_id = ?{source_clause}""",
            count_params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = self.conn.execute(
            f"""SELECT papers.* FROM user_paper_favorites
               JOIN papers ON papers.id = user_paper_favorites.paper_id
               WHERE user_paper_favorites.user_id = ?{source_clause}
               ORDER BY user_paper_favorites.created_at DESC
               LIMIT ? OFFSET ?""",
            (*query_params, per_page, offset),
        ).fetchall()

        papers = [_row_to_paper(r) for r in rows]
        for p in papers:
            p["is_favorited"] = True

        return {
            "items": papers,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def get_favorited_reports(self, user_id: str, *, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        """Paginated list of a user's favorited reports, most recently favorited first."""
        offset = (page - 1) * per_page

        count_row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_report_favorites WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = self.conn.execute(
            """SELECT reports.* FROM user_report_favorites
               JOIN reports ON reports.id = user_report_favorites.report_id
               WHERE user_report_favorites.user_id = ?
               ORDER BY user_report_favorites.created_at DESC
               LIMIT ? OFFSET ?""",
            (user_id, per_page, offset),
        ).fetchall()

        reports = [_row_to_report(r) for r in rows]
        for r in reports:
            r["is_favorited"] = True

        return {
            "items": reports,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def set_topic_pref(self, user_id: str, topic_id: int, state: Optional[str]) -> None:
        """Set ('subscribed'/'blocked') or clear (state=None) a user's preference for one topic."""
        if state is None:
            self.conn.execute(
                "DELETE FROM user_topic_prefs WHERE user_id = ? AND topic_id = ?",
                (user_id, topic_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO user_topic_prefs (user_id, topic_id, state)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, topic_id) DO UPDATE SET state = excluded.state""",
                (user_id, topic_id, state),
            )
        self.conn.commit()

    def get_topic_prefs(self, user_id: str) -> dict[str, str]:
        """Return {topic_slug: state} for every topic this user has a preference for."""
        rows = self.conn.execute(
            """SELECT t.slug, p.state FROM user_topic_prefs p
               JOIN topics t ON t.id = p.topic_id
               WHERE p.user_id = ?""",
            (user_id,),
        ).fetchall()
        return {r["slug"]: r["state"] for r in rows}

    def get_blocked_topic_ids(self, user_id: str) -> set[int]:
        """Internal helper: topic ids this user has blocked."""
        rows = self.conn.execute(
            "SELECT topic_id FROM user_topic_prefs WHERE user_id = ? AND state = 'blocked'",
            (user_id,),
        ).fetchall()
        return {r["topic_id"] for r in rows}
