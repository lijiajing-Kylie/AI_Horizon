"""Unit tests for WxMpScraper."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import WxMpConfig, WxMpSourceConfig
from src.scrapers.wxmp import WxMpScraper


def _make_feed_json(items: list[dict]) -> str:
    """Build a fake /feed/{id}.json response body."""
    import json
    return json.dumps({"items": items}, ensure_ascii=False)


def _mock_response(data: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = data
    resp.status_code = status
    # For response.json() use the raw parsed data
    import json
    resp.json.return_value = json.loads(data) if isinstance(data, str) else data
    resp.raise_for_status.return_value = None
    return resp


def _mock_async_client(feed_responses: dict[str, MagicMock]) -> AsyncMock:
    """Create an AsyncMock httpx client that returns per-URL responses."""
    client = AsyncMock()

    async def side_effect(url, **kwargs):
        for pattern, resp in feed_responses.items():
            if pattern in url:
                return resp
        # Default: return empty feed
        empty = MagicMock()
        empty.text = '{"items": []}'
        empty.json.return_value = {"items": []}
        empty.raise_for_status.return_value = None
        return empty

    client.get.side_effect = side_effect
    return client


# ── Sample feed JSON data ────────────────────────────────────────────────

_SAMPLE_ARTICLES = [
    {
        "id": "art_001",
        "title": "AI 大模型最新进展",
        "description": "本文介绍了大模型领域的多个重要突破",
        "link": "https://mp.weixin.qq.com/s/test1",
        "updated": "2026-07-28T10:00:00+08:00",
        "content": "<p>大模型在推理能力上取得了显著进展…</p>",
        "channel_name": "机器之心",
        "image": "https://mmbiz.qpic.cn/cover1",
        "feed": {"id": "MP_WXS_001", "name": "机器之心", "cover": "", "intro": ""},
    },
    {
        "id": "art_002",
        "title": "强化学习新方法",
        "description": "一种新的强化学习方法",
        "link": "https://mp.weixin.qq.com/s/test2",
        "updated": "2026-07-27T14:30:00+08:00",
        "content": "<p>强化学习的最新方法…</p>",
        "channel_name": "机器之心",
        "image": "",
        "feed": {"id": "MP_WXS_001", "name": "机器之心", "cover": "", "intro": ""},
    },
    {
        "id": "art_003",
        "title": "老文章",
        "description": "旧闻",
        "link": "https://mp.weixin.qq.com/s/test3",
        "updated": "2026-07-20T08:00:00+08:00",
        "content": "<p>较老的内容…</p>",
        "channel_name": "机器之心",
        "image": "",
        "feed": {"id": "MP_WXS_001", "name": "机器之心", "cover": "", "intro": ""},
    },
]


# ── Tests ─────────────────────────────────────────────────────────────────


def test_parse_articles_within_time_window() -> None:
    """Should return only articles published after the 'since' cutoff."""
    feed_json = _make_feed_json(_SAMPLE_ARTICLES)
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 26, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))

    assert len(items) == 2, f"Expected 2 items, got {len(items)}"
    titles = [i.title for i in items]
    assert "AI 大模型最新进展" in titles
    assert "强化学习新方法" in titles
    assert "老文章" not in titles


def test_source_type_is_wechat() -> None:
    """Items should have source_type WECHAT."""
    feed_json = _make_feed_json([_SAMPLE_ARTICLES[0]])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert len(items) == 1
    assert items[0].source_type.value == "wechat"


def test_high_content_quality_with_full_content() -> None:
    """Items with content should have rss_content_quality='high'."""
    feed_json = _make_feed_json([_SAMPLE_ARTICLES[0]])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items[0].rss_content_quality == "high"
    assert items[0].content == "<p>大模型在推理能力上取得了显著进展…</p>"


def test_low_content_quality_when_no_content() -> None:
    """Items without content should have rss_content_quality='low'."""
    article = dict(_SAMPLE_ARTICLES[0])
    article["content"] = ""
    feed_json = _make_feed_json([article])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items[0].rss_content_quality == "low"
    assert items[0].content == ""


def test_metadata_populated() -> None:
    """Item metadata should include feed_name, feed_id, category, pic_url."""
    feed_json = _make_feed_json([_SAMPLE_ARTICLES[0]])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001", category="wechat-account")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    meta = items[0].metadata
    assert meta["feed_name"] == "机器之心"
    assert meta["feed_id"] == "MP_WXS_001"
    assert meta["category"] == "wechat-account"
    assert meta["pic_url"] == "https://mmbiz.qpic.cn/cover1"


def test_author_falls_back_to_feed_name() -> None:
    """Author should default to the configured feed name when channel_name is missing."""
    article = dict(_SAMPLE_ARTICLES[0])
    article.pop("channel_name", None)
    feed_json = _make_feed_json([article])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items[0].author == "机器之心"


def test_empty_feed_returns_empty() -> None:
    """An empty feed should return an empty list without error."""
    feed_json = '{"items": []}'
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items == []


def test_network_error_returns_empty() -> None:
    """A network error fetching a feed should log a warning and return empty list."""
    client = AsyncMock()
    client.get.side_effect = Exception("Connection refused")

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001")],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items == []


def test_disabled_feeds_are_skipped() -> None:
    """Feeds with enabled=False should not be fetched."""
    feed_json = _make_feed_json([_SAMPLE_ARTICLES[0]])
    resp = _mock_response(feed_json)
    client = _mock_async_client({"MP_WXS_001": resp})

    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001", enabled=False),
        ],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items == []


def test_multiple_feeds() -> None:
    """Multiple enabled feeds should all be fetched."""
    feed1 = _mock_response(_make_feed_json([_SAMPLE_ARTICLES[0]]))
    feed2 = _mock_response(_make_feed_json([_SAMPLE_ARTICLES[1]]))
    client = _mock_async_client({"MP_WXS_001": feed1, "MP_WXS_002": feed2})

    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(name="机器之心", feed_id="MP_WXS_001"),
            WxMpSourceConfig(name="量子位", feed_id="MP_WXS_002"),
        ],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert len(items) == 2


def test_feed_id_resolution_on_first_fetch() -> None:
    """When feed_id is None, scraper should resolve it lazily on first fetch()."""
    mps_response_data = {
        "data": {
            "list": [
                {"id": "MP_WXS_001", "mp_name": "机器之心", "status": 1},
                {"id": "MP_WXS_002", "mp_name": "量子位", "status": 1},
            ]
        }
    }
    mps_resp = MagicMock()
    mps_resp.json.return_value = mps_response_data
    mps_resp.raise_for_status.return_value = None
    mps_resp.status_code = 200

    feed_resp = _mock_response(_make_feed_json([_SAMPLE_ARTICLES[0]]))
    feed_resp2 = _mock_response(_make_feed_json([_SAMPLE_ARTICLES[1]]))

    client = AsyncMock()
    call_count = {"count": 0}

    async def side_effect(url, **kwargs):
        if "/api/v1/wx/mps" in url:
            call_count["count"] += 1
            return mps_resp
        if "MP_WXS_001" in url:
            return feed_resp
        if "MP_WXS_002" in url:
            return feed_resp2
        empty = MagicMock()
        empty.text = '{"items": []}'
        empty.json.return_value = {"items": []}
        empty.raise_for_status.return_value = None
        return empty

    client.get.side_effect = side_effect

    config = WxMpConfig(
        feeds=[
            WxMpSourceConfig(name="机器之心"),  # no feed_id
            WxMpSourceConfig(name="量子位"),  # no feed_id
        ],
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert len(items) == 2
    # Should have resolved feed_ids via the /mps API call
    assert config.feeds[0].feed_id == "MP_WXS_001"
    assert config.feeds[1].feed_id == "MP_WXS_002"
    assert call_count["count"] == 1  # only one API call for both

    # Second fetch should not call the /mps API again
    items2 = asyncio.run(scraper.fetch(since))
    assert len(items2) == 2
    assert call_count["count"] == 1  # still 1


def test_parse_published_iso_string() -> None:
    """ISO-8601 string should parse correctly."""
    raw = {"updated": "2026-07-28T10:00:00+08:00"}
    dt = WxMpScraper._parse_published(raw)
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 28


def test_parse_published_unix_timestamp() -> None:
    """Unix timestamp (int) should parse correctly."""
    raw = {"updated": 1722153600}
    dt = WxMpScraper._parse_published(raw)
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_published_none() -> None:
    """Missing updated field should return None."""
    raw = {"title": "no date"}
    dt = WxMpScraper._parse_published(raw)
    assert dt is None


def test_missing_feed_id_after_resolution() -> None:
    """Feed that fails to resolve feed_id should be skipped gracefully."""
    mps_response_data = {"data": {"list": []}}
    mps_resp = MagicMock()
    mps_resp.json.return_value = mps_response_data
    mps_resp.raise_for_status.return_value = None
    mps_resp.status_code = 200

    client = AsyncMock()
    client.get.side_effect = lambda url, **kw: mps_resp if "mps" in url else _mock_response('{"items": []}')

    config = WxMpConfig(
        feeds=[WxMpSourceConfig(name="未知的公众号")],  # no feed_id, won't resolve
    )
    scraper = WxMpScraper(config, client)
    since = datetime(2026, 7, 27, tzinfo=timezone.utc)

    items = asyncio.run(scraper.fetch(since))
    assert items == []
