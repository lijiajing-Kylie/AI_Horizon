"""Unit tests for the Aliyun Reports source and PDF utilities.

Tests parsing logic with mock JSON data — no network or Playwright needed.
"""

import pytest

from src.reports.pdf import sanitize_filename


# ── sanitize_filename ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "input_name, expected",
    [
        ("正常文件名", "正常文件名"),
        ("报告:AI/2026", "报告_AI_2026"),
        ("test<report>.pdf", "test_report_.pdf"),
        ("  spaces  ", "spaces"),
        (".leading_dot", "leading_dot"),
        ("trailing.", "trailing"),
        ("", "report"),
        ("a" * 200, "a" * 120),  # truncation without extension
        ("x" * 200 + ".pdf", "x" * 116 + ".pdf"),  # truncation preserving extension
    ],
)
def test_sanitize_filename(input_name, expected):
    assert sanitize_filename(input_name) == expected


# ── AliyunReportsConfig ──────────────────────────────────────────────────────

def test_default_config_values():
    from src.reports.sources.aliyunreports import AliyunReportsConfig

    config = AliyunReportsConfig()
    assert config.content_category == "报告"
    assert config.year == "2026年"
    assert config.tech_category == "人工智能"
    assert config.pdf_output_dir == "data/reports_pdfs"
    assert config.browser_profile_dir == "data/aliyun_profile"
    assert config.headless is False
    assert config.download_pdfs is True
    assert config.max_retries == 3


# ── API response parsing ─────────────────────────────────────────────────────

# Representative mock data — field names and structure will be refined
# once the actual API responses are intercepted from the live site.

MOCK_LIST_RESPONSE = {
    "success": True,
    "code": "200",
    "data": [
        {
            "id": "123",
            "title": "阿里云AI十大技术进展",
            "slug": "2026-ai-top10tech",
            "publishDate": "2026-03-15",
            "categoryNames": ["报告", "人工智能"],
        },
        {
            "id": "456",
            "title": "AI消费硬件产业报告",
            "slug": "2026-ai-consumer-electronics",
            "publishDate": "2026-02-10",
            "categoryNames": ["报告", "人工智能"],
        },
    ],
}

MOCK_DETAIL_RESPONSE = {
    "success": True,
    "code": "200",
    "data": {
        "slug": "2026-ai-top10tech",
        "title": "阿里云AI十大技术进展",
        "institution": "阿里云",
        "author": "阿里云研究中心",
        "summary": "本报告梳理了2026年AI领域十大技术突破。",
        "publishDate": "2026-03-15 10:00:00",
        "updateDate": "2026-03-20 14:00:00",
        "categoryNames": ["人工智能", "报告"],
        "pdfList": [
            {"name": "阿里云AI十大技术进展", "url": "https://example.com/report.pdf"},
        ],
        "content": "<p>本报告梳理了2026年AI领域十大技术突破...</p>",
        "viewCount": 1500,
        "downloadCount": 380,
    },
}


def test_parse_list_response_returns_slugs():
    from src.reports.sources.aliyunreports import AliyunReportsFetcher

    fetcher = AliyunReportsFetcher()
    ids = fetcher._parse_list_response(MOCK_LIST_RESPONSE)
    assert ids == ["2026-ai-top10tech", "2026-ai-consumer-electronics"]


def test_parse_list_response_empty_on_failure():
    from src.reports.sources.aliyunreports import AliyunReportsFetcher

    fetcher = AliyunReportsFetcher()
    assert fetcher._parse_list_response({"success": False}) == []
    assert fetcher._parse_list_response({"success": True, "data": None}) == []


def test_parse_detail_response_builds_report():
    from src.reports.sources.aliyunreports import AliyunReportsFetcher

    fetcher = AliyunReportsFetcher()
    report = fetcher._parse_detail_response(MOCK_DETAIL_RESPONSE, "2026-ai-top10tech")

    assert report is not None
    assert report.id == "aliyunreports:2026-ai-top10tech"
    assert report.source == "aliyunreports"
    assert report.title == "阿里云AI十大技术进展"
    assert report.institution == "阿里云"
    assert report.author == "阿里云研究中心"
    assert "人工智能" in report.categories
    assert len(report.pdf_urls) == 1
    assert report.pdf_urls[0]["name"] == "阿里云AI十大技术进展"
    assert report.content_text != ""


def test_parse_detail_response_none_on_missing_data():
    from src.reports.sources.aliyunreports import AliyunReportsFetcher

    fetcher = AliyunReportsFetcher()
    assert fetcher._parse_detail_response({"success": True, "data": None}, "x") is None
    assert fetcher._parse_detail_response({"success": False}, "x") is None
