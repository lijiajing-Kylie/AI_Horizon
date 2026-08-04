"""WeChat login token / cookie persistence (local YAML only — Redis stripped)."""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from ..core.config import Config, cfg
from ..core.print import print_success, print_warning

REDIS_TOKEN_PREFIX = "werss:token:"  # kept for reference; Redis unused

# Lazy local persistence (created on first access / configure()).
_data_dir = "data/wxmp"
_wx_cfg: Optional[Config] = None


def configure(data_dir: str = "data/wxmp") -> None:
    """Point the token store at *data_dir* (must be called before first use)."""
    global _data_dir, _wx_cfg
    _data_dir = data_dir
    _wx_cfg = None


def _get_wx_cfg() -> Config:
    """Lazily build the wx.lic-backed Config for the configured data dir."""
    global _wx_cfg
    if _wx_cfg is None:
        lic_path = os.path.join(_data_dir, "wx.lic")
        os.makedirs(_data_dir, exist_ok=True)
        if not os.path.exists(lic_path):
            with open(lic_path, "w") as f:
                f.write("{}")
        _wx_cfg = Config(lic_path)
    return _wx_cfg


def set_token(data: Any, ext_data: Any = None) -> None:
    """Set WeChat login token and cookie info.

    :param data: dict containing token/cookie info.
    """
    if not data.get("token", ""):
        return

    token_data = {
        "token": data.get("token", ""),
        "cookie": data.get("cookies_str", ""),
        "fingerprint": data.get("fingerprint", ""),
        "expiry": data.get("expiry", {}),
    }
    if ext_data is not None:
        token_data["ext_data"] = ext_data

    _save_to_local(token_data)
    print_success(
        f"Token:{data.get('token')} \n到期时间:{data.get('expiry', {}).get('expiry_time')}\n"
    )


def _save_to_local(token_data: dict) -> None:
    """Save to the local wx.lic file."""
    wx_cfg = _get_wx_cfg()
    wx_cfg.set("token_data", token_data)
    wx_cfg.save_config()
    wx_cfg.reload()


def get(key: str, default: str = "") -> str:
    """Get a field from the overall token_data dict."""
    token_data = _get_token_data()
    if token_data is None:
        return default
    value = token_data.get(key, default)
    if isinstance(value, dict):
        return json.dumps(value)
    if value == "None":
        return ""
    return str(value) if value is not None else default


def _get_token_data() -> Optional[dict]:
    """Get the overall token_data (local file only)."""
    return _get_wx_cfg().get("token_data", None)
