"""Shared AI utility functions."""

import asyncio
import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Retrying AI completion calls
# ---------------------------------------------------------------------------


async def complete_with_retry(
    ai_client: Any,
    *,
    retries: int = 2,
    backoff: float = 1.5,
    **kwargs: Any,
) -> str:
    """Call ``ai_client.complete(**kwargs)`` with light exponential backoff.

    Retries transient failures (rate limits, timeouts, upstream errors) up to
    *retries* times, sleeping ``backoff * (attempt + 1)`` seconds between
    attempts.  Raises the last exception once attempts are exhausted.

    Single-provider configs get no retry from the client itself
    (``ChainedAIClient`` already falls back across providers), so this wrapper
    is the mitigation for rate-limit/request storms.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await ai_client.complete(**kwargs)
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_exc = exc
            if attempt >= retries:
                break
            await asyncio.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def parse_json_response(response: str) -> dict | None:
    """Try multiple strategies to extract a JSON object from an AI response.

    Returns the parsed dict, or None if all strategies fail.
    """
    text = response.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: extract from ```json ... ``` code block
    if "```json" in text:
        try:
            json_str = text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    # Strategy 3: extract from ``` ... ``` code block
    if "```" in text:
        try:
            json_str = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    # Strategy 4: find the first { ... } block using brace matching
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    # Strategy 5: regex extraction as last resort
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return None


# ---------------------------------------------------------------------------
# Content / comments splitting
# ---------------------------------------------------------------------------


def split_content_and_comments(
    content: str | None,
) -> tuple[str, str]:
    """Split ``ContentItem.content`` into *(main_text, comments_text)*.

    Items whose content contains ``--- Top Comments ---`` are split at that
    delimiter; otherwise the whole string is returned as main text with an
    empty comments string.  Both returned strings are stripped of leading /
    trailing whitespace.

    Returns ``("", "")`` when *content* is ``None`` or empty.
    """
    if not content:
        return "", ""
    if "--- Top Comments ---" in content:
        main, comments_part = content.split("--- Top Comments ---", 1)
        return main.strip(), comments_part.strip()
    return content.strip(), ""


# ---------------------------------------------------------------------------
# Engagement / discussion section builder
# ---------------------------------------------------------------------------

_ENGAGEMENT_FIELDS: list[tuple[str, Any]] = [
    ("score",           lambda v: f"score: {v}"),
    ("descendants",     lambda v: f"{v} comments"),
    ("favorite_count",  lambda v: f"{v} likes"),
    ("retweet_count",   lambda v: f"{v} retweets"),
    ("reply_count",     lambda v: f"{v} replies"),
    ("views",           lambda v: f"{v} views"),
    ("bookmarks",       lambda v: f"{v} bookmarks"),
    ("upvote_ratio",    lambda v: f"upvote ratio: {v:.0%}"),
]


def build_discussion_section(metadata: dict, comments_text: str = "") -> str:
    """Build a formatted discussion section from engagement metadata.

    Accepts *metadata* from ``ContentItem.metadata`` and an optional
    pre-extracted *comments_text* string.  Returns a multi-line string
    suitable for the ``discussion_section`` prompt placeholder, or an
    empty string when neither comments nor engagement signals are present.
    """
    parts: list[str] = []
    if comments_text:
        parts.append(f"Community Comments:\n{comments_text}")

    engagement_items = [
        fmt(metadata[key])
        for key, fmt in _ENGAGEMENT_FIELDS
        if metadata.get(key)
    ]
    if engagement_items:
        parts.append(f"Engagement: {', '.join(engagement_items)}")

    if metadata.get("discussion_url"):
        parts.append(f"Discussion: {metadata['discussion_url']}")
    if metadata.get("community_note"):
        parts.append(f"Community Note: {metadata['community_note']}")

    return "\n".join(parts)
