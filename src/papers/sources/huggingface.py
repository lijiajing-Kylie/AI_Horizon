"""Hugging Face daily-papers source: top-trending papers for the last full month.

Uses the official `huggingface_hub` client (`HfApi.list_daily_papers`) rather
than hitting `/api/daily_papers` directly. `HfApi` is a synchronous client, so
calls are pushed onto a thread via `asyncio.to_thread` to avoid blocking the
event loop shared with the other async fetchers.

`list_daily_papers(sort="trending")` ignores the `month` filter entirely
(verified empirically — it returns globally-trending papers spanning years,
not "trending within that month"), and a single call is capped at 100 results
(`p` is a page index, not auto-paginated). So instead: page through every
paper submitted in the target month with `sort="publishedAt"` (which *does*
respect `month`), then rank by `upvotes` ourselves and keep the top N.

After collecting candidates, batch-enriches them with arXiv metadata
(journal_ref, categories, comment) and optionally filters by topic keywords
before selecting the final top N by upvotes.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from huggingface_hub import HfApi

from ...models import HuggingFaceSourceConfig
from ..models import Paper
from . import arxiv
from .base import PaperSourceFetcher

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 30  # safety cap (30 * 100 = 3000 papers/month); a real month tops out around 10 pages
_CANDIDATE_LIMIT = 100  # how many top-upvoted papers to arXiv-enrich before filtering


class HuggingFaceFetcher(PaperSourceFetcher):
    """Fetches the top-upvoted Hugging Face daily papers for the last full month,
    enriched with arXiv metadata and optionally filtered by topic keywords."""

    source_name = "huggingface"

    def __init__(self, config: HuggingFaceSourceConfig, api: Optional[HfApi] = None):
        self.cfg = config
        self._api = api or HfApi()

    async def fetch(
        self,
        client: httpx.AsyncClient,
        month: Optional[str] = None,
        week: Optional[str] = None,
        top_n_override: Optional[int] = None,
        no_enrich: bool = False,
    ) -> List[Paper]:
        """Fetch top-upvoted papers for a time period.

        When *week* is given, fetch that ISO week (YYYY-Www). When *month* is
        given, fetch that month (YYYY-MM). When neither is given, defaults to
        the last full calendar month (backward-compatible).

        When *no_enrich* is True, skip the arXiv batch-enrichment step
        (journal_ref, categories, comment).
        """
        top_n = top_n_override if top_n_override is not None else self.cfg.top_n

        # Determine the time window and label for logging.
        try:
            if week:
                period_label = week
                infos = await asyncio.to_thread(self._fetch_week, week)
            elif month:
                period_label = month
                infos = await asyncio.to_thread(self._fetch_month, month)
            else:
                period_label = _last_full_month()
                infos = await asyncio.to_thread(self._fetch_month, period_label)
        except Exception as e:
            period_hint = week or month or _last_full_month()
            logger.warning("Error fetching Hugging Face daily papers for %s: %s", period_hint, e)
            return []

        if not infos:
            logger.info("No Hugging Face daily papers found for %s", period_label)
            return []

        # Step 1: sort by upvotes, keep top candidates for enrichment
        infos.sort(key=lambda i: i.upvotes or 0, reverse=True)
        cap = max(_CANDIDATE_LIMIT, top_n)
        candidates = infos[:cap]
        logger.info(
            "Hugging Face: %d papers in %s, enriching top %d candidates (top_n=%d)",
            len(infos), period_label, len(candidates), top_n,
        )

        # Step 2: convert to Paper objects (basic fields from HF)
        papers = [self._info_to_paper(info) for info in candidates]
        papers = [p for p in papers if p is not None]

        # Step 3: batch arXiv enrichment (journal_ref, categories, comment)
        if not no_enrich:
            papers = await self._enrich_with_arxiv(client, papers)

        # Step 4: topic keyword filtering (if configured)
        if self.cfg.topics:
            papers = self._filter_by_topics(papers)

        # Step 5: re-sort by upvotes, keep final top N
        papers.sort(key=lambda p: p.upvote_count or 0, reverse=True)
        final = papers[:top_n]
        logger.info(
            "Hugging Face: returning %d papers (from %d enriched, top_n=%d)",
            len(final), len(papers), top_n,
        )
        return final

    def _fetch_month(self, month: str) -> list:
        """Page through every daily paper submitted in `month` (sync; runs in a thread)."""
        infos = []
        for page in range(_MAX_PAGES):
            batch = list(
                self._api.list_daily_papers(
                    month=month, sort="publishedAt", limit=_PAGE_SIZE, p=page
                )
            )
            infos.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
        return infos

    def _fetch_week(self, week: str) -> list:
        """Page through every daily paper submitted in `week` (sync; runs in a thread).

        A typical week has ~50-70 papers, well under _PAGE_SIZE (100), but we
        paginate defensively."""
        infos = []
        for page in range(_MAX_PAGES):
            batch = list(
                self._api.list_daily_papers(
                    week=week, sort="publishedAt", limit=_PAGE_SIZE, p=page
                )
            )
            infos.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
        return infos

    async def _enrich_with_arxiv(
        self, client: httpx.AsyncClient, papers: List[Paper]
    ) -> List[Paper]:
        """Batch-enrich papers with arXiv metadata (journal_ref, categories, comment).

        For HF papers, native_id IS the arXiv ID (e.g. "2501.12345").
        Papers that fail arXiv lookup keep their original fields unchanged.
        """
        if not papers:
            return papers

        # Build arXiv ID → Paper mapping
        arxiv_ids: List[str] = []
        paper_map: dict[str, Paper] = {}
        for p in papers:
            aid = p.native_id.strip()
            if aid:
                arxiv_ids.append(aid)
                paper_map[aid] = p

        if not arxiv_ids:
            return papers

        try:
            enriched = await arxiv.lookup_by_ids(client, arxiv_ids)
        except Exception as e:
            logger.warning("arXiv batch enrichment failed: %s", e)
            return papers

        updated = 0
        for arxiv_id, result in enriched.items():
            if result is None:
                continue
            p = paper_map.get(arxiv_id)
            if p is None:
                continue

            # Only fill fields that are currently empty/none
            jr = result.get("journal_ref")
            if jr:
                p.journal_ref = jr
                updated += 1

            comment = result.get("comment")
            if comment:
                p.comment = comment

            cats = result.get("categories")
            if cats:
                p.categories = cats

        logger.info("arXiv enrichment: updated %d/%d papers", updated, len(papers))
        return papers

    def _filter_by_topics(self, papers: List[Paper]) -> List[Paper]:
        """Filter papers to those matching at least one configured topic keyword.

        Matching is case-insensitive and checks: title, abstract, categories,
        journal_ref, and authors. Returns only matching papers. If no papers
        match, logs a warning and returns all papers unfiltered (fallback).
        """
        if not self.cfg.topics:
            return papers

        keywords = [kw.lower() for kw in self.cfg.topics]

        def matches(paper: Paper) -> bool:
            fields_to_check = [
                paper.title or "",
                paper.abstract or "",
                paper.journal_ref or "",
                " ".join(paper.categories),
                " ".join(paper.authors),
            ]
            combined = " ".join(fields_to_check).lower()
            return any(kw in combined for kw in keywords)

        filtered = [p for p in papers if matches(p)]

        if not filtered:
            logger.warning(
                "Topic filtering (%r) matched 0/%d papers; returning all unfiltered.",
                self.cfg.topics,
                len(papers),
            )
            return papers

        logger.info(
            "Topic filtering (%r): %d/%d papers matched.",
            self.cfg.topics,
            len(filtered),
            len(papers),
        )
        return filtered

    def _info_to_paper(self, info) -> Optional[Paper]:
        """Convert a single huggingface_hub `PaperInfo` into a Paper."""
        native_id = info.id
        title = (info.title or "").strip()
        if not native_id or not title:
            return None

        published_at = info.published_at or info.submitted_at
        if published_at is None:
            return None
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        authors = [a.name for a in (info.authors or []) if a.name]

        return Paper(
            id=f"{self.source_name}:{native_id}",
            source=self.source_name,
            native_id=native_id,
            title=title,
            authors=authors,
            abstract=(info.summary or "").strip(),
            url=f"https://huggingface.co/papers/{native_id}",
            pdf_url=f"https://arxiv.org/pdf/{native_id}",
            published_at=published_at,
            updated_at=published_at,
            publication_year=published_at.year,
            arxiv_id=native_id,
            upvote_count=info.upvotes,
            fetched_at=datetime.now(timezone.utc),
        )


def _last_full_month() -> str:
    """Return the last completed calendar month as "YYYY-MM" (UTC)."""
    first_of_this_month = datetime.now(timezone.utc).date().replace(day=1)
    last_day_of_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_of_prev_month.strftime("%Y-%m")


def _last_week() -> str:
    """Return the last completed ISO week as "YYYY-Www" (UTC)."""
    today = datetime.now(timezone.utc).date()
    # ISO weeks start on Monday; the current week's Monday
    monday = today - timedelta(days=today.weekday())
    # Previous week's Monday
    prev_monday = monday - timedelta(days=7)
    iso_year, iso_week, _ = prev_monday.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"
