"""Data models for the WeRead channel (forwarding service payloads)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WeReadLoginSession:
    """Successful QR-login result from the forwarding service."""

    vid: str
    token: str
    username: str = ""


@dataclass(frozen=True)
class WeReadMpInfo:
    """A WeChat official account as resolved from a share link (wxs2mp)."""

    id: str
    name: str
    cover: str = ""
    intro: str = ""
    update_time: int = 0


@dataclass(frozen=True)
class WeReadArticle:
    """One article listing from the mps/{id}/articles endpoint."""

    id: str
    title: str
    pic_url: str = ""
    publish_time: int = 0
    url: str = ""
