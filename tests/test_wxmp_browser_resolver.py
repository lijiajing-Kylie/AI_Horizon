"""Pure-function tests for the wxmp footer-QR PDF resolver.

Covers the QR localisation logic (``_footer_qr_candidate_urls``) and the
preview-page PDF extraction (``_extract_pdf_from_url_query``).  These are
DOM/pure functions — no pyzbar, no browser, no network.

Real-world reference structure (FDE article, stored raw_html): the footer
QR is a bare ``<img>`` inside a single-image ``<section>`` immediately
preceding a ``<section>`` whose text is "扫描二维码，获完整报告".
"""

from src.reports.wxmp_browser_resolver import (
    WxMpBrowserResolver,
    _footer_qr_candidate_urls,
    _qr_cta_marker_hit,
)

# ── _qr_cta_marker_hit ────────────────────────────────────────────────


def test_cta_marker_hit_report():
    assert _qr_cta_marker_hit("扫描二维码，获完整报告") == "扫描二维码"


def test_cta_marker_hit_secondary():
    assert _qr_cta_marker_hit("长按识别二维码，关注公众号") == "长按识别二维码"


def test_cta_marker_hit_none_for_body_text():
    assert _qr_cta_marker_hit("这是正文段落，没有运营提示") is None


def test_cta_marker_hit_empty():
    assert _qr_cta_marker_hit("") is None


# ── _footer_qr_candidate_urls: CTA-anchor main path ───────────────────


def test_real_wxmp_footer_structure_img_before_cta():
    """真实 FDE 结构：单图 section 在前、CTA 文案 section 在后（相邻兄弟）。"""
    html = """<div id="js_content">
      <p>正文第一段……</p>
      <section style="text-align: center;margin-top: 16px;">
        <img src="https://mmbiz.qpic.cn/mmbiz_png/sm1UZBHjpbiaN3UJu8/640?wx_fmt=png&amp;from=appmsg" style="width: 199px;height: auto !important;"/>
      </section>
      <section style="margin: 0px 8px;text-align: center;">
        <span style="font-size: 14px;color: #888888;">扫描二维码，获完整报告</span>
      </section>
      <p>推荐阅读……</p>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    assert len(urls) == 1
    assert urls[0].startswith("https://mmbiz.qpic.cn/mmbiz_png/sm1UZBHjpbiaN3UJu8")


def test_cta_after_img_is_next_sibling():
    """变体：CTA 文案在图片前面 → 图片是 CTA 的后一个兄弟。"""
    html = """<div id="js_content">
      <p>正文</p>
      <section><span style="color:#888;">长按识别二维码，获取全文报告</span></section>
      <section style="text-align:center;"><img src="https://mmbiz.qpic.cn/mmbiz_png/variantA/640?wx_fmt=png"/></section>
      <p>结尾</p>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    assert urls == ["https://mmbiz.qpic.cn/mmbiz_png/variantA/640?wx_fmt=png"]


def test_qr_wrapped_in_anchor():
    """变体：二维码图片包在 <a href> 里（链接形态）。"""
    html = """<div id="js_content">
      <p>正文</p>
      <section style="text-align:center;"><a href="#"><img src="https://mmbiz.qpic.cn/mmbiz_png/inAnchor/640?wx_fmt=png"/></a></section>
      <section><span>扫码下载完整报告</span></section>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    assert urls == ["https://mmbiz.qpic.cn/mmbiz_png/inAnchor/640?wx_fmt=png"]


def test_data_uri_placeholder_not_selected_as_cta_img():
    """CTA 相邻兄弟里的 data: 占位图不算数 → 落到兜底。"""
    html = """<div id="js_content">
      <section><span>扫描二维码获取全文</span></section>
      <section><img src="data:image/gif;base64,AAAA"/></section>
      <img src="https://example.com/square.png" style="width:200px;height:200px;"/>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    # 主路径忽略 data: 图；兜底返回 http 正方形图
    assert "data:image" not in "".join(urls)
    assert "https://example.com/square.png" in urls


# ── _footer_qr_candidate_urls: fallback (no CTA anchor) ───────────────


def test_fallback_square_images_filters_data_uri():
    html = """<div id="js_content">
      <img src="https://example.com/a.png" style="width:300px;height:300px;"/>
      <img src="data:image/gif;base64,AAAA"/>
      <img src="https://example.com/b.png" style="width:120px;height:120px;"/>
      <img src="https://example.com/c.png" style="width:100px;height:100px;"/>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    assert "data:image" not in "".join(urls)
    assert set(urls) == {
        "https://example.com/a.png",
        "https://example.com/b.png",
        "https://example.com/c.png",
    }


def test_fallback_oblong_image_excluded():
    """兜底时宽高比过大（非正方形）的图被排除。"""
    html = """<div id="js_content">
      <img src="https://example.com/wide.png" style="width:600px;height:100px;"/>
      <img src="https://example.com/square.png" style="width:150px;height:150px;"/>
    </div>"""
    urls = _footer_qr_candidate_urls(html)
    assert "https://example.com/wide.png" not in urls
    assert "https://example.com/square.png" in urls


def test_fallback_no_imgs_returns_empty():
    html = '<div id="js_content"><p>纯文字，没有图片</p></div>'
    assert _footer_qr_candidate_urls(html) == []


def test_candidate_urls_requires_js_content_when_absent():
    """无 #js_content 时用整个 soup 兜底（与生产路径一致）。"""
    html = """<p>没有 js_content</p>
    <section><img src="https://example.com/x.png" style="width:100px;height:100px;"/></section>
    <section><span>扫码获取</span></section>"""
    urls = _footer_qr_candidate_urls(html)
    assert "https://example.com/x.png" in urls


# ── _extract_pdf_from_url_query ───────────────────────────────────────


def test_extract_pdf_from_clewm_view_url():
    """草料预览页 view.html?url=<pdf>：URL-encoded 的 pdf 藏在 url 参数里。"""
    url = ("https://preview-static.clewm.net/cli/view-doc/view.html"
           "?url=https%3A%2F%2Fncstatic.clewm.net%2Frsrc%2F2026%2F0805%2F16%2F"
           "bc3e3e642e3d4bb097fed75613d2b477.pdf&filename=FDE.pdf")
    assert WxMpBrowserResolver._extract_pdf_from_url_query(url) == (
        "https://ncstatic.clewm.net/rsrc/2026/0805/16/"
        "bc3e3e642e3d4bb097fed75613d2b477.pdf"
    )


def test_extract_pdf_from_plain_pdf_url():
    assert WxMpBrowserResolver._extract_pdf_from_url_query(
        "https://x.com/a/b/report.pdf"
    ) is None  # query 为空 → None


def test_extract_pdf_query_with_file_param():
    assert WxMpBrowserResolver._extract_pdf_from_url_query(
        "https://x.com/doc?file=/static/report.pdf&t=1"
    ) == "/static/report.pdf"


def test_extract_pdf_none_without_pdf_in_query():
    assert WxMpBrowserResolver._extract_pdf_from_url_query(
        "https://preview.example.com/view.html?url=https://a.com/page"
    ) is None
