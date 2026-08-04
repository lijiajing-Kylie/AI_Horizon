from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from src.papers.sources import arxiv as arxiv_source

_ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <published>2026-01-01T17:59:59Z</published>
    <updated>2026-01-02T01:00:00Z</updated>
    <title>Deep Learning with Transformers</title>
    <summary>A transformer architecture for sequence modeling.</summary>
    <author><name>Alice Zhang</name></author>
    <author><name>Bob Liu</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2501.00001v1"/>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="cs.AI"/>
    <arxiv:comment>Code: https://github.com/foo/bar. Accepted at NeurIPS 2025.</arxiv:comment>
    <arxiv:journal_ref/>
  </entry>
</feed>
"""


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "x"), response=self
            )

    @property
    def headers(self) -> dict:
        return {}


class _FakeClient:
    """Minimal httpx.AsyncClient stand-in returning a canned Atom feed."""

    def __init__(self, feed: str = _ATOM_FEED):
        self._feed = feed
        self.calls: list[dict] = []

    async def get(self, url: str, params: dict, timeout: float = 30.0):
        self.calls.append({"url": url, "params": params})
        return _FakeResponse(self._feed)


@pytest.mark.anyio
async def test_fetch_recent_parses_paper() -> None:
    client = _FakeClient()
    papers = await arxiv_source.fetch_recent(client, ["cs.LG"], 1)

    assert len(papers) == 1
    p = papers[0]
    assert p.id == "arxiv:2501.00001"
    assert p.source == "arxiv"
    assert p.native_id == "2501.00001"
    assert p.title == "Deep Learning with Transformers"
    assert p.authors == ["Alice Zhang", "Bob Liu"]
    assert p.abstract.startswith("A transformer architecture")
    assert p.url == "https://arxiv.org/abs/2501.00001"
    assert p.pdf_url == "http://arxiv.org/pdf/2501.00001v1"
    assert p.categories == ["cs.LG", "cs.AI"]
    assert p.category == "cs.LG"
    assert p.comment == "Code: https://github.com/foo/bar. Accepted at NeurIPS 2025."
    assert p.published_at == datetime(2026, 1, 1, 17, 59, 59, tzinfo=timezone.utc)
    assert p.updated_at == datetime(2026, 1, 2, 1, 0, 0, tzinfo=timezone.utc)
    assert p.publication_year == 2026


@pytest.mark.anyio
async def test_fetch_recent_sends_category_query() -> None:
    client = _FakeClient()
    await arxiv_source.fetch_recent(client, ["cs.AI"], 50)

    assert len(client.calls) == 1
    params = client.calls[0]["params"]
    assert params["search_query"] == "cat:cs.AI"
    assert params["sortBy"] == "submittedDate"
    assert params["sortOrder"] == "descending"
    assert params["max_results"] == "50"


@pytest.mark.anyio
async def test_fetch_recent_dedupes_across_categories() -> None:
    # Same entry returned for both categories → deduped to a single paper,
    # keeping the richer (more categories) one.
    client = _FakeClient()
    papers = await arxiv_source.fetch_recent(client, ["cs.LG", "cs.AI"], 5)

    assert len(papers) == 1
    assert papers[0].id == "arxiv:2501.00001"


@pytest.mark.anyio
async def test_fetch_recent_skips_entries_without_title() -> None:
    empty_feed = _ATOM_FEED.replace("<title>Deep Learning with Transformers</title>", "<title></title>")
    client = _FakeClient(empty_feed)
    papers = await arxiv_source.fetch_recent(client, ["cs.LG"], 1)
    assert papers == []


def test_normalize_keeps_backward_compatible_keys() -> None:
    """_normalize still exposes the legacy 'year' key alongside published_at."""
    from xml.etree import ElementTree

    root = ElementTree.fromstring(_ATOM_FEED)
    entry = root.find("{http://www.w3.org/2005/Atom}entry")
    norm = arxiv_source._normalize(entry)

    assert norm["year"] == 2026
    assert norm["published_at"] == "2026-01-01T17:59:59Z"
    assert norm["updated_at"] == "2026-01-02T01:00:00Z"
    assert norm["arxiv_id"] == "2501.00001"
    assert norm["categories"] == ["cs.LG", "cs.AI"]
    assert norm["primary_category"] == "cs.LG"
