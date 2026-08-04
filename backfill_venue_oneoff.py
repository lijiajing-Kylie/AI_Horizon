"""One-off backfill: apply seed_data.py canonical_venue to existing DB rows.

Without re-fetching from OpenAlex, updates the `journal_ref` column of already
persisted openalex papers to the human-curated canonical venue.

Match priority (by seed field):
  1. openalex_id_override  -> papers.openalex_id_override
  2. canonical_doi / doi   -> papers.doi (normalized)
  3. arxiv_id              -> papers.arxiv_id column
  4. arxiv_id              -> papers.url / papers.pdf_url (arxiv.org/abs|pdf/{id})
  5. normalized title      -> papers.title (exact, with \\n / nets~networks aliases)

Run:  uv run python backfill_venue_oneoff.py
"""

import re
import sqlite3

from src.papers.seed_data import SEED_PAPERS

DB_PATH = "data/horizon.db"


def norm_title(s: str) -> str:
    s = (s or "").replace("\\n", " ").replace("\n", " ")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def norm_doi(s: str) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (s or "").strip().lower())


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, doi, arxiv_id, openalex_id_override, url, pdf_url, "
        "journal_ref FROM papers WHERE source='openalex'"
    ).fetchall()

    # Build per-key indexes (first occurrence wins).
    idx = {"oa_override": {}, "doi": {}, "arxiv_col": {}, "arxiv_url": {}, "title": {}}
    for r in rows:
        idx["oa_override"].setdefault((r["openalex_id_override"] or "").strip(), r)
        if r["doi"]:
            idx["doi"].setdefault(norm_doi(r["doi"]), r)
        if r["arxiv_id"]:
            idx["arxiv_col"].setdefault(r["arxiv_id"].strip(), r)
        for field in ("url", "pdf_url"):
            m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]+\.[0-9]+)", r[field] or "")
            if m:
                idx["arxiv_url"].setdefault(m.group(1), r)
        idx["title"].setdefault(norm_title(r["title"]), r)

    def resolve(seed) -> sqlite3.Row | None:
        if seed.openalex_id_override and seed.openalex_id_override.strip() in idx["oa_override"]:
            return idx["oa_override"][seed.openalex_id_override.strip()]
        for key in ("canonical_doi", "doi"):
            d = getattr(seed, key)
            if d and norm_doi(d) in idx["doi"]:
                return idx["doi"][norm_doi(d)]
        if seed.arxiv_id and seed.arxiv_id.strip() in idx["arxiv_col"]:
            return idx["arxiv_col"][seed.arxiv_id.strip()]
        if seed.arxiv_id and seed.arxiv_id.strip() in idx["arxiv_url"]:
            return idx["arxiv_url"][seed.arxiv_id.strip()]
        nt = norm_title(seed.title)
        for cand_title, cand in idx["title"].items():
            if (
                cand_title == nt
                or cand_title.replace("networks", "nets") == nt
                or cand_title.replace("nets", "networks") == nt
            ):
                return cand
        return None

    updated, skipped = [], []
    with conn:  # transaction
        for seed in SEED_PAPERS:
            if not seed.canonical_venue:
                continue
            row = resolve(seed)
            if row is None:
                skipped.append(seed.title)
                continue
            cur = conn.execute(
                "UPDATE papers SET journal_ref=?, updated_row_at=datetime('now') "
                "WHERE id=?",
                (seed.canonical_venue, row["id"]),
            )
            if cur.rowcount:
                updated.append((seed.title, row["id"], row["journal_ref"]))
            else:
                skipped.append(seed.title)

    print(f"更新: {len(updated)}  跳过: {len(skipped)}")
    print("\n-- 已更新 --")
    for t, pid, old in updated:
        print(f"{t[:40]:42} [{pid}]  {old or '(空)'} -> 更新为 canonical_venue")
    if skipped:
        print("\n-- 未匹配（库中不存在） --")
        for t in skipped:
            print(" -", t)

    conn.close()


if __name__ == "__main__":
    main()
