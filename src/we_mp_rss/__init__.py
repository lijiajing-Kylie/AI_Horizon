"""Bundled (vendored) core of we-mp-rss — WeChat Official Account scraper.

This package is a trimmed, process-embedded copy of the core scraping logic
from `https://github.com/rachelos/we-mp-rss` (MIT License, version 1.5.2).
It keeps the original module layout (``core/`` and ``driver/``) so upstream
fixes can be ported with minimal diff.  Removed: web UI, admin API, cascade,
queue/Redis/task scheduler, RSS output, notifications, doc2pdf, and the
Docker/HTTP serving layers.

License: see ``we_mp_rss/LICENSE`` (MIT, Copyright (c) 2025 RACHEL).
"""

from __future__ import annotations

from typing import Optional

__version__ = "1.5.2"

# Re-export the central configuration singleton so callers can seed it.
from .core.config import cfg


def init(
    wxmp_config: Optional["object"] = None,
    data_dir: str = "data/wxmp",
) -> None:
    """Seed the bundled config from a Horizon ``WxMpConfig``.

    Idempotent — call once at startup (or before any fetch/login).  Writes
    nothing to disk except the token files under *data_dir*.
    """
    from .core.config import build_config_dict, cfg

    if wxmp_config is not None:
        cfg.config = build_config_dict(wxmp_config)
        cfg._config = cfg.replace_env_vars(cfg.config)

    # Ensure the token/cookie data directory exists.
    import os
    os.makedirs(data_dir, exist_ok=True)

    # Point token/store/qr at the configured data dir.
    from . import driver  # noqa: F401
    from .driver import token as _token
    from .driver import store as _store
    from .driver import wx_api as _wx_api
    _token.configure(data_dir=data_dir)
    _store.configure(data_dir=data_dir)
    _wx_api.configure(data_dir=data_dir)


__all__ = ["cfg", "init", "__version__"]
