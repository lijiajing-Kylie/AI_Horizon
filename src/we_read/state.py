"""Sync-state tracking for the WeRead channel — ``data/auth/weread_sync.json``.

Records per-feed last successful sync timestamps plus a global last-sync time.
Used by ``status`` to display "最后同步时间" and by the empty-response retry
logic to distinguish "feed genuinely has no articles" from "rate-limited" when
a feed that previously returned articles suddenly returns empty lists.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


class WeReadSyncState:
    """Atomic read/write of sync progress."""

    def __init__(self, path: Path | str = "data/auth/weread_sync.json") -> None:
        self.path = Path(path)

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)

    def record_feed_success(self, mp_id: str) -> None:
        """Note that a feed synced successfully right now."""
        data = self._load()
        feeds = data.setdefault("feeds", {})
        feeds[str(mp_id)] = int(time.time())
        data["last_sync_at"] = int(time.time())
        self._atomic_write(data)

    def record_sync_finished(self) -> None:
        data = self._load()
        data["last_sync_at"] = int(time.time())
        self._atomic_write(data)

    def last_sync_at(self) -> Optional[int]:
        data = self._load()
        ts = data.get("last_sync_at")
        return int(ts) if ts else None

    def feed_last_sync(self, mp_id: str) -> Optional[int]:
        data = self._load()
        ts = (data.get("feeds") or {}).get(str(mp_id))
        return int(ts) if ts else None

    def subscribed_count(self) -> int:
        """Number of feeds ever recorded as synced (informational)."""
        return len(self._load().get("feeds") or {})

    # ── collector 调度计划(horizon-wxmp-collector 用)───────────────────────
    # 持久化文件额外增加顶层 key "schedule": {mp_id: {"next_run_at": ts}},
    # 与 feeds/last_sync_at 并列,status 向后兼容、collector 只增不改。

    def feed_next_run(self, mp_id: str) -> Optional[int]:
        """读某公众号的下次计划抓取时刻(schedule[mp_id].next_run_at)。"""
        data = self._load()
        entry = (data.get("schedule") or {}).get(str(mp_id)) or {}
        ts = entry.get("next_run_at")
        return int(ts) if ts else None

    def record_feed_schedule(self, mp_id: str, next_run_at: int) -> None:
        """记录某公众号的下次计划抓取时刻(原子写)。"""
        data = self._load()
        schedule = data.setdefault("schedule", {})
        schedule[str(mp_id)] = {"next_run_at": int(next_run_at)}
        self._atomic_write(data)
