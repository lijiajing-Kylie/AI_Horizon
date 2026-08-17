"""Tests for WeChat article ``display_html`` generation.

Covers the current pipeline ``#js_content → fix_wechat_images →
truncate_wxmp_footer → nh3 sanitize``: ``section``/``div`` block boundaries
are kept (no more paragraph-merge), body images and tables survive, the tail
CTA/QR footer is truncated, author attribution lines are NOT truncated, and
inline ``style`` never leaks through.
"""

from __future__ import annotations

from pathlib import Path

from src.scrapers.wxmp import sanitize_wxmp_display_html, truncate_wxmp_footer


def test_many_sections_keep_block_boundaries() -> None:
    """大量 <section> 的文章清洗后每个段落仍独立成块，不会粘成一坨。"""
    html = (
        '<div id="js_content">'
        + "".join(f"<section><p>这是第{i}段正文。</p></section>" for i in range(40))
        + "</div>"
    )
    display = sanitize_wxmp_display_html(html)
    assert display.count("<section>") >= 40
    assert display.count("<p>") >= 40
    assert "第1段正文。第2段正文。" not in display


def test_section_and_div_preserved() -> None:
    """<section>/<div> 作为块级容器保留，不再被转成 <p> 或剥掉。"""
    display = sanitize_wxmp_display_html(
        '<div class="rich_media_content"><section><p>内容</p></section></div>'
    )
    assert "<section>" in display
    assert "<div>" in display


def test_span_stripped_text_kept() -> None:
    """<span> 标签被剥掉但文字内容保留。"""
    display = sanitize_wxmp_display_html(
        "<p>正文<span>（括号内容）</span>继续</p>"
    )
    assert "<span" not in display
    assert "（括号内容）" in display
    assert "正文" in display and "继续" in display


def test_data_src_becomes_src() -> None:
    """微信懒加载 data-src → src，并替换为后端图片代理地址。"""
    display = sanitize_wxmp_display_html(
        '<p><img data-src="https://mmbiz.qpic.cn/x" alt="配图"></p>'
    )
    assert "/api/img-proxy?url=" in display
    assert "https%3A%2F%2Fmmbiz.qpic.cn%2Fx" in display  # 原 URL 编码在代理 query 里
    assert "data-src" not in display


def test_body_image_kept_with_attrs() -> None:
    """正文普通图片保留，且至少保留 src/alt/width/height。"""
    display = sanitize_wxmp_display_html(
        '<p><img data-src="https://mmbiz.qpic.cn/y" width="400" height="300" alt="示意图"></p>'
    )
    assert "mmbiz.qpic.cn" in display  # 域名在代理 query 中保留
    assert 'width="400"' in display
    assert 'height="300"' in display
    assert 'alt="示意图"' in display
    assert display.count("/api/img-proxy?url=") == 1


def test_non_wechat_image_src_not_proxied() -> None:
    """非微信 CDN 的图片不代理，保持原 URL。"""
    display = sanitize_wxmp_display_html(
        '<p><img src="https://cdn.example.com/photo.png" alt="普通图"></p>'
    )
    assert 'src="https://cdn.example.com/photo.png"' in display
    assert "/api/img-proxy" not in display


def test_table_preserved() -> None:
    """数据表格正常保留（含 thead/tbody/th/td）。"""
    display = sanitize_wxmp_display_html(
        "<table><thead><tr><th>列A</th><th>列B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    assert "<table>" in display
    assert "<thead>" in display
    assert "<tbody>" in display
    assert "<th>" in display
    assert "<td>" in display


def test_qr_cta_at_tail_truncated() -> None:
    """“扫描二维码”在文章尾部时，命中 marker 的块及其后内容被截断。"""
    html = (
        "<p>正文第一段。</p><p>正文第二段。</p>"
        "<p>扫描二维码，获取全文报告</p>"
        "<p>更多信息请访问官网</p>"
    )
    display = sanitize_wxmp_display_html(html)
    assert "正文第一段。" in display
    assert "扫描二维码" not in display
    assert "更多信息请访问官网" not in display


def test_qr_image_adjacent_to_cta_removed() -> None:
    """紧邻 CTA 前的单张二维码图片会一并删除，前面的署名保留。"""
    html = (
        "<p>顾问：某某</p>"
        "<p>研究团队：某某团队</p>"
        "<p>联合出品：某某机构</p>"
        '<p><img src="https://mmbiz.qpic.cn/qr"></p>'
        "<p>扫描二维码，获全文报告</p>"
    )
    display = sanitize_wxmp_display_html(html)
    assert "顾问：某某" in display
    assert "研究团队" in display
    assert "联合出品" in display
    assert "扫描二维码" not in display
    assert "mmbiz.qpic.cn/qr" not in display


def test_recommended_and_like_truncated() -> None:
    """“推荐阅读 / 点个在看”等尾部运营内容被删除。"""
    html = (
        "<p>真正的正文结尾。</p>"
        "<p>推荐阅读</p><p>腾讯研究院：某篇文章标题</p>"
        "<p>👇 点个 “在看” 分享洞见</p>"
    )
    display = sanitize_wxmp_display_html(html)
    assert "真正的正文结尾。" in display
    assert "推荐阅读" not in display
    assert "腾讯研究院" not in display
    assert "在看" not in display


def test_author_attribution_not_truncated() -> None:
    """顾问 / 研究团队 / 联合出品 默认当作正文保留，不被误删。"""
    html = (
        "<p>顾问：张某某</p>"
        "<p>研究团队：某某实验室</p>"
        "<p>联合出品：某某大学</p>"
        "<p>这是报告正文内容。</p>"
    )
    display = sanitize_wxmp_display_html(html)
    assert "顾问：张某某" in display
    assert "研究团队" in display
    assert "联合出品" in display
    assert "这是报告正文内容。" in display


def test_middle_mention_not_truncated() -> None:
    """正文中段偶然出现“推荐阅读”不触发截断（只在尾部 30 块内扫描）。"""
    body = "".join(f"<p>这是正文第{i}段。</p>" for i in range(1, 31))
    mid = "<p>正文中段提到“推荐阅读”更多文章，但不应截断。</p>"
    tail = "".join(f"<p>这是尾部第{i}段。</p>" for i in range(1, 41))
    display = sanitize_wxmp_display_html(body + mid + tail)
    assert "正文中段提到“推荐阅读”更多文章" in display
    assert "这是尾部第40段。" in display


def test_no_footer_marker_leaves_content_untouched() -> None:
    """没有运营内容时不做任何尾部截断。"""
    html = "<p>第一段正文。</p><p>第二段正文。</p><p>结尾。</p>"
    display = sanitize_wxmp_display_html(html)
    assert "第一段正文。" in display
    assert "第二段正文。" in display
    assert "结尾。" in display


def test_inline_style_not_leaked() -> None:
    """inline style 不会透传。"""
    display = sanitize_wxmp_display_html(
        '<p style="color:red">正文</p>'
        '<div style="margin:0">内容</div>'
    )
    assert "style=" not in display
    assert "color:red" not in display
    assert "正文" in display


def test_footer_across_nested_blocks_truncated() -> None:
    """footer 横跨嵌套块与顶层块时，从命中点起整体截断、前面的正文保留。"""
    html = (
        '<div id="js_content">'
        "<section><section><p>正文在前。</p><section>推荐阅读</section></section></section>"
        "<p>推荐文章一</p><p>点个在看</p>"
        "</div>"
    )
    display = sanitize_wxmp_display_html(html)
    assert "正文在前。" in display
    assert "推荐阅读" not in display
    assert "推荐文章一" not in display
    assert "点个在看" not in display


def test_ui_noise_outside_js_content_excluded() -> None:
    """#js_content 之外的微信 H5 UI 噪音（扫一扫/赞/留言 等）不进 display_html。"""
    html = (
        '<div id="js_content"><p>真正的正文。</p></div>'
        '<div><p>微信扫一扫可打开此内容</p></div>'
        '<div><p>赞</p><p>在看</p><p>分享</p><p>留言</p></div>'
    )
    display = sanitize_wxmp_display_html(html)
    assert "真正的正文。" in display
    for noise in ("微信扫一扫", "使用完整服务", "赞", "留言"):
        assert noise not in display


def test_golden_fixture_cleaned_display_html() -> None:
    """真实微信文章 fixture：正文结构/图片保留、footer 与 UI 噪音被清干净。"""
    fixture = Path(__file__).parent / "fixtures" / "wx_article_tencent_research.html"
    raw = fixture.read_text(encoding="utf-8")
    display = sanitize_wxmp_display_html(raw)
    # 块级边界与图片保留
    assert "<section>" in display
    assert "mmbiz.qpic.cn" in display
    # footer 运营内容与 #js_content 外 UI 噪音清掉
    for noise in (
        "推荐阅读", "腾讯研究院：", "分享洞见", "点个在看",
        "微信扫一扫", "使用完整服务", "预览时标签不可点",
    ):
        assert noise not in display
    # 正文标记保留
    assert "波士顿动力" in display


def test_truncate_wxmp_footer_returns_flag() -> None:
    """truncate_wxmp_footer 返回是否发生截断。"""
    from bs4 import BeautifulSoup

    with_footer = BeautifulSoup(
        "<p>正文。</p><p>推荐阅读</p>", "html.parser"
    )
    assert truncate_wxmp_footer(with_footer) is True
    assert "正文。" in str(with_footer)

    clean = BeautifulSoup("<p>正文。</p><p>结尾。</p>", "html.parser")
    assert truncate_wxmp_footer(clean) is False
    assert "结尾。" in str(clean)
