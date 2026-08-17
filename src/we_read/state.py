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
