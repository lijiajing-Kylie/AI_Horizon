import asyncio

import httpx

from datetime import datetime, timezone

from src.content_extractor import (
    EXTRACTOR_VERSION,
    clean_article_content,
    extract_full_content,
    sanitize_article_html,
    _strip_boilerplate_containers,
    _strip_cta_sentences,
)
from src.models import ContentItem


# ── clean_article_content ────────────────────────────────────────────────


def test_clean_article_content_strips_noise_and_duplicate_title():
    raw = (
        "My Big Title\n"
        "\n"
        "This is the first real paragraph of the article with enough content.\n"
        "\n"
        "阅读原文 · example.com\n"
        "\n"
        "This is the second paragraph, continuing on with more text.\n"
        "\n"
        "\n"
        "Read more\n"
        "\n"
        "\n"
        "Continue reading\n"
        "\n"
        "\n"
        "The post My Big Title appeared first on ExampleSite.\n"
        "\n"
        "来源: 华尔街日报\n"
        "\n"
        "— ExampleSite"
    )

    cleaned = clean_article_content(raw, title="My Big Title")

    assert "My Big Title" not in cleaned
    assert "阅读原文" not in cleaned
    assert "Read more" not in cleaned
    assert "Continue reading" not in cleaned
    assert "appeared first on" not in cleaned
    assert "来源" not in cleaned
    assert "ExampleSite" not in cleaned
    assert "\n\n\n" not in cleaned
    assert "first real paragraph" in cleaned
    assert "second paragraph" in cleaned


def test_clean_article_content_empty_input():
    assert clean_article_content(None) == ""
    assert clean_article_content("   ") == ""


def test_clean_article_content_never_mutates_input():
    raw = "Title\n\nRead more"
    original = raw
    clean_article_content(raw, title="Title")
    assert raw == original


def test_clean_article_content_plain_text_passthrough():
    assert clean_article_content("Just plain text, no noise.") == "Just plain text, no noise."


# ── image extraction (via extract_full_content) ──────────────────────────


def _article_html(*, og_image: str | None = None) -> str:
    og_tag = f'<meta property="og:image" content="{og_image}">' if og_image else ""
    body = "A" * 250  # padding so trafilatura's length heuristics accept it
    return f"""<html><head><title>Test Article</title>{og_tag}</head>
<body>
<nav><img src="https://example.com/logo-nav.png" alt="Site Logo"></nav>
<article>
<h1>Test Article</h1>
<p>Intro paragraph with enough real content to pass extraction heuristics. {body}</p>
<figure>
<img src="https://example.com/chart1.png" alt="Chart showing growth">
<figcaption>Figure 1: Growth chart</figcaption>
</figure>
<p>Second paragraph with more real content to satisfy the length filters used. {body}</p>
</article>
<footer><img src="https://example.com/footer-ad.png" alt="ad"></footer>
</body></html>"""


def _client_for_html(html: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_extract_full_content_returns_images_and_cover_from_og_tag():
    html = _article_html(og_image="https://cdn.example.com/cover.jpg")
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/article", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.cover_image == "https://cdn.example.com/cover.jpg"
    urls = [img["url"] for img in result.images]
    assert "https://example.com/chart1.png" in urls
    # Boilerplate images (nav logo, footer ad) must not leak into the list.
    assert "https://example.com/logo-nav.png" not in urls
    assert "https://example.com/footer-ad.png" not in urls

    chart = next(img for img in result.images if img["url"] == "https://example.com/chart1.png")
    assert chart["caption"] == "Figure 1: Growth chart"
    assert chart["alt"] == "Chart showing growth"
    assert chart["source"] == "example.com"

    # clean_content derivation must never include raw <img> markup.
    assert "<img" not in result.text


def test_extract_full_content_reports_http_status_final_url_and_extractor_version():
    html = _article_html(og_image="https://cdn.example.com/cover.jpg")
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/article", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.http_status == 200
    assert result.final_url == "https://example.com/article"
    assert result.extractor_version == EXTRACTOR_VERSION


def test_extract_full_content_falls_back_to_first_non_icon_image_for_cover():
    html = _article_html(og_image=None)
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/article", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.cover_image == "https://example.com/chart1.png"


def test_extract_full_content_no_images_returns_empty_list():
    body = "A" * 250
    html = f"""<html><body><article><h1>T</h1>
<p>Paragraph with enough real content to pass extraction heuristics for the test. {body}</p>
<p>Second paragraph with more real content to satisfy the length filters used here. {body}</p>
</article></body></html>"""
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/no-images", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.cover_image is None
    assert result.images == []


# ── structured HTML extraction (raw_html / display_html) ─────────────────


def test_extract_full_content_preserves_heading_paragraph_and_figure_position():
    html = _article_html(og_image="https://cdn.example.com/cover.jpg")
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/article", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.raw_html is not None
    assert result.display_html is not None

    # h1 in the source shifts to h2 (page already renders the item title as h1).
    assert "<h2>Test Article</h2>" in result.display_html
    assert "Intro paragraph with enough real content" in result.display_html

    # The figure/figcaption must land *between* the two paragraphs, matching
    # source document order — not appended after all the text.
    intro_pos = result.display_html.index("Intro paragraph")
    figure_pos = result.display_html.index("<figure>")
    second_pos = result.display_html.index("Second paragraph")
    assert intro_pos < figure_pos < second_pos

    assert '<img src="https://example.com/chart1.png" alt="Chart showing growth">' in result.display_html
    assert "<figcaption>Figure 1: Growth chart</figcaption>" in result.display_html

    # Boilerplate images (nav logo, footer ad) must not leak into the HTML either.
    assert "logo-nav" not in result.display_html
    assert "footer-ad" not in result.display_html


def _rich_article_html() -> str:
    body = "A" * 250
    return f"""<html><head><title>Rich Article</title></head>
<body><article>
<h1>Rich Article</h1>
<p>Intro paragraph with <strong>bold text</strong> and a
<a href="https://example.com/ref">reference link</a> plus enough padding. {body}</p>
<blockquote>An important quoted remark from the article, padded for length. {body}</blockquote>
<ul><li>First point with enough detail to count as real content here today.</li>
<li>Second point with enough detail to count as real content here today.</li></ul>
<p>Closing paragraph with a dangerous link
<a href="javascript:alert(1)">click me</a> that must not become a live link. {body}</p>
</article></body></html>"""


def test_extract_full_content_preserves_formatting_links_and_lists():
    html = _rich_article_html()
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/rich", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.display_html is not None

    assert "<strong>bold text</strong>" in result.display_html
    assert "reference link" in result.display_html
    assert "<blockquote>" in result.display_html and "important quoted remark" in result.display_html
    assert "<ul>" in result.display_html and "<li>" in result.display_html
    assert "First point" in result.display_html and "Second point" in result.display_html

    # Body-internal links are never clickable — only their text survives.
    # This holds regardless of scheme (http(s) or javascript:).
    assert "<a " not in result.display_html and "<a>" not in result.display_html
    assert "javascript:" not in result.display_html
    assert "click me" in result.display_html


# ── sanitize_article_html ─────────────────────────────────────────────────


def test_sanitize_article_html_strips_script_tags_and_content():
    dirty = "<p>safe text</p><script>alert('xss')</script>"
    clean = sanitize_article_html(dirty)
    assert "<script" not in clean
    assert "alert" not in clean
    assert "<p>safe text</p>" in clean


def test_sanitize_article_html_strips_event_handlers():
    dirty = '<p onclick="evil()">hi</p><img src="x.png" onerror="alert(1)">'
    clean = sanitize_article_html(dirty)
    assert "onclick" not in clean
    assert "onerror" not in clean
    assert "<img" in clean and 'src="x.png"' in clean


def test_sanitize_article_html_strips_javascript_scheme_links():
    dirty = '<a href="javascript:alert(1)">bad</a>'
    clean = sanitize_article_html(dirty)
    assert "javascript:" not in clean
    assert "bad" in clean  # text survives, just not as a live link


def test_sanitize_article_html_strips_disallowed_tags_but_keeps_text():
    dirty = '<div class="wrapper"><span style="color:red">plain text</span></div>'
    clean = sanitize_article_html(dirty)
    assert "<div" not in clean
    assert "<span" not in clean
    assert "style=" not in clean
    assert "plain text" in clean


def test_sanitize_article_html_keeps_whitelisted_structure():
    dirty = (
        "<h2>Heading</h2><p>Para with <strong>bold</strong> and "
        '<a href="https://example.com/x">link</a>.</p>'
        '<figure><img src="https://example.com/a.jpg" alt="alt text">'
        "<figcaption>caption</figcaption></figure>"
        "<blockquote>quote</blockquote><ul><li>item</li></ul>"
    )
    clean = sanitize_article_html(dirty)
    for expected in (
        "<h2>Heading</h2>",
        "<strong>bold</strong>",
        'href="https://example.com/x"',
        'src="https://example.com/a.jpg"',
        "<figcaption>caption</figcaption>",
        "<blockquote>quote</blockquote>",
        "<ul><li>item</li></ul>",
    ):
        assert expected in clean


def test_sanitize_article_html_empty_input():
    assert sanitize_article_html(None) == ""
    assert sanitize_article_html("") == ""
    assert sanitize_article_html("   ") == ""


# ── boilerplate container removal ─────────────────────────────────────────


def test_strip_boilerplate_containers_removes_aside_and_footer():
    html = (
        "<article><p>Real content paragraph.</p>"
        '<aside class="newsletter-signup"><p>Subscribe now!</p></aside>'
        "<footer><p>Site footer text.</p></footer>"
        "</article>"
    )
    cleaned = _strip_boilerplate_containers(html)
    assert "Real content paragraph" in cleaned
    assert "Subscribe now" not in cleaned
    assert "Site footer text" not in cleaned


def test_strip_boilerplate_containers_removes_class_and_id_keyword_matches():
    html = (
        "<div><p>Real content.</p>"
        '<div class="join-us-cta"><p>Careers: apply today.</p></div>'
        '<div id="promo-banner"><p>Limited offer!</p></div>'
        "</div>"
    )
    cleaned = _strip_boilerplate_containers(html)
    assert "Real content" in cleaned
    assert "Careers: apply today" not in cleaned
    assert "Limited offer" not in cleaned


def test_strip_boilerplate_containers_no_false_positive_on_substring_matches():
    # "header" and "lazy-load" both contain the "ad"/"load" substrings a
    # naive match would trip on — token-boundary matching must not flag them.
    html = (
        '<div class="page-header"><p>Real header content, e.g. a byline.</p></div>'
        '<div class="lazy-load"><p>Lazily loaded content.</p></div>'
    )
    cleaned = _strip_boilerplate_containers(html)
    assert "Real header content" in cleaned
    assert "Lazily loaded content" in cleaned


# ── sentence-level CTA stripping ───────────────────────────────────────────


def test_strip_cta_sentences_removes_only_the_cta_sentence():
    text = "This is a real informative sentence about the news. Subscribe to our newsletter today!"
    cleaned, changed = _strip_cta_sentences(text)
    assert changed is True
    assert "real informative sentence" in cleaned
    assert "Subscribe" not in cleaned


def test_strip_cta_sentences_no_cta_leaves_text_unchanged():
    text = "This is a normal sentence with no CTA content at all."
    cleaned, changed = _strip_cta_sentences(text)
    assert changed is False
    assert cleaned == text


# ── clean_article_content: sentence-level CTA cleaning + over-clean guard ─


def test_clean_article_content_single_paragraph_strips_trailing_cta_sentence():
    # A news item whose entire article is one paragraph — the naive "drop
    # the whole paragraph if it contains a CTA keyword" approach would wipe
    # out the entire article here. Only the CTA sentence should go.
    raw = (
        "This single-paragraph article covers a major product launch event "
        "with plenty of substantive detail about the new features, pricing, "
        "and availability that readers actually came here for, along with "
        "commentary from analysts and early customers who tried the product "
        "ahead of the public release and shared their first impressions. "
        "Subscribe to our newsletter for more updates."
    )

    cleaned = clean_article_content(raw)

    assert "product launch event" in cleaned
    assert "pricing, and availability" in cleaned
    assert "early customers" in cleaned
    assert "Subscribe to our newsletter" not in cleaned


def test_clean_article_content_hiring_cta_sentence_removed_keeps_rest():
    raw = (
        "The company reported strong quarterly earnings driven by growth in "
        "its core cloud division, beating analyst expectations across the board. "
        "We're hiring! Join our team and help us build the future. "
        "Executives also announced a new investment in AI infrastructure for next year."
    )

    cleaned = clean_article_content(raw)

    assert "strong quarterly earnings" in cleaned
    assert "AI infrastructure" in cleaned
    assert "We're hiring" not in cleaned
    assert "Join our team" not in cleaned


def test_clean_article_content_overclean_guard_falls_back_to_raw():
    real_content = "Real short update: prices rose today."
    cta_noise = (
        " Subscribe now for more! Sign up today! Join our team! "
        "We're hiring engineers! Apply here!"
    ) * 5
    raw = real_content + cta_noise

    cleaned = clean_article_content(raw)

    # Sentence-level CTA stripping alone would gut this down to well under
    # 200 chars / 30% of the original — the over-clean guard should keep
    # the (title-deduped) original text instead of shipping the gutted result.
    assert real_content in cleaned
    assert "Subscribe now" in cleaned


# ── extract_full_content: end-to-end container + link-text-only behavior ──


def _article_html_with_boilerplate_containers() -> str:
    body = "A" * 250
    return f"""<html><body><article>
<h1>Container Test</h1>
<p>Real paragraph with substantive content about the topic at hand today. {body}</p>
<aside class="newsletter-signup"><p>Subscribe to our newsletter for daily updates on
everything happening in the industry right now and beyond, today. {body}</p></aside>
<footer class="careers-cta"><p>We're hiring! Join our team, apply today for open
engineering and product roles across the company worldwide. {body}</p></footer>
</article></body></html>"""


def test_extract_full_content_strips_ad_and_hiring_containers():
    html = _article_html_with_boilerplate_containers()
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/container-test", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert "Real paragraph with substantive content" in result.text
    assert "Subscribe to our newsletter" not in result.text
    assert "We're hiring" not in result.text
    assert result.display_html is not None
    assert "Subscribe to our newsletter" not in result.display_html
    assert "We're hiring" not in result.display_html


def test_extract_full_content_product_and_paper_links_become_text_only():
    body = "A" * 250
    html = f"""<html><body><article><h1>T</h1>
<p>We benchmarked against <a href="https://arxiv.org/abs/2401.00001">the original paper</a>
and the <a href="https://example.com/product">product page</a> for comparison. {body} {body}</p>
</article></body></html>"""
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/links", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert result.display_html is not None
    assert "the original paper" in result.display_html
    assert "product page" in result.display_html
    assert "<a " not in result.display_html
    assert "arxiv.org" not in result.display_html


def test_extract_full_content_structured_html_overclean_falls_back_to_none():
    real = "Real short update: prices rose today."
    cta = (
        " Subscribe now for more! Sign up today! Join our team! "
        "We're hiring engineers! Apply here!"
    ) * 6
    html = f"<html><body><article><h1>T</h1><p>{real}{cta}</p></article></body></html>"
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/overclean", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    # Structured HTML bails out to (None, None) when CTA-sentence cleaning
    # would gut the block — callers fall back to the plain-text field.
    assert result.display_html is None
    assert real in result.text


# ── Smart skip: high-quality RSS content ─────────────────────────────────


def _make_item(*, rss_quality: str = "low", content: str = "") -> ContentItem:
    """Create a minimal ContentItem for extraction tests."""
    return ContentItem(
        id="test:rss:123",
        source_type="rss",
        title="Test Item",
        url="https://example.com/article",
        content=content,
        rss_content_quality=rss_quality,
        rss_summary=content,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        metadata={"extraction_mode": "http"},
    )


def test_extract_full_content_skips_when_rss_high_quality() -> None:
    """When rss_content_quality='high', extraction returns None without HTTP."""
    html = _article_html()
    client = _client_for_html(html)
    item = _make_item(rss_quality="high", content="X" * 1500)

    async def run():
        return await extract_full_content(
            "https://example.com/article", client, item=item
        )

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is None


def test_extract_full_content_still_runs_when_rss_low_quality() -> None:
    """When rss_content_quality='low', extraction proceeds normally."""
    html = _article_html()
    client = _client_for_html(html)
    item = _make_item(rss_quality="low", content="short")

    async def run():
        return await extract_full_content(
            "https://example.com/article", client, item=item
        )

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert len(result.text) >= 200


def test_extract_full_content_skips_when_rss_quality_none() -> None:
    """When rss_content_quality='none', the item has no usable RSS — extract anyway."""
    html = _article_html()
    client = _client_for_html(html)
    item = _make_item(rss_quality="none", content="")

    async def run():
        return await extract_full_content(
            "https://example.com/article", client, item=item
        )

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert len(result.text) >= 200


def test_extract_full_content_no_item_still_works() -> None:
    """Calling without item (backward compat) works as before."""
    html = _article_html()
    client = _client_for_html(html)

    async def run():
        return await extract_full_content("https://example.com/article", client)

    result = asyncio.run(run())
    asyncio.run(client.aclose())

    assert result is not None
    assert len(result.text) >= 200
