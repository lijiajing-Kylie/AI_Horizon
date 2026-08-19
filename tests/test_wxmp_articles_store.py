"""中间表 wxmp_articles 的 CRUD / 窗口查询 / 消费标记 / 迁移幂等测试（无网络）。

中间表是「微信抓取独立调度」方案的地基：独立采集 daemon 落库，新闻/报告
两条管道只读消费。这里只测 db 层，不依赖 collector / we_read。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models import WxmpArticle
from src.storage.db import HorizonDB


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _art(i: int, *, feed: str = "机器之心", mp: str = "MP_WXS_001",
         url: str | None = None, published: datetime | None = None) -> WxmpArticle:
    """构造一篇文章，url 默认与 i 唯一对应（自然键幂等去重用）。"""
    ts = published or (_now() - timedelta(hours=i))
    return WxmpArticle(
        id=f"wechat:{mp}:{i}",
        feed_name=feed,
        weread_mp_id=mp,
        native_id=str(i),
        title=f"标题 {i}",
        url=url or f"https://mp.weixin.qq.com/s/{i}",
        published_at=ts,
        raw_html=f"<html>{i}</html>",
        display_html=f"<p>{i}</p>",
        content_text=f"正文 {i}",
        content_hash=f"hash{i}",
    )


def test_upsert_creates_rows_and_dedup_by_url(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    n = db.upsert_wxmp_articles([_art(1), _art(2)])
    assert n == 2
    assert len(db.get_wxmp_articles_window(since_ts=0)) == 2

    # 同一 URL 重抓 → 覆盖不增行,标题/正文更新
    again = _art(1)
    again.title = "标题 1 更新"
    db.upsert_wxmp_articles([again])
    rows = db.get_wxmp_articles_window(since_ts=0)
    assert len(rows) == 2
    titles = {r["title"] for r in rows}
    assert "标题 1 更新" in titles
    assert "标题 2" in titles


def test_upsert_does_not_overwrite_consumed_marks(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_art(1)])
    db.mark_wxmp_articles_consumed_news(["wechat:MP_WXS_001:1"], "2026-08-15")
    db.mark_wxmp_articles_consumed_reports(["wechat:MP_WXS_001:1"])

    # 重抓覆盖 → 两个消费标记必须保留
    db.upsert_wxmp_articles([_art(1)])
    row = db.conn.execute(
        "SELECT consumed_news_run_date, consumed_reports_at FROM wxmp_articles WHERE id=?",
        ("wechat:MP_WXS_001:1",),
    ).fetchone()
    assert row["consumed_news_run_date"] == "2026-08-15"
    assert row["consumed_reports_at"] is not None


def test_window_filters_by_time_and_feed(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    now = _now()
    db.upsert_wxmp_articles([
        _art(1, feed="机器之心", published=now - timedelta(hours=1)),
        _art(2, feed="腾讯研究院", published=now - timedelta(hours=30)),
    ])

    # 时间窗口:只看 24h 内 → 只剩机器之心
    since_ts = (now - timedelta(hours=24)).timestamp()
    rows = db.get_wxmp_articles_window(since_ts=since_ts)
    assert {r["feed_name"] for r in rows} == {"机器之心"}

    # feed 过滤:只看腾讯研究院 → 1 条
    rows = db.get_wxmp_articles_window(since_ts=0, feed_names=["腾讯研究院"])
    assert [r["feed_name"] for r in rows] == ["腾讯研究院"]
    assert len(rows) == 1


def test_window_excludes_news_run_date(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_art(1)])
    db.mark_wxmp_articles_consumed_news(["wechat:MP_WXS_001:1"], "2026-08-16")

    # 同 run_date 再读 → 排除(IS DISTINCT FROM 生效)
    assert db.get_wxmp_articles_window(
        since_ts=0, exclude_news_run_date="2026-08-16"
    ) == []
    # 其它 run_date 读 → 仍返回
    assert len(
        db.get_wxmp_articles_window(since_ts=0, exclude_news_run_date="2026-08-17")
    ) == 1


def test_window_excludes_reports_consumed(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_art(1), _art(2)])
    db.mark_wxmp_articles_consumed_reports(["wechat:MP_WXS_001:1"])

    rows = db.get_wxmp_articles_window(since_ts=0, exclude_reports_consumed=True)
    assert [r["native_id"] for r in rows] == ["2"]

    # 重抓覆盖 → last_synced_at 更新 → 文章重新进报告
    db.upsert_wxmp_articles([_art(1)])
    rows = db.get_wxmp_articles_window(since_ts=0, exclude_reports_consumed=True)
    assert {r["native_id"] for r in rows} == {"1", "2"}


def test_reset_news_consumption(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    db.upsert_wxmp_articles([_art(1)])
    db.mark_wxmp_articles_consumed_news(["wechat:MP_WXS_001:1"], "2026-08-16")
    n = db.reset_wxmp_articles_news_consumption("2026-08-16")
    assert n == 1
    # 重置后窗口重新可见
    assert len(db.get_wxmp_articles_window(since_ts=0)) == 1


def test_prune_only_deletes_fully_consumed_and_expired(tmp_path) -> None:
    db = HorizonDB(str(tmp_path / "t.db"))
    old = _now() - timedelta(days=90)
    db.upsert_wxmp_articles([
        _art(1, published=old),  # 未消费 → 保留
        _art(2, published=old),  # 只被新闻消费 → 保留
        _art(3, published=old),  # 双消费 → 删除
        _art(4),  # 新发布 → 保留
    ])
    db.mark_wxmp_articles_consumed_news(
        ["wechat:MP_WXS_001:2", "wechat:MP_WXS_001:3"], "2026-06-01"
    )
    db.mark_wxmp_articles_consumed_reports(["wechat:MP_WXS_001:3"])

    n = db.prune_wxmp_articles((_now() - timedelta(days=60)).isoformat())
    assert n == 1
    rows = db.get_wxmp_articles_window(since_ts=0)
    assert {r["native_id"] for r in rows} == {"1", "2", "4"}


def test_migration_idempotent(tmp_path) -> None:
    """反复打开同一库,迁移链不报错、表仍可写（幂等）。"""
    path = str(tmp_path / "t.db")
    for _ in range(3):
        db = HorizonDB(path)
        db.upsert_wxmp_articles([_art(1)])
    db = HorizonDB(path)
    assert len(db.get_wxmp_articles_window(since_ts=0)) == 1


def test_rewrite_wechat_img_proxy_across_three_tables(tmp_path) -> None:
    """存量 display_html 的旧代理地址前缀整体改写(三表覆盖、幂等)。

    db 层方法与具体前缀无关(参数化),测试用字面量模拟
    /api/img-proxy → weserv 的回填场景。
    """
    old_prefix = "/api/img-proxy?url="
    new_prefix = "https://images.weserv.nl/?url="
    encoded = "https%3A%2F%2Fmmbiz.qpic.cn%2Fx"  # quote(url, safe='') 段原样保留

    db = HorizonDB(str(tmp_path / "t.db"))
    art = _art(1)
    art.display_html = f'<p><img src="{old_prefix}{encoded}"></p>'
    db.upsert_wxmp_articles([art])
    db.conn.execute(
        "INSERT INTO items (id, source_type, title, url, published_at, fetched_at,"
        " run_date, display_html) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("i1", "wxmp", "标题", "https://u/1", "2026-08-18T00:00:00+00:00",
         "2026-08-18T00:00:00+00:00", "2026-08-18",
         f'<p><img src="{old_prefix}{encoded}"></p>'),
    )
    db.conn.execute(
        "INSERT INTO reports (id, source, native_id, title, url, content_text,"
        " published_at, updated_at, fetched_at, display_html)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("r1", "wxmp", "n1", "标题", "https://u/2", "正文",
         "2026-08-18T00:00:00+00:00", "2026-08-18T00:00:00+00:00",
         "2026-08-18T00:00:00+00:00", f'<p><img src="{old_prefix}{encoded}"></p>'),
    )
    db.conn.commit()

    counts = db.rewrite_wechat_img_proxy(old_prefix, new_prefix)
    assert counts == {"wxmp_articles": 1, "items": 1, "reports": 1}
    for table in ("wxmp_articles", "items", "reports"):
        html = db.conn.execute(f"SELECT display_html FROM {table}").fetchone()[0]
        assert f"{new_prefix}{encoded}" in html
        assert old_prefix not in html

    # 幂等:再跑一遍不再命中任何行
    assert db.rewrite_wechat_img_proxy(old_prefix, new_prefix) == {
        "wxmp_articles": 0, "items": 0, "reports": 0,
    }
