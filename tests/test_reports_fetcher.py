from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.models import ReportsConfig
from src.reports.fetcher import fetch_all_reports
from src.reports.sources.aliresearch import AliResearchFetcher


def _json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


LIST_PAYLOAD = {
    "success": True,
    "msg": "success",
    "code": "200",
    "total": 517,
    "data": [
        {"articleCode": "591792162400768000", "title": "阿里发布职业趋势报告"},
        {"articleCode": "561785991325683712", "title": "淘宝隐藏土特产报告"},
    ],
}

DETAIL_PAYLOAD = {
    "success": True,
    "msg": "success",
    "code": "200",
    "data": {
        "articleCode": "591792162400768000",
        "title": "阿里发布职业趋势报告 详解AI时代工作怎么变",
        "author": "阿里巴巴",
        "organName": "",
        "type": "新闻,报告",
        "special": "数字经济,创业就业",
        "description": "",
        "content": "<p>正文第一段。</p><p>正文第二段。</p>",
        "gmtCreated": "2024-04-25 11:21:44",
        "gmtModified": "2024-04-25 11:23:06",
        "viewCount": 1249071,
        "downloadCount": 1414,
        "docUrlList": [
            {"name": "阿里发布AI职业趋势报告", "url": "https://oss.example.com/report.pdf"}
        ],
    },
}


def test_fetch_native_ids_parses_list() -> None:
    client = AsyncMock()
    client.post.return_value = _json_response(LIST_PAYLOAD)
    fetcher = AliResearchFetcher()

    ids = asyncio.run(fetcher.fetch_native_ids(client))

    assert ids == ["591792162400768000", "561785991325683712"]
    call = client.post.call_args
    assert call.kwargs["json"]["type"] == "报告"


def test_fetch_detail_parses_full_report() -> None:
    client = AsyncMock()
    client.post.return_value = _json_response(DETAIL_PAYLOAD)
    fetcher = AliResearchFetcher()

    report = asyncio.run(fetcher.fetch_detail(client, "591792162400768000"))

    assert report is not None
    assert report.id == "aliresearch:591792162400768000"
    assert report.source == "aliresearch"
    assert report.institution == "阿里巴巴"
    assert "正文第一段。" in report.content_text
    assert "正文第二段。" in report.content_text
    assert report.pdf_urls == [{"name": "阿里发布AI职业趋势报告", "url": "https://oss.example.com/report.pdf"}]
    assert set(report.categories) == {"新闻", "报告", "数字经济", "创业就业"}
    assert report.published_at.year == 2024
    assert report.view_count == 1249071


def test_fetch_detail_returns_none_on_failure() -> None:
    client = AsyncMock()
    client.post.return_value = _json_response({"success": False, "msg": "服务器异常", "data": None})
    fetcher = AliResearchFetcher()

    assert asyncio.run(fetcher.fetch_detail(client, "bad-id")) is None


def test_fetch_native_ids_returns_empty_on_http_error() -> None:
    client = AsyncMock()
    client.post.side_effect = httpx.HTTPError("boom")
    fetcher = AliResearchFetcher()

    assert asyncio.run(fetcher.fetch_native_ids(client)) == []


def test_fetch_all_reports_orchestrates_list_and_detail() -> None:
    client = AsyncMock()
    client.post.side_effect = [
        _json_response(LIST_PAYLOAD),
        _json_response(DETAIL_PAYLOAD),
        _json_response({"success": False, "msg": "not found", "data": None}),
    ]
    config = ReportsConfig(enabled=True, sources=["aliresearch"])

    reports = asyncio.run(fetch_all_reports(config, client))

    assert len(reports) == 1
    assert reports[0].id == "aliresearch:591792162400768000"


def test_fetch_all_reports_skips_unknown_source() -> None:
    client = AsyncMock()
    config = ReportsConfig(enabled=True, sources=["unknown-source"])

    reports = asyncio.run(fetch_all_reports(config, client))

    assert reports == []
    client.post.assert_not_called()
