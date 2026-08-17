"""WeRead channel HTTP client — wraps the cooderl wewe-rss forwarding service.

Pure HTTP, no Playwright. Two independent pace-controlled request paths:
- forwarding-service API (login / wxs2mp / articles) — auth headers, strict pacing
- mp.weixin.qq.com article pages — no auth, loose pacing

The client accepts an external :class:`httpx.AsyncClient` so callers can reuse
their connection pool (news: the scraper's client; reports: the fetcher's).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional, Tuple

import httpx

from .config import WeReadConfig
from .errors import (
    WeReadAuthError,
    WeReadError,
    WeReadError400,
    WeReadLoginTimeoutError,
    WeReadNetworkError,
    WeReadRateLimitError,
    WeReadServerError,
)
from .model import WeReadArticle, WeReadLoginSession, WeReadMpInfo
from .retry import RequestPacer
from .token_store import WeReadTokenStore

logger = logging.getLogger(__name__)


def _map_status(status: int, body: str = "") -> Optional[WeReadError]:
    # The forwarding service wraps WeRead errors in HTTP 500 with a message
    # marker like "id(123): WeReadError400" — match those first.
    if "WeReadError401" in body:
        return WeReadAuthError("微信读书登录失效(401)，请重新运行 `horizon-wxmp login` 扫码")
    if "WeReadError429" in body:
        return WeReadRateLimitError("微信读书请求过于频繁(429)")
    if "WeReadError400" in body:
        return WeReadError400(f"微信读书参数错误(400): {body[:120]}")
    if status == 401:
        return WeReadAuthError("微信读书登录失效(401)，请重新运行 `horizon-wxmp login` 扫码")
    if status == 400:
        return WeReadError400(f"微信读书参数错误(400): {body[:120]}")
    if status == 429:
        return WeReadRateLimitError("微信读书请求过于频繁(429)")
    if status >= 500:
        return WeReadServerError(f"微信读书转发服务错误({status}): {body[:120]}")
    return None


def extract_article_body(html: str) -> str:
    """Extract the WeChat article content container as outerHTML (or "")."""
    if not html:
        return ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("#js_content, .rich_media_content")
    return str(node) if node is not None else ""


class WeReadClient:
    """Async client for the WeRead forwarding service + article pages."""

    def __init__(
        self,
        config: Optional[WeReadConfig] = None,
        store: Optional[WeReadTokenStore] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        api_pacer: Optional[RequestPacer] = None,
        article_pacer: Optional[RequestPacer] = None,
        probe_mp_id: Optional[str] = None,
    ) -> None:
        self.config = config or WeReadConfig()
        self.store = store or WeReadTokenStore(self.config.token_store_path)
        self.probe_mp_id = probe_mp_id
        self._http = http_client
        self._owns_http = http_client is None
        self.api_pacer = api_pacer or RequestPacer(
            self.config.request_interval, self.config.jitter
        )
        self.article_pacer = article_pacer or RequestPacer(
            self.config.article_interval, self.config.article_jitter
        )

    # ── lifecycle ─────────────────────────────────────────────────────────────
    @property
    def client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self.config.timeout, follow_redirects=True
            )
            self._owns_http = True
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── auth header ───────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        vid = self.store.get("vid")
        token = self.store.get("token")
        return {"xid": str(vid), "Authorization": f"Bearer {token}"}

    # ── unified API request (forwarding service) ─────────────────────────────
    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[float] = None,
        auth: bool = True,
    ) -> httpx.Response:
        await self.api_pacer.wait_before_request()
        kwargs: dict = {"timeout": timeout}
        if params is not None:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        if auth:
            kwargs["headers"] = self._headers()
        try:
            resp = await self.client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise WeReadNetworkError(f"请求失败: {exc}") from exc
        err = _map_status(resp.status_code, resp.text)
        if err is not None:
            raise err
        self.store.touch_success()
        return resp

    # ── login ────────────────────────────────────────────────────────────────
    async def create_login(self) -> Tuple[str, str]:
        """Create a login QR. Returns ``(uuid, scan_url)``."""
        resp = await self._request(
            "GET", f"{self.config.base_url}/api/v2/login/platform", auth=False
        )
        data = resp.json()
        return data["uuid"], data["scanUrl"]

    async def poll_login(self, uuid: str, *, timeout: float = 120.0) -> WeReadLoginSession:
        """Poll until the user scans. Logs in and persists the token on success."""
        url = f"{self.config.base_url}/api/v2/login/platform/{uuid}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await self.api_pacer.wait_before_request()
            try:
                resp = await self.client.get(url)
            except httpx.TransportError as exc:
                logger.warning("登录轮询网络错误: %s", exc)
                await asyncio.sleep(self.config.poll_interval)
                continue
            if resp.status_code >= 500:
                logger.warning("登录轮询服务端错误 %d，稍后重试", resp.status_code)
                await asyncio.sleep(self.config.poll_interval)
                continue
            if resp.status_code in (401, 400):
                raise WeReadError400(
                    f"登录轮询失败 status={resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            token = data.get("token")
            if token:
                session = WeReadLoginSession(
                    vid=str(data.get("vid", "")),
                    token=token,
                    username=str(data.get("username", "") or ""),
                )
                self.store.save(session.vid, session.token)
                return session
            # {"message": "waiting"} → keep polling
            msg = data.get("message")
            if msg and msg != "waiting":
                logger.info("登录状态: %s", msg)
            await asyncio.sleep(self.config.poll_interval)
        raise WeReadLoginTimeoutError("扫码登录超时，请重试")

    # ── platform ─────────────────────────────────────────────────────────────
    async def resolve_share(self, share_url: str) -> List[WeReadMpInfo]:
        """Resolve a share link into the account(s) it belongs to (wxs2mp)."""
        resp = await self._request(
            "POST",
            f"{self.config.base_url}/api/v2/platform/wxs2mp",
            json_body={"url": share_url.strip()},
        )
        data = resp.json()
        if not isinstance(data, list):
            raise WeReadError400(f"wxs2mp 返回异常: {data}")
        return [
            WeReadMpInfo(
                id=str(item.get("id", "")),
                name=str(item.get("name", "") or ""),
                cover=str(item.get("cover", "") or ""),
                intro=str(item.get("intro", "") or ""),
                update_time=int(item.get("updateTime", 0) or 0),
            )
            for item in data
        ]

    async def list_articles(self, mp_id: str, page: int = 1) -> List[WeReadArticle]:
        """List articles for an account. An empty ``[]`` is returned as-is (the
        caller decides whether that is a rate limit via ``with_empty_retry``)."""
        resp = await self._request(
            "GET",
            f"{self.config.base_url}/api/v2/platform/mps/{mp_id}/articles",
            params={"page": page},
        )
        data = resp.json()
        if not isinstance(data, list):
            raise WeReadError400(f"articles 返回异常: {data}")
        return [
            WeReadArticle(
                id=str(item.get("id", "")),
                title=str(item.get("title", "") or ""),
                pic_url=str(item.get("picUrl", "") or ""),
                publish_time=int(item.get("publishTime", 0) or 0),
                url=str(item.get("url", "") or ""),
            )
            for item in data
        ]

    # ── article full text (mp.weixin.qq.com, no auth) ────────────────────────
    async def fetch_article_html(self, article_url: str) -> str:
        """Fetch the article content container outerHTML from the public link."""
        await self.article_pacer.wait_before_request()
        try:
            resp = await self.client.get(
                article_url,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                timeout=self.config.article_timeout,
                # 外部传入的 client 默认不跟随重定向；微信文章失效/风控常回 302，
                # 显式跟随，避免 302 直接被 raise_for_status() 打成硬错误。
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.TransportError as exc:
            raise WeReadNetworkError(f"正文抓取网络错误: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise WeReadServerError(
                f"正文抓取被拒 status={exc.response.status_code}"
            ) from exc
        return extract_article_body(resp.text)

    # ── token validation (for `status`) ───────────────────────────────────────
    async def validate_token(self) -> bool:
        """Probe whether the stored token is valid by listing a known account.

        ``401`` → False (invalid). Other errors (400/5xx/network) → True because
        they are uncertain — "not demonstrably invalid" keeps status honest.
        """
        if not self.store.is_present():
            return False
        if not self.probe_mp_id:
            return True  # nothing to probe against — assume valid
        try:
            await self.list_articles(self.probe_mp_id, page=1)
            return True
        except WeReadAuthError:
            return False
        except WeReadError:
            return True
