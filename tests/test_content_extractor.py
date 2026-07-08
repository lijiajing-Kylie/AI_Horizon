import asyncio

import httpx

from src.content_extractor import (
    clean_article_content,
    extract_full_content,
    sanitize_article_html,
)


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
    assert '<a href="https://example.com/ref"' in result.display_html
    assert "reference link" in result.display_html
    assert "<blockquote>" in result.display_html and "important quoted remark" in result.display_html
    assert "<ul>" in result.display_html and "<li>" in result.display_html
    assert "First point" in result.display_html and "Second point" in result.display_html

    # javascript: link must never survive as a clickable <a> — only as text.
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
