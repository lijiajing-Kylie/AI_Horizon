from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.models import HuggingFaceSourceConfig
from src.papers.sources.huggingface import HuggingFaceFetcher, _last_full_month


def _paper_info(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="2501.12345",
        title="A Trending Paper",
        summary="An abstract about a trending paper.",
        authors=[SimpleNamespace(name="Alice Smith"), SimpleNamespace(name="Bob Jones")],
        published_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        submitted_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        upvotes=42,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_api(pages: list[list]) -> MagicMock:
    """A fake HfApi whose list_daily_papers returns successive pages by call order."""
    api = MagicMock()
    api.list_daily_papers.side_effect = pages
    return api


def test_fetch_ranks_by_upvotes_and_takes_top_n() -> None:
    infos = [
        _paper_info(id="2501.1", upvotes=10),
        _paper_info(id="2501.2", upvotes=99),
        _paper_info(id="2501.3", upvotes=50),
    ]
    api = _fake_api([infos])  # single page, under the 100-page-size threshold
    fetcher = HuggingFaceFetcher(HuggingFaceSourceConfig(top_n=2), api=api)

    papers = asyncio.run(fetcher.fetch(client=None))

    assert [p.native_id for p in papers] == ["2501.2", "2501.3"]


def test_fetch_paginates_until_a_short_page() -> None:
    full_page = [_paper_info(id=f"2501.{i}", upvotes=i) for i in range(100)]
    short_page = [_paper_info(id="2501.last", upvotes=1000)]
    api = _fake_api([full_page, short_page])
    fetcher = HuggingFaceFetcher(HuggingFaceSourceConfig(top_n=1), api=api)

    papers = asyncio.run(fetcher.fetch(client=None))

    assert api.list_daily_papers.call_count == 2
    assert papers[0].native_id == "2501.last"


def test_calls_list_daily_papers_with_month_and_published_at_sort() -> None:
    api = _fake_api([[]])
    fetcher = HuggingFaceFetcher(HuggingFaceSourceConfig(top_n=5), api=api)

    asyncio.run(fetcher.fetch(client=None))

    _, kwargs = api.list_daily_papers.call_args
    assert kwargs["sort"] == "publishedAt"
    assert kwargs["limit"] == 100
    assert re.match(r"^\d{4}-\d{2}$", kwargs["month"])


def test_missing_published_and_submitted_at_is_skipped() -> None:
    api = _fake_api([[_paper_info(published_at=None, submitted_at=None)]])
    fetcher = HuggingFaceFetcher(HuggingFaceSourceConfig(), api=api)

    assert asyncio.run(fetcher.fetch(client=None)) == []


def test_api_error_returns_empty() -> None:
    api = MagicMock()
    api.list_daily_papers.side_effect = RuntimeError("boom")
    fetcher = HuggingFaceFetcher(HuggingFaceSourceConfig(), api=api)

    assert asyncio.run(fetcher.fetch(client=None)) == []


def test_last_full_month_is_before_current_month() -> None:
    month = _last_full_month()
    first_of_this_month = datetime.now(timezone.utc).date().replace(day=1)
    parsed = datetime.strptime(month, "%Y-%m").date()

    assert parsed < first_of_this_month
