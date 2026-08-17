"""WeRead channel — WeChat official-account fetching via the cooderl wewe-rss
forwarding service (``https://weread.111965.xyz``). Pure HTTP, no Playwright.

Layering:  Horizon business layer → wxmp scraper → we_read client → weread API.

This package must NOT import any wxmp scraper business code, so that a future
channel failure can be replaced by swapping ``src/we_read/`` alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .client import WeReadClient, extract_article_body
from .config import WeReadConfig
from .ensure_login import ensure_login, is_interactive
from .errors import (
    WeReadAuthError,
    WeReadEmptyResponseError,
    WeReadError,
    WeReadError400,
    WeReadLoginTimeoutError,
    WeReadNetworkError,
    WeReadRateLimitError,
    WeReadServerError,
)
from .model import WeReadArticle, WeReadLoginSession, WeReadMpInfo
from .retry import RequestPacer, with_backoff, with_empty_retry
from .state import WeReadSyncState
from .token_store import WeReadTokenStore

if TYPE_CHECKING:
    import httpx

    from ..models import WxMpConfig

__all__ = [
    "WeReadClient",
    "WeReadConfig",
    "WeReadArticle",
    "WeReadLoginSession",
    "WeReadMpInfo",
    "WeReadTokenStore",
    "WeReadSyncState",
    "RequestPacer",
    "with_backoff",
    "with_empty_retry",
    "extract_article_body",
    "WeReadError",
    "WeReadAuthError",
    "WeReadError400",
    "WeReadRateLimitError",
    "WeReadEmptyResponseError",
    "WeReadServerError",
    "WeReadNetworkError",
    "WeReadLoginTimeoutError",
    "build_client_from_wxmp_config",
    "ensure_login",
    "is_interactive",
]


def build_client_from_wxmp_config(
    wxmp: "WxMpConfig", http_client: Optional["httpx.AsyncClient"] = None
) -> WeReadClient:
    """Assemble a :class:`WeReadClient` from a Horizon ``WxMpConfig``.

    An optional external :class:`httpx.AsyncClient` can be passed in to reuse
    a connection pool (news: the scraper's client; reports: the fetcher's).
    """
    wr = getattr(wxmp, "weread", None)
    if wr is None:
        cfg = WeReadConfig()
    else:
        cfg = WeReadConfig(
            base_url=wr.base_url,
            request_interval=wr.request_interval,
            jitter=wr.jitter,
            empty_retry_waits=tuple(wr.empty_retry_waits),
            empty_max_retries=wr.empty_max_retries,
            backoff_waits=tuple(wr.backoff_waits),
            timeout=wr.timeout,
            token_max_age_days=wr.token_max_age_days,
        )
    store = WeReadTokenStore(cfg.token_store_path)
    probe = next(
        (
            f.weread_mp_id
            for f in (wxmp.feeds or [])
            if getattr(f, "weread_mp_id", None)
        ),
        None,
    )
    return WeReadClient(
        cfg, store=store, probe_mp_id=probe, http_client=http_client
    )
