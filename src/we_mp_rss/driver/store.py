"""Encrypted cookie store (local key.lic only — Redis stripped)."""
from __future__ import annotations

import json
import os
from typing import Any, List

from ..core.config import cfg
from ..core.file import FileCrypto

_data_dir = "data/wxmp"
_key_file = "data/key.lic"
_store_instance: "KeyStore | None" = None


def configure(data_dir: str = "data/wxmp") -> None:
    """Point the cookie store at *data_dir* (must be called before first use)."""
    global _data_dir, _key_file, _store_instance
    _data_dir = data_dir
    _key_file = os.path.join(data_dir, "key.lic")
    _store_instance = None


class KeyStore:
    redis_key = "werss:key_store:cookies"  # kept for reference; Redis unused

    def __init__(self) -> None:
        self.key_file = _key_file
        self.store = FileCrypto(cfg.get("safe.lic_key", "store.csol.store.werss"))

    def save(self, text) -> None:
        items: List[Any] = []
        if type(text) != str:
            for item in text:
                items.append(item)
        text = json.dumps(items)
        self.store.encrypt_to_file(self.key_file, text.encode("utf-8"))

    def load(self):
        """Load cookies from the local encrypted file (filtered)."""
        try:
            text = self.store.decrypt_from_file(self.key_file).decode("utf-8")
            items = json.loads(text)
            return self._filter_items(items)
        except Exception:
            return ""

    def _filter_items(self, items):
        """Filter out `_clck` and `token` cookies."""
        new_items = []
        for item in items:
            if item["name"] == "_clck":
                continue
            if item["name"] == "token":
                continue
            new_items.append(item)
        return new_items


def _get_store() -> KeyStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = KeyStore()
    return _store_instance


def __getattr__(name: str) -> Any:
    """PEP 562 — expose a lazy module-level ``Store`` singleton."""
    if name == "Store":
        return _get_store()
    raise AttributeError(name)
