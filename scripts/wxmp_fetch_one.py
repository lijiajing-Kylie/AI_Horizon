#!/usr/bin/env python3
"""一次性脚本：把单篇微信公众号文章 URL 抓进中间表 wxmp_articles。

collector 走 list_articles 列表，单篇 URL 若不在列表里（发布时间较早/服务未
收录）就不会进中间表。本脚本直接抓文章 HTML，解析标题/封面/发布时间/正文，
构造 WxmpArticle 落库。

用法：
    uv run python scripts/wxmp_fetch_one.py <url> --dry-run   # 只打印解析结果
    uv run python scripts/wxmp_fetch_one.py <url> --write     # 写中间表

跑完即可删除。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from bs4 import BeautifulSoup

from src.models import WxmpArticle
from src.scrapers.wxmp import _html_to_text, fix_wechat_images, sanitize_wxmp_display_html
from src.storage.db import HorizonDB
from src.storage.manager import StorageManager

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _parse_publish_time(html: str, soup: BeautifulSoup) -> datetime | None:
    """从文章 HTML 提取发布时间：unix 时间戳 → 日期字符串 → em#publish_time。"""
    # unix 秒：ori_create_time / create_timestamp / var createTime
    for pat in (
        r"ori_create_time:\s*'?(\d{10,})'?",
        r"create_timestamp:\s*'?(\d{10,})'?",
        r"var\s+createTime\s*=\s*'?(\d{10,})'?",
    ):
        m = re.search(pat, html)
        if m:
            try:
                return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
            except (ValueError, OSError):
                pass
    # 日期字符串：create_time: 'YYYY-MM-DD'
    m = re.search(r"create_time:\s*'?(\d{4}-\d{2}-\d{2})'?", html)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    em = soup.select_one("#publish_time")
    if em:
        text = em.get_text(strip=True)
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


async def fetch_one(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", property="og:title")
    title = (og["content"].strip() if og else "") or (soup.select_one(".rich_media_title") or "").get_text(strip=True) or ""
    ogimg = soup.find("meta", property="og:image")
    cover = ogimg["content"].strip() if ogimg else None
    published_at = _parse_publish_time(html, soup)

    body = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    raw = str(body) if body else ""
    return {"html_len": len(html), "title": title, "cover": cover, "published_at": published_at, "raw_len": len(raw)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--write", action="store_true", help="写中间表（默认 dry-run）")
    args = parser.parse_args()

    info = await fetch_one(args.url)
    print(f"HTML 长度: {info['html_len']}")
    print(f"标题: {info['title']}")
    print(f"封面: {info['cover']}")
    print(f"发布时间: {info['published_at']}")
    print(f"正文容器长度: {info['raw_len']}")
    if not args.write:
        print("(dry-run) 加 --write 才写入中间表")
        return
    if not info["title"] or not info["raw_len"]:
        print("[red]标题或正文缺失，不落库[/red]")
        return

    # 解析公众号（复用 we_read 转发服务）
    config = StorageManager().load_config()
    wxmp = config.sources.wxmp
    from src.we_read import build_client_from_wxmp_config
    from src.we_read.client import WeReadClient

    client: WeReadClient = build_client_from_wxmp_config(wxmp)
    infos = await client.resolve_share(args.url)
    if not infos:
        print("[red]无法解析该链接所属公众号[/red]")
        return
    mp = infos[0]
    mp_id, feed_name = mp.id, mp.name
    print(f"公众号: {feed_name} ({mp_id})")

    native = args.url.rstrip("/").split("/")[-1]
    raw_html = fix_wechat_images((await _fetch_body(client, args.url)))
    now = datetime.now(timezone.utc)
    article = WxmpArticle(
        id=f"wechat:{mp_id}:{native}",
        feed_name=feed_name,
        weread_mp_id=mp_id,
        native_id=native,
        title=info["title"],
        url=args.url,
        cover_image=info["cover"],
        published_at=info["published_at"] or now,
        raw_html=raw_html or None,
        display_html=sanitize_wxmp_display_html(raw_html) or None,
        content_text=_html_to_text(raw_html) or None,
        content_hash=_sha1(args.url),
        fetched_at=now,
        last_synced_at=now,
    )
    db = HorizonDB()
    n = db.upsert_wxmp_articles([article])
    print(f"[green]已写入中间表: {feed_name} / {info['title'][:40]} (影响 {n} 行)[/green]")


async def _fetch_body(client, url: str) -> str:
    """复用 we_read 客户端的正文抓取（含 pacer/UA/风控处理）。"""
    return await client.fetch_article_html(url)


if __name__ == "__main__":
    asyncio.run(main())
