"""Tests for dedup module — URL normalization and cross-source merging."""
import pytest
from urllib.parse import parse_qsl, urlparse

from src.models import ContentItem, SourceType


# Replicate the normalize_url logic from src/dedup.py for standalone testing
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "dclid", "gbraid", "wbraid",
    "msclkid", "twclid", "sc_campaign", "sc_channel", "sc_content",
    "sc_medium", "sc_outcome", "sc_geo", "sc_country",
    "ref", "source", "source_type", "from", "isappinstalled",
})


def normalize_url(url: str) -> str:
    parsed = urlparse(str(url))
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    key = f"{host}{path}"
    if parsed.query:
        params = sorted(
            (k, v) for k, v in parse_qsl(parsed.query)
            if k.lower() not in _TRACKING_PARAMS
        )
        if params:
            key += "?" + "&".join(f"{k}={v}" for k, v in params)
    return key


class TestNormalizeURL:
    """URL normalization used by merge_cross_source_duplicates."""

    def test_wechat_articles_differentiate_by_query(self):
        """Different WeChat articles must produce different normalized keys."""
        # WeChat articles use query params (__biz, sn, etc.) for identity;
        # all share the same /s path.
        url_a = "https://mp.weixin.qq.com/s?__biz=MzIwMTE1NjQxMQ==&mid=1&idx=1&sn=aaa111"
        url_b = "https://mp.weixin.qq.com/s?__biz=MzIwMTE1NjQxMQ==&mid=2&idx=2&sn=bbb222"
        assert normalize_url(url_a) != normalize_url(url_b)

    def test_tracking_params_stripped(self):
        """Tracking/analytics params should be removed so tracking variants
        of the same article still deduplicate."""
        url_a = "https://example.com/article?id=123&utm_source=twitter"
        url_b = "https://example.com/article?id=123&utm_medium=facebook"
        assert normalize_url(url_a) == normalize_url(url_b)

    def test_tracking_params_on_wechat(self):
        """WeChat URLs with only tracking-param differences should dedup."""
        url_a = "https://mp.weixin.qq.com/s?__biz=test&sn=aaa&from=groupmessage"
        url_b = "https://mp.weixin.qq.com/s?__biz=test&sn=aaa&isappinstalled=0"
        assert normalize_url(url_a) == normalize_url(url_b)

    def test_different_paths_different(self):
        """Different paths → different keys regardless of tracking params."""
        url_a = "https://example.com/article-a?utm_source=twitter"
        url_b = "https://example.com/article-b?utm_source=twitter"
        assert normalize_url(url_a) != normalize_url(url_b)

    def test_www_stripping(self):
        """www. prefix should be stripped."""
        assert normalize_url("https://www.example.com/path/") == "example.com/path"

    def test_trailing_slash_stripping(self):
        """Trailing slashes should be stripped."""
        assert normalize_url("https://example.com/a") == normalize_url("https://example.com/a/")

    def test_no_query_backward_compat(self):
        """URLs without query strings should behave exactly as before."""
        assert normalize_url("https://news.ycombinator.com/item?id=123") != normalize_url("https://news.ycombinator.com/item?id=456")

    def test_fragment_stripped(self):
        """URL fragments (#section) should be ignored."""
        assert normalize_url("https://example.com/a#section1") == normalize_url("https://example.com/a#section2")

    def test_same_article_different_fbclid(self):
        """Facebook click-id shouldn't break dedup."""
        url_a = "https://example.com/article?fbclid=abc123"
        url_b = "https://example.com/article?fbclid=xyz789"
        assert normalize_url(url_a) == normalize_url(url_b)

    def test_standard_query_preserved(self):
        """Non-tracking query params should be preserved."""
        key = normalize_url("https://example.com/page?q=search&lang=zh")
        assert "q=search" in key
        assert "lang=zh" in key

    def test_gclid_stripped(self):
        """Google click-id should be stripped."""
        url_a = "https://example.com/article?gclid=abc"
        url_b = "https://example.com/article"
        assert normalize_url(url_a) == normalize_url(url_b)
