"""常驻采集 daemon:每号随机 4-8h 间隔抓公众号,文章落中间表 wxmp_articles。

单线程串行,同一时刻只有一个公众号在抓,不存在并发;随机体现在两层——
每号间隔 [interval_min, interval_max] 均匀随机(每次抓完重掷),不同号的
到期时刻因此天然错开。转发服务层面的节流由 WeReadClient 内置 api_pacer
(20s±5)/ article_pacer(2s±2)全局兜底,不新增节流代码。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import signal
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models import WxmpArticle
from ..scrapers.wxmp import (
    _html_to_text,
    fix_wechat_images,
    sanitize_wxmp_display_html,
)
from ..storage.db import HorizonDB, _dt_iso
from ..we_read import build_client_from_wxmp_config, with_empty_retry
from ..we_read.client import WeReadClient
from ..we_read.errors import WeReadAuthError, WeReadError
from ..we_read.state import WeReadSyncState
from .scheduler import random_interval

logger = logging.getLogger(__name__)


def _sha1(text: str) -> str:
    """content_hash = sha1(url),与中间表 DDL 注释一致。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


async def sync_feed(client, feed, db: HorizonDB, wxmp, max_age_days: Optional[int] = None) -> int:
    """抓单个公众号:列表 → 与中间表已有 URL 去重 → 逐篇抓正文 → upsert。

    返回本次写入/更新的行数。单篇正文失败只留空、不拖垮整号;单号整体失败
    由上层(run_daemon)捕获记录,进程继续跑其他号(fail-open)。
    """
    arts = await with_empty_retry(
        lambda: client.list_articles(feed.weread_mp_id, page=1),
        waits=wxmp.weread.empty_retry_waits,
        max_empties=wxmp.weread.empty_max_retries,
        log=logger,
        ctx=f"公众号 {feed.name}",
    )
    existing = db.get_wxmp_article_urls(feed.weread_mp_id)  # 命中 → 不重复抓正文
    now = datetime.now(timezone.utc)
    cutoff = (
        now - timedelta(days=max_age_days)
        if max_age_days is not None
        else None
    )
    rows: list[WxmpArticle] = []
    for art in arts:
        if not art.url or art.url in existing:
            continue
        if not art.publish_time:
            continue  # 转发服务没带发布时间,宁缺毋滥
        published_dt = datetime.fromtimestamp(float(art.publish_time), tz=timezone.utc)
        if cutoff is not None and published_dt < cutoff:
            continue  # 可选窗口:过滤老文章
        raw = ""
        if wxmp.gather_content:
            try:
                raw = await client.fetch_article_html(art.url)  # article_pacer 2s±2
            except WeReadError as exc:
                logger.warning("单篇正文失败留空: %s", exc)  # 不拖垮整号
        raw_html = fix_wechat_images(raw)
        rows.append(WxmpArticle(
            id=f"wechat:{feed.weread_mp_id}:{art.id}",  # 与 ContentItem.id 格式一致
            feed_name=feed.name,
            weread_mp_id=feed.weread_mp_id,
            native_id=art.id,
            title=art.title,
            url=art.url,
            cover_image=art.pic_url or None,
            published_at=published_dt,
            raw_html=raw_html or None,
            display_html=sanitize_wxmp_display_html(raw_html) or None,
            content_text=_html_to_text(raw_html) or None,
            content_hash=_sha1(art.url),
            fetched_at=now,
            last_synced_at=now,
        ))
    return db.upsert_wxmp_articles(rows)


def _prune_if_due(db: HorizonDB, retention_days: int) -> None:
    """清理已过保留期且被两条管道都消费过的行;未消费的过期行一律保留。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    n = db.prune_wxmp_articles(_dt_iso(cutoff))
    if n:
        logger.info("清理 %d 条已消费且过期的中间表文章(保留 %d 天)", n, retention_days)


async def _sleep_interruptible(delay: float, stop: asyncio.Event) -> None:
    """可中断睡眠:stop 触发即返回,用于同轮到点的号之间随机打散。"""
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except asyncio.TimeoutError:
        pass


async def _wait_for_re_login(
    client: WeReadClient,
    feeds,
    stop: asyncio.Event,
    *,
    poll: float = 60.0,
    max_wait: Optional[float] = None,
) -> Optional[bool]:
    """登录失效后等待重新扫码:每 ``poll`` 秒探测一次登录态,恢复后继续。

    返回 True=登录已恢复;False=等待超过 ``max_wait``(不设则一直等);
    None=等待期间 stop 被置位(用户 SIGINT/SIGTERM 主动停止)。
    """
    probe = next((f.weread_mp_id for f in feeds if f.weread_mp_id), None)
    if probe is None:
        return False
    deadline = time.monotonic() + max_wait if max_wait else None
    while not stop.is_set():
        if deadline is not None and time.monotonic() >= deadline:
            logger.error("等待重登超过 %.0f 分钟仍未恢复,collector 停止。", max_wait / 60.0)
            return False
        try:
            # 认证通过即视为恢复(空列表也算:空只是频控信号,不是凭证失效)。
            await client.list_articles(probe, page=1)
            logger.info("登录态已恢复,collector 继续抓取。")
            return True
        except WeReadAuthError:
            logger.warning("登录态未恢复,%.0fs 后重试(运行 `horizon-wxmp login` 扫码)...", poll)
        except WeReadError:
            # 非认证错误(429/5xx/网络)不代表凭证失效,但也未确认恢复,继续等。
            logger.warning("登录探测异常,%.0fs 后重试...", poll)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except asyncio.TimeoutError:
            pass
    return None


async def wait_until_next_due(state: WeReadSyncState, feeds, stop: asyncio.Event, poll: float = 30.0) -> None:
    """睡到最近的 next_run_at(每 30s 醒来查一次 stop),随时响应 SIGINT/SIGTERM。

    所有 feed 都已过 next_run_at 时立即返回,避免空转。
    """
    while not stop.is_set():
        now = time.time()
        next_ts = min(
            (state.feed_next_run(f.weread_mp_id) for f in feeds),
            default=None,
        )
        if next_ts is None or next_ts <= now:
            return
        delay = min(max(next_ts - now, 0.0), poll)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue


async def run_daemon(
    config,
    *,
    interval: tuple[int, int] = (4 * 3600, 8 * 3600),
    max_age_days: Optional[int] = None,
    retention_days: int = 60,
    once: bool = False,
    db_path: str = "data/horizon.db",
    state_path: Optional[str] = None,
    client=None,
    inter_feed_jitter: tuple[float, float] = (30.0, 180.0),
    auth_poll_sec: float = 60.0,
    auth_max_wait_sec: Optional[float] = None,
) -> None:
    """常驻调度循环(once=True 时抓一轮全量后退出)。

    首启:常驻模式每号随机初始计划时间(非立即,避免启动瞬间全部开抓);
    once 模式强制全部立即到期,抓完一轮退出。

    登录失效不退出:进入等待重登(``_wait_for_re_login``),每 ``auth_poll_sec``
    探测一次,扫码后自动恢复并重试当前号;``auth_max_wait_sec`` 可设最大等待
    (不设则一直等到扫码或进程被停止)。

    state_path / client / inter_feed_jitter / auth_poll_sec / auth_max_wait_sec
    仅供测试注入(隔离真实的 data/auth 与连接池、缩短打散睡眠与等待重登探测);
    默认行为与文档一致。
    """
    wxmp = config.sources.wxmp
    feeds = [f for f in wxmp.feeds if f.enabled and f.weread_mp_id]
    db = HorizonDB(db_path)
    state = WeReadSyncState(state_path) if state_path else WeReadSyncState()
    client = client or build_client_from_wxmp_config(wxmp)
    if not client.store.is_present():
        # 未登录不崩溃:到点抓取遇到 401 会进入等待重登,扫码后自动恢复。
        logger.warning("微信读书未登录,先运行 `horizon-wxmp login` 扫码。")

    now_i = int(time.time())
    if once:
        # 单轮全量:所有号立即到期,抓完一轮后 break。
        for f in feeds:
            state.record_feed_schedule(f.weread_mp_id, now_i)
    else:
        for f in feeds:
            if state.feed_next_run(f.weread_mp_id) is None:
                state.record_feed_schedule(
                    f.weread_mp_id, now_i + random_interval(*interval)
                )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # 非主线程等不支持 add_signal_handler 的环境

    _prune_if_due(db, retention_days)  # 启动时清理一次
    last_prune = time.time()
    auth_failed = False
    try:
        while not stop.is_set():
            now = time.time()
            due = [f for f in feeds if state.feed_next_run(f.weread_mp_id) <= now]
            for i, f in enumerate(due):
                auth_failed = False
                try:
                    n = await sync_feed(client, f, db, wxmp, max_age_days)
                    state.record_feed_success(f.weread_mp_id)
                    logger.info("抓取 %s 完成,写入 %d 篇", f.name, n)
                except WeReadAuthError:
                    # 登录失效是全局性的:token 被服务端判定无效后所有号都会 401。
                    # 不退出进程,进入等待重登:定期探测登录态,扫码后自动恢复,无需重启。
                    logger.error(
                        "%s 登录失效;运行 `uv run horizon-wxmp login` 扫码后自动恢复。",
                        f.name,
                    )
                    recovered = await _wait_for_re_login(
                        client, feeds, stop,
                        poll=auth_poll_sec, max_wait=auth_max_wait_sec,
                    )
                    if recovered is None or not recovered:
                        # None=用户主动停止;False=等待超时。都停止本轮抓取。
                        auth_failed = True
                        break
                    # 登录已恢复:重试当前号(此前因 401 未抓到),成功则照常重掷排期。
                    n = await sync_feed(client, f, db, wxmp, max_age_days)
                    state.record_feed_success(f.weread_mp_id)
                    logger.info("抓取 %s 完成,写入 %d 篇", f.name, n)
                except WeReadError as exc:
                    logger.warning("抓取 %s 失败(fail-open): %s", f.name, exc)
                except sqlite3.OperationalError as exc:
                    # 与管道/API 并发写同一 SQLite 文件时的锁碰撞。busy_timeout 已兜住
                    # 大部分,剩余撞锁按单号失败跳过并重新排期,而不是让整个 daemon 退出。
                    logger.warning("数据库忙,跳过 %s: %s", f.name, exc)
                finally:
                    # 登录失效时不重掷排期:保持原计划时间,重登重启后到点即可抓,
                    # 而不是又随机排到 4-8h 之后白等一轮。
                    if not auth_failed:
                        state.record_feed_schedule(
                            f.weread_mp_id, int(time.time()) + random_interval(*interval)
                        )
                if auth_failed:
                    break
                if i < len(due) - 1:  # 同轮到点的号之间再随机打散(默认 30-180s)
                    await _sleep_interruptible(random.uniform(*inter_feed_jitter), stop)
            if time.time() - last_prune > retention_days * 3600 / 2:
                _prune_if_due(db, retention_days)
                last_prune = time.time()
            if auth_failed or once:
                break
            await wait_until_next_due(state, feeds, stop)
    finally:
        await client.aclose()  # client.py:102 — 只在自持连接时真正关闭
    # 仅等待超时抛错提示重登;用户主动停止时 stop 已置位,静默正常退出(exit 0)。
    if auth_failed and not stop.is_set():
        raise WeReadAuthError(
            "微信读书登录失效且等待重登超时,collector 已停止;运行 `uv run horizon-wxmp login` 重新扫码后再启动。"
        )
