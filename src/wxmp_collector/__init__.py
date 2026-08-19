"""微信抓取独立采集 daemon(可迁移常驻进程)。

把公众号抓取从新闻/报告管道里解耦出来:collector 按每号随机 4-8h 间隔抓取,
文章统一落中间表 wxmp_articles;horizon / horizon-reports 运行时只从中间表读、
再走原有分析/过滤流程,不再重复调 src/we_read。

**可回滚**:本包整体隔离,回滚时删除本目录 + pyproject 一条脚本入口 +
对应测试文件即可,对现有文件零残留。
"""

from __future__ import annotations

from .daemon import run_daemon, sync_feed
from .scheduler import feed_due, random_interval

__all__ = ["run_daemon", "sync_feed", "feed_due", "random_interval"]
