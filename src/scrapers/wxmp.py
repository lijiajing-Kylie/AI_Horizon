"""WeChat MP scraper via the WeRead channel (weread.111965.xyz forwarding service).

Fetches WeChat Official Account articles through ``src.we_read`` — pure HTTP,
no Playwright, no external we-mp-rss service. Requires a valid WeRead login
token (see ``horizon-wxmp login``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from ..content_extractor import sanitize_article_html
from ..models import ContentItem, SourceType, WxMpConfig, WxMpSourceConfig
from ..storage.db import HorizonDB
from ..we_read import build_client_from_wxmp_config, ensure_login, with_empty_retry
from ..we_read.errors import WeReadAuthError, WeReadError
from .base import BaseScraper

logger = logging.getLogger(__name__)


def fix_wechat_images(html: str) -> str:
    """Fix WeChat article lazy-loaded images (``data-src`` → ``src``) and strip
    unnecessary attributes. Ported from we-mp-rss ``Web.fix_images`` (pure bs4)."""
    if not html or not html.strip():
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 - best-effort
        return html

    for img_tag in soup.find_all("img"):
        src_value = img_tag.get("src") or img_tag.get("data-src", "")
        if src_value.startswith("data:image") and src_value != img_tag.get("data-src", ""):
            src_value = img_tag.get("data-src", "")
        # 保留展示需要的最小属性集（alt/width/height 由 display_html 白名单透传）。
        style_value = img_tag.get("style", "")
        alt_value = img_tag.get("alt", "")
        width_value = img_tag.get("width", "")
        height_value = img_tag.get("height", "")
        img_tag.attrs = {}
        if src_value:
            img_tag["src"] = src_value
        if alt_value:
            img_tag["alt"] = alt_value
        if width_value:
            img_tag["width"] = width_value
        if height_value:
            img_tag["height"] = height_value
        if style_value:
            img_tag["style"] = style_value

    for tag_name in ("section", "p", "span"):
        for tag in soup.find_all(tag_name):
            style_value = tag.get("style", "")
            tag.attrs = {}
            if style_value:
                tag["style"] = style_value

    for element in soup.find_all(attrs={"style": True}):
        data_src = element.get("data-src", "")
        style = element.get("style", "")
        if data_src and "background" in style.lower() and "url(" not in style.lower():
            if style.endswith(";"):
                element["style"] = f'{style}background-image: url("{data_src}")'
            else:
                element["style"] = f'{style};background-image: url("{data_src}")'

    # str(soup) (not prettify) keeps the original compact structure.
    return str(soup)


# ── WeChat 正文 display_html 清洗 ────────────────────────────────────────
# 微信正文大量用 <section>/<div> 作为块级容器，而默认 nh3 白名单不含它们：
# 直接清洗会把块级边界剥掉、相邻正文连成一片。这里给微信专用白名单 +
# 尾部运营内容截断，生成结构清晰、可安全渲染的 display_html。
# 职责边界：raw_html 保留原始 HTML，content_text 走纯文本清洗（见
# src/reports/sources/wxmp.py），这里只负责前端阅读展示的 display_html。

# 尾部运营 marker：只在文章尾部扫描命中，命中后从该块起截断。与纯文本路径
# （_WEIXIN_CONTENT_END_MARKERS）各自独立，避免过宽的 marker 影响 LLM 读到的正文。
_WXMP_FOOTER_MARKERS = [
    "扫描二维码",
    "长按识别二维码",
    "扫码获取",
    "关注公众号",
    "关注我们",
    "点个在看",
    '点个"在看"',
    "👇 点个",
    "点击阅读原文",
    "回复关键词",
    "后台回复",
    "推荐阅读",
    "相关阅读",
    "往期推荐",
    "更多精彩",
    "分享洞见",
    # 微信 H5 页底 UI 噪音（#js_content 内不可见按钮文本）。
    "预览时标签不可点",
    "微信扫一扫可打开此内容",
    "使用完整服务",
]

# 尾部扫描的块级节点上限：只检查文章最后 30 个块，避免正文中段偶然出现
# 运营词时被误截断。
_FOOTER_SCAN_BLOCKS = 30
# 用于尾部扫描的"内容块"标签：只收集不含块级后代的 leaf 块，跳过容器。
_FOOTER_BLOCK_TAGS = (
    "p", "div", "section", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "figure", "table",
)

# display_html 白名单：保留 section/div 块级边界，放行表格与图片展示属性。
# span 有意不放行（nh3 会剥标签但保留文字）；inline style 一律不放行，
# 表格边框/图片样式由前端 .article-html CSS 兜底。
WXMP_DISPLAY_TAGS = {
    "div", "section", "p",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "ul", "ol", "li",
    "strong", "b", "em", "i", "a",
    "figure", "img", "figcaption",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "br", "hr",
}
WXMP_DISPLAY_ATTRIBUTES = {
    # referrerpolicy="no-referrer"：mmbiz.qpic.cn 防盗链，非微信域名 Referer
    # 一律 403。前端跨域渲染时靠它让浏览器不发 Referer，图片才能显示。
    "img": {"src", "alt", "width", "height", "referrerpolicy"},
    "a": {"href"},
    "table": {"align", "border", "cellpadding", "cellspacing", "width"},
    "td": {"colspan", "rowspan", "align", "valign", "width"},
    "th": {"colspan", "rowspan", "align", "valign", "width"},
    "ol": {"start"},
}


def _leaf_footer_blocks(container) -> list:
    """收集不含块级后代的块级元素（真正承载内容的 leaf 块）。"""
    return [
        el for el in container.find_all(_FOOTER_BLOCK_TAGS)
        if el.find(_FOOTER_BLOCK_TAGS) is None
    ]


# 微信图片代理地址：新旧两代方案。weserv 公共图片代理是现役方案——微信 CDN
# （mmbiz.qpic.cn）防盗链，且自建 /api/img-proxy 依赖部署机能直连微信 CDN
# （本机 Clash fake-ip + 境外出口会被直接重置，实测不可用）；weserv 前端
# 直链、不依赖后端存活（WeWe RSS 等微信 RSS 项目的通行做法）。LEGACY 前缀
# 仅用于存量 display_html 回填识别（见 HorizonDB.rewrite_wechat_img_proxy）；
# VPS 图片本地化落地后再替换为本地地址。
WESERV_IMG_PROXY_BASE = "https://images.weserv.nl/?url="
LEGACY_IMG_PROXY_PREFIX = "/api/img-proxy?url="


def _proxy_wechat_img_src(src: str) -> str:
    """把 mmbiz.qpic.cn 图片 URL 替换为 weserv 公共图片代理地址。

    微信 CDN 防盗链导致前端直链加载失败；自建后端代理又依赖部署机网络
    （代理工具/境外出口都会被微信 CDN 重置）。非微信 CDN 图片不代理，保持原样。
    """
    if not src.startswith(("http://", "https://")):
        return src
    host = (urlparse(src).hostname or "").lower()
    if host != "mmbiz.qpic.cn":
        return src
    return WESERV_IMG_PROXY_BASE + quote(src, safe="")


def _drop_leading_qr_image(blk) -> None:
    """若 blk 前一个相邻兄弟只含单张图片（无文字），删除它——常用来去掉
    尾部 CTA 文案前紧跟的二维码图片。"""
    prev = blk.find_previous_sibling()
    if prev is None:
        return
    if prev.name == "img":
        prev.decompose()
        return
    if prev.get_text("", strip=True):
        return
    if len(prev.find_all("img")) == 1:
        prev.decompose()


def _remove_block_and_following(blk, container) -> None:
    """删除 blk 及其后所有内容（可跨多个顶层块）；blk 之前的内容保留。

    逐层向上：每层删当前节点的后续兄弟，并把已空的祖先容器一起 decompose；
    一旦某层父容器里还有 blk 之前的正文，保留该容器，但仍继续向上删除所有
    更高层容器的后续兄弟（footer 往往横跨多个顶层块），直到 container。
    """
    node = blk
    while node is not None and node.parent is not None:
        parent = node.parent
        for later in list(node.find_next_siblings()):
            later.decompose()
        node.decompose()
        if parent is container or parent is None:
            break
        for later in list(parent.find_next_siblings()):
            later.decompose()
        if parent.get_text("", strip=True) or parent.find("img") or parent.find("br"):
            # parent 内 blk 前还有正文 → 保留 parent，只清更外层兄弟。
            ancestor = parent.parent
            while ancestor is not None and ancestor is not container:
                for later in list(ancestor.find_next_siblings()):
                    later.decompose()
                ancestor = ancestor.parent
            break
        node = parent  # parent 已空 → 继续向上 decompose


def truncate_wxmp_footer(container) -> bool:
    """截断文章尾部的运营内容，就地修改 ``container``。

    只从最后 ``_FOOTER_SCAN_BLOCKS`` 个 leaf 块里从前向后找第一个命中
    ``_WXMP_FOOTER_MARKERS`` 的块：命中后先删其前一个相邻单图兄弟（二维码），
    再删该块及其后所有内容。返回是否发生了截断；无运营内容则完全不动。
    """
    tail = _leaf_footer_blocks(container)[-_FOOTER_SCAN_BLOCKS:]
    for blk in tail:
        text = blk.get_text(" ", strip=True)
        if text and any(m in text for m in _WXMP_FOOTER_MARKERS):
            _drop_leading_qr_image(blk)
            _remove_block_and_following(blk, container)
            return True
    return False


def sanitize_wxmp_display_html(raw_html: Optional[str]) -> str:
    """把微信正文原始 HTML 清洗为可安全渲染的 display_html（详情页用）。

    链路：#js_content 原始 HTML → fix_wechat_images（data-src→src）
    → truncate_wxmp_footer（尾部运营截断）→ nh3 白名单消毒。

    保留 ``<section>/<div>`` 块级边界、正文图片与表格；只截断尾部明确的
    运营内容（扫码/关注/推荐阅读等），``顾问/研究团队/联合出品`` 等署名
    默认当作正文保留。图片与表格样式由前端 ``.article-html`` CSS 兜底。
    """
    if not raw_html or not raw_html.strip():
        return ""
    html = fix_wechat_images(raw_html)
    soup = BeautifulSoup(html, "html.parser")
    # 只保留 #js_content 内的正文：#js_content 之外是微信 H5 的 UI 噪音
    #（微信扫一扫/使用完整服务/赞/听过 等按钮文本），不进 display_html。
    body = soup.select_one("#js_content") or soup
    truncate_wxmp_footer(body)
    # mmbiz.qpic.cn 防盗链：非微信域名 Referer 一律 403。图片走 weserv 公共
    # 代理（自建 /api/img-proxy 依赖部署机直连微信 CDN，实测在代理工具/
    # 境外出口下不可用）；referrerpolicy 同时保留作为非微信 CDN 图片的兜底。
    for img in body.find_all("img"):
        img["referrerpolicy"] = "no-referrer"
        src = img.get("src") or ""
        if src:
            img["src"] = _proxy_wechat_img_src(src)
    return sanitize_article_html(
        str(body),
        tags=WXMP_DISPLAY_TAGS,
        attributes=WXMP_DISPLAY_ATTRIBUTES,
    )


def _html_to_text(html: str) -> str:
    """Strip article HTML to plain text, keeping paragraph breaks.

    we-read returns the full WeChat article body as HTML (``section``/``p``/
    ``img``); the AI stages read plain text, so convert here once at scrape time
    rather than in the extractor.
    """
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n")]
    return "\n".join(ln for ln in lines if ln)


class WxMpScraper(BaseScraper):
    """Scraper for WeChat MP articles via the WeRead channel.

    Keeps the ``BaseScraper`` signature for orchestrator compatibility;
    ``http_client`` is reused as the we_read connection pool when available.
    """

    def __init__(self, config: WxMpConfig, http_client=None):
        super().__init__({"wxmp": config}, http_client)
        self._cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch WeChat articles.

        When the WeRead token is missing or has gone invalid (401), an
        interactive run pops the QR login window and retries once with the
        fresh token; CI / non-interactive runs skip the source fail-open.
        """
        client = build_client_from_wxmp_config(self._cfg, http_client=self.client)
        if not await ensure_login(client):
            logger.warning(
                "微信读书未登录或登录失效，跳过该源。可运行 `horizon-wxmp login` 扫码。"
            )
            return []

        login_retried = False
        while True:
            try:
                return await self._fetch_feeds(client, since)
            except WeReadAuthError as exc:
                if login_retried:
                    logger.warning("微信读书登录失效，跳过该源: %s", exc)
                    return []
                login_retried = True
                logger.warning("微信读书登录失效，正在弹出扫码窗口重新登录…")
                if await ensure_login(client, force=True):
                    continue  # 新 token，重试全部 feed
                return []

    async def _fetch_feeds(
        self, client, since: datetime
    ) -> List[ContentItem]:
        """List each enabled feed's articles within the time window.

        ``WeReadAuthError`` (401) propagates up to ``fetch`` so it can trigger
        a re-login; other WeRead errors are logged per-feed and skipped.
        """
        cutoff_ts = since.timestamp()
        items: List[ContentItem] = []
        for feed in self._cfg.feeds:
            if not feed.enabled or not feed.weread_mp_id:
                if feed.enabled:
                    logger.warning(
                        "跳过公众号 %r：缺少 weread_mp_id（先 `horizon-wxmp migrate` 迁移）",
                        feed.name,
                    )
                continue
            try:
                arts = await with_empty_retry(
                    lambda: self._list_feed_articles_weread(client, feed),
                    waits=self._cfg.weread.empty_retry_waits,
                    max_empties=self._cfg.weread.empty_max_retries,
                    log=logger,
                    ctx=f"公众号 {feed.name}",
                )
                for art in arts:
                    published_at = self._parse_publish_time(art)
                    if published_at is None or published_at.timestamp() < cutoff_ts:
                        continue
                    items.append(self._to_content_item(art, feed, published_at))
            except WeReadAuthError:
                raise  # 401 → 交回 fetch() 处理重新登录
            except WeReadError as exc:
                logger.warning("抓取公众号 %r 失败: %s", feed.name, exc)
        return items

    async def _list_feed_articles_weread(
        self, client, feed: WxMpSourceConfig
    ) -> List[dict]:
        """List one account's articles via we_read and normalize to the internal
        art-dict shape (rachelos-compatible) so downstream reuse is unchanged."""
        arts: List[dict] = []
        for art in await client.list_articles(feed.weread_mp_id, page=1):
            content = ""
            if self._cfg.gather_content and art.url:
                try:
                    raw = await client.fetch_article_html(art.url)
                    content = fix_wechat_images(raw)
                except WeReadError as exc:
                    # 单篇正文失败(302/风控/失效/网络) → 正文留空、文章保留，
                    # 不拖垮整个 feed 的其它文章。
                    logger.warning(
                        "公众号 %r 正文抓取失败，跳过正文: %s", feed.name, exc
                    )
            arts.append(
                {
                    "id": art.id,
                    "mp_id": feed.weread_mp_id,
                    "title": art.title,
                    "url": art.url,
                    "pic_url": art.pic_url,
                    "publish_time": art.publish_time,
                    "description": "",
                    "content": content,
                }
            )
        return arts

    def _to_content_item(
        self, art: dict, feed: WxMpSourceConfig, published_at: datetime
    ) -> ContentItem:
        content = art.get("content", "") or ""
        native_id = str(art.get("id", "")) or art.get("url", "")
        # we-read 返回的是微信文章的完整 HTML 正文（含 mmbiz.qpic.cn 图片）。
        # 直接由 scraper 产出 raw_content / raw_html / display_html，并标记
        # extraction_mode="skip"，让提取阶段跳过 trafilatura：trafilatura 会丢弃
        # 微信 CDN 无扩展名的图片 URL，重新提取会让详情页正文丢失配图。
        raw_html = content
        display_html = sanitize_wxmp_display_html(raw_html)
        return ContentItem(
            id=self._generate_id("wechat", str(feed.weread_mp_id or feed.feed_id), native_id),
            source_type=SourceType.WECHAT,
            title=art.get("title", "Untitled"),
            url=art.get("url", ""),
            content=content,
            raw_content=_html_to_text(raw_html) or None,
            raw_html=raw_html or None,
            display_html=display_html or None,
            cover_image=art.get("pic_url", "") or None,
            rss_summary=art.get("description", ""),
            rss_content_quality="high" if content else "low",
            author=feed.name,
            published_at=published_at,
            metadata={
                "feed_name": feed.name,
                "feed_id": feed.feed_id,
                "weread_mp_id": feed.weread_mp_id,
                "category": feed.category or "",
                "pic_url": art.get("pic_url", ""),
                "extraction_mode": "skip",
            },
        )

    @staticmethod
    def _parse_publish_time(art: dict) -> Optional[datetime]:
        """Parse ``publish_time`` (unix seconds, int/str/float) to UTC datetime."""
        raw = art.get("publish_time", "")
        if raw is None or raw == "":
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            logger.debug("Cannot parse publish_time: %r", raw)
            return None


class WxmpStoredScraper(BaseScraper):
    """从中间表 wxmp_articles 读微信文章的 scraper(collector 模式)。

    与 WxMpScraper 并列:collector 把文章抓进中间表,日报运行时只读表、不重复
    调 src/we_read。产出与 WxMpScraper._to_content_item 等价,下游提取/去重/
    翻译恢复/AI 分析/过滤链全部零改动。

    fail-open:窗口整体为空(新机器/CI/collector 未跑)时,自动降级为实时抓取
    (WxMpScraper),日报不丢微信内容。
    """

    def __init__(
        self,
        config: WxMpConfig,
        db: HorizonDB,
        run_date: str,
        http_client=None,
    ):
        super().__init__({"wxmp": config}, http_client)
        self._cfg = config
        self._db = db
        self._run_date = run_date  # 当前日报 run_date,消费标记粒度

    async def fetch(self, since: datetime) -> List[ContentItem]:
        rows = self._db.get_wxmp_articles_window(
            since_ts=since.timestamp(),
            exclude_news_run_date=self._run_date,
        )
        if not rows:
            # 窗口为空 → 实时兜底抓一次(不写中间表,collector 抓到后自然进表)。
            return await WxMpScraper(self._cfg, self.client).fetch(since)
        # 读取时不标记;标记由 orchestrator 在首次落库成功后统一做(崩溃重跑不丢)。
        return [self._row_to_item(r) for r in rows]

    def _row_to_item(self, row: dict) -> ContentItem:
        raw = row["raw_html"] or ""
        return ContentItem(
            id=row["id"],
            source_type=SourceType.WECHAT,
            title=row["title"],
            url=row["url"],
            content=raw,
            raw_content=row["content_text"] or _html_to_text(raw),
            raw_html=raw or None,
            display_html=row["display_html"] or sanitize_wxmp_display_html(raw) or None,
            cover_image=row["cover_image"],
            author=row["feed_name"],
            published_at=datetime.fromisoformat(row["published_at"]),
            metadata={
                "feed_name": row["feed_name"],
                "weread_mp_id": row["weread_mp_id"],
                "category": "",  # 中间表未存 category,归类交给 classify_topics 兜底
                "pic_url": row["cover_image"],
                "extraction_mode": "skip",
            },
        )
