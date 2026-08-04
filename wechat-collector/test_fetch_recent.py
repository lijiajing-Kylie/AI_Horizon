"""Minimal test script — verify the collector can fetch the most recent
articles (default 5) for one 公众号.

Run from the repo root (``uv run`` gives it the project environment):

    uv run python wechat-collector/test_fetch_recent.py 机器之心
    uv run python wechat-collector/test_fetch_recent.py --feed-id MP_WXS_3073282833
    uv run python wechat-collector/test_fetch_recent.py --list

Exit codes: 0 = PASS (>=1 article fetched), 1 = FAIL (no articles / not logged
in / unusable feed_id).  Fetches without a browser (gather_content=False).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``collector`` (same dir) and ``src.we_mp_rss`` (repo root) importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import (  # noqa: E402
    faker_id_from_feed_id,
    fetch_recent,
    list_accounts,
    print_articles,
    resolve_account,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="最小测试：验证能否获取指定公众号最近 N 篇文章",
    )
    parser.add_argument("name", nargs="?", help="公众号名称（见 accounts.json）")
    parser.add_argument("--feed-id", help="直接以 MP_WXS_ 开头的 feed_id 抓取")
    parser.add_argument("--list", action="store_true", help="列出内置公众号")
    parser.add_argument("--limit", type=int, default=5, help="最近几篇(默认 5)")
    parser.add_argument("--data-dir", default="data/wxmp", help="登录态存放目录")
    args = parser.parse_args()

    if args.list:
        list_accounts()
        return 0

    try:
        name, feed_id = resolve_account(args.name, args.feed_id)
    except ValueError as e:
        print(e)
        return 1

    faker_id = faker_id_from_feed_id(feed_id)
    if not faker_id:
        print(f"FAIL: 无法从 feed_id 推导 faker_id: {feed_id!r}")
        return 1

    print(f"测试: 获取公众号 [{name}] ({feed_id}) 最近 {args.limit} 篇文章...")
    articles = fetch_recent(name, feed_id, limit=args.limit, data_dir=args.data_dir)

    if not articles:
        print("FAIL: 未获取到任何文章（请先登录，或该公众号近期无发布）")
        return 1

    print_articles(articles)
    print(f"PASS: 成功获取 {len(articles)} 篇（不足 {args.limit} 篇属正常："
          "公众号近期发布少或微信端点限制）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
