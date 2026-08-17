"""Runtime configuration for the WeRead channel.

Defaults match the cooderl/wewe-rss forwarding service behavior observed during
the spike validation:
- The forwarding service rate-limits by silently returning ``[]`` — retry
  helpers and pacing below are tuned around that.
- WeRead API requests (login / wxs2mp / articles) hit the forwarding service and
  must stay ~20s apart to avoid rate limiting.
- Article-URL requests hit mp.weixin.qq.com directly (public links) and have a
  much looser anti-crawl budget — paced independently at 2-4s so heavy full-text
  fetching doesn't drag out the sync window.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeReadConfig:
    base_url: str = "https://weread.111965.xyz"

    # ── WeRead API pacing (forwarding service) ────────────────────────────────
    request_interval: float = 20.0
    jitter: float = 5.0

    # ── Article-URL pacing (mp.weixin.qq.com public links) ────────────────────
    article_interval: float = 2.0
    article_jitter: float = 2.0

    # ── Retries ───────────────────────────────────────────────────────────────
    empty_retry_waits: tuple = (15.0, 30.0)
    empty_max_retries: int = 3
    backoff_waits: tuple = (15.0, 30.0, 60.0)

    # ── Login ─────────────────────────────────────────────────────────────────
    poll_interval: float = 5.0

    # ── Timeouts ──────────────────────────────────────────────────────────────
    timeout: float = 20.0
    article_timeout: float = 20.0

    # ── Article fetch UA (public link) ────────────────────────────────────────
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    token_store_path: str = "data/auth/weread.json"
    sync_state_path: str = "data/auth/weread_sync.json"
    # Advisory only: surfaced by `status` as a reminder, never enforced.
    # The authoritative invalidation signal is a 401 from the API.
    token_max_age_days: int = 30
