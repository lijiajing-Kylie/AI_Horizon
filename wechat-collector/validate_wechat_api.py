"""wechat-download-api 最小验证脚本。

本地调用 wechat-download-api 服务（默认 http://localhost:5050），
对 GitHubDaily 拉取最近 N 篇，输出 title / url / publish_time / content_html。

流程:
  1. GET  /api/public/searchbiz?query=GitHubDaily      -> fakeid
  2. GET  /api/public/articles?fakeid=X&begin=0&count=N -> 最近 N 篇列表
  3. POST /api/article {url} (每篇间隔 ≥3s)            -> 正文 HTML

用法（repo 根目录）:
    uv run python wechat-collector/validate_wechat_api.py
    uv run python wechat-collector/validate_wechat_api.py --limit 5 --base-url http://localhost:5050
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

import httpx

_BASE = "http://localhost:5050"
_ACCOUNT = "GitHubDaily"
_LIMIT = 5
_ARTICLE_PAUSE = 3.5  # 每篇正文请求间隔（秒），规避服务端防风控限频


def _get(client: httpx.Client, path: str, **params) -> dict:
    r = client.get(f"{_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("success") is False:
        raise RuntimeError(f"{path} 失败: {data.get('error')}")
    return data


def _post_article(client: httpx.Client, url: str) -> dict:
    r = client.post(f"{_BASE}/api/article", json={"url": url}, timeout=120)
    r.raise_for_status()
    data = r.json()
    if data.get("success") is False:
        raise RuntimeError(f"/api/article 失败: {data.get('error')}")
    return data.get("data", {})


def main() -> int:
    parser = argparse.ArgumentParser(description="wechat-download-api 最小验证")
    parser.add_argument("--account", default=_ACCOUNT, help="公众号名称")
    parser.add_argument("--limit", type=int, default=_LIMIT, help="最近几篇(默认 5)")
    parser.add_argument("--base-url", default=_BASE, help="wechat-download-api 地址")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=60)

    # 1. 健康检查
    try:
        r = client.get("/api/health", timeout=10)
        print(f"[health] HTTP {r.status_code} {r.text[:120]}")
    except Exception as e:
        print(f"[health] 连接失败: {e}（服务是否已启动在 {args.base_url}？）")
        return 2

    # 2. 搜索公众号 -> fakeid
    try:
        data = _get(client, "/api/public/searchbiz", query=args.account)
    except Exception as e:
        print(f"[searchbiz] 失败: {e}")
        print("  提示: 服务端未扫码登录时，此接口会返回 success=false。请先访问 login.html 扫码。")
        return 1
    lst = data.get("data", {}).get("list", [])
    if not lst:
        print(f"[searchbiz] 未找到公众号: {args.account}")
        return 1
    acc = lst[0]
    fakeid = acc.get("fakeid")
    print(f"[searchbiz] 找到: {acc.get('nickname')}  alias={acc.get('alias')}  fakeid={fakeid}")

    # 3. 文章列表 -> 最近 N 篇
    try:
        data = _get(client, "/api/public/articles", fakeid=fakeid, begin=0, count=args.limit)
    except Exception as e:
        print(f"[articles] 失败: {e}")
        return 1
    articles = data.get("data", {}).get("articles", [])
    total = data.get("data", {}).get("total")
    print(f"[articles] 该号共 {total} 篇，本次取最近 {len(articles)} 篇\n")

    # 4. 每篇拉正文，输出 title / url / publish_time / content_html
    ok = 0
    for i, art in enumerate(articles, 1):
        url = art.get("link", "")
        print(f"───── [{i}] 拉取正文: {art.get('title', '')}")
        try:
            detail = _post_article(client, url)
        except Exception as e:
            print(f"  !! 正文失败: {e}")
            continue

        publish = detail.get("publish_time_str") or art.get("update_time") or ""
        content_html = detail.get("content", "")
        print(f"  title        : {detail.get('title') or art.get('title')}")
        print(f"  url          : {url}")
        print(f"  publish_time : {publish}  (unix={detail.get('publish_time')})")
        print(f"  content_html : {len(content_html)} 字符")
        # 原始结果落盘到本地文件，便于核对
        with open(f"/tmp/wxapi_article_{i}.json", "w", encoding="utf-8") as f:
            json.dump({"title": detail.get("title"), "url": url,
                       "publish_time": detail.get("publish_time"),
                       "publish_time_str": detail.get("publish_time_str"),
                       "content_html": content_html,
                       "plain_content": detail.get("plain_content", "")}, f,
                      ensure_ascii=False, indent=2)
        ok += 1
        if i < len(articles):
            time.sleep(_ARTICLE_PAUSE)

    print(f"\n[结果] 成功拉取正文 {ok}/{len(articles)} 篇")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
