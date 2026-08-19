"""调度相关的纯函数(随机间隔 / 到期判定),便于单测。

随机模型:每个公众号的抓取间隔在 [min_seconds, max_seconds] 均匀随机,
每次抓完重新掷一次;不同号的到期时刻因此天然错开,避免固定时刻集中抓取
(这是微信风控最容易识别的行为模式)。
"""

from __future__ import annotations

import random
from typing import Optional


def random_interval(min_seconds: int, max_seconds: int) -> int:
    """在 [min_seconds, max_seconds] 秒区间内均匀随机取一个抓取间隔。"""
    return random.randint(min_seconds, max_seconds)


def feed_due(next_run_at: Optional[int], now: int) -> bool:
    """判定某公众号是否到点该抓。

    next_run_at 为空(尚未排程)视为到期,让首轮立即执行。
    """
    if next_run_at is None:
        return True
    return next_run_at <= now
