"""Persistent token storage for the WeRead channel — ``data/auth/weread.json``.

Format: ``{"vid": …, "token": …, "created_at": <unix>, "last_success": <unix>}``

Expiry semantics (per design decision):
- ``token_max_age_days`` is advisory only — surfaced by ``status`` as a reminder,
  never enforced here and never used to block requests.
- The authoritative invalidation signal is a ``401`` from the forwarding service
  (:class:`we_read.errors.WeReadAuthError`); even then the token file is kept
  for forensics rather than cleared.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


class WeReadTokenStore:
    """Atomic read/write of the weread token file."""

    def __init__(self, path: Path | str = "data/auth/weread.json") -> None:
        self.path = Path(path)

    # ── reads ─────────────────────────────────────────────────────────────────
    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def get(self, key: str) -> Optional[str]:
        data = self.load()
        if not data:
            return None
        val = data.get(key)
        return str(val) if val is not None else None

    def is_present(self) -> bool:
        data = self.load()
        return bool(data and data.get("vid") and data.get("token"))

    def age_seconds(self) -> Optional[float]:
        """Seconds since last_success (or created_at) — None if never stored."""
        data = self.load()
        if not data:
            return None
        ref = data.get("last_success") or data.get("created_at")
        if not ref:
            return None
        try:
            return time.time() - float(ref)
        except (TypeError, ValueError):
            return None

    # ── writes ────────────────────────────────────────────────────────────────
    def save(self, vid: str, token: str) -> None:
        now = int(time.time())
        data = self.load() or {}
        data.update(
            {"vid": str(vid), "token": token, "created_at": now, "last_success": now}
        )
        self._atomic_write(data)

    def touch_success(self) -> None:
        """Refresh last_success after any successful forwarding-service call."""
        data = self.load()
        if data is None:
            return
        data["last_success"] = int(time.time())
        self._atomic_write(data)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    # ── internal ──────────────────────────────────────────────────────────────
    def _atomic_write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)
