"""Tests for parse_json_response's multi-strategy JSON extraction."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.ai.utils import complete_with_retry, parse_json_response


def test_parses_direct_valid_json():
    assert parse_json_response('{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}


def test_parses_json_with_surrounding_whitespace():
    assert parse_json_response('\n\n  {"a": 1}  \n') == {"a": 1}


def test_extracts_from_json_labeled_code_fence():
    text = 'Here is the result:\n```json\n{"a": 1, "b": 2}\n```\nHope that helps.'
    assert parse_json_response(text) == {"a": 1, "b": 2}


def test_extracts_from_plain_code_fence_without_json_tag():
    text = 'Sure thing:\n```\n{"a": 1}\n```'
    assert parse_json_response(text) == {"a": 1}


def test_extracts_json_embedded_in_prose_without_code_fence():
    text = 'Sure, here is my answer: {"relevant": true, "score": 7} — let me know if you need more.'
    assert parse_json_response(text) == {"relevant": True, "score": 7}


def test_handles_nested_objects_and_arrays_via_brace_matching():
    text = 'Result: {"tags": ["a", "b"], "nested": {"x": 1, "y": [1, 2, {"z": 3}]}} done'
    result = parse_json_response(text)
    assert result == {"tags": ["a", "b"], "nested": {"x": 1, "y": [1, 2, {"z": 3}]}}


def test_returns_none_for_non_json_text():
    assert parse_json_response("Sorry, I can't help with that.") is None


def test_returns_none_for_empty_string():
    assert parse_json_response("") is None
    assert parse_json_response("   ") is None


def test_returns_none_when_code_fence_contains_malformed_json():
    text = '```json\n{"a": 1,}\n```'  # trailing comma is invalid JSON
    assert parse_json_response(text) is None


def test_recovers_via_regex_fallback_when_naive_brace_counting_miscounts_string_content():
    """The brace-matching strategy counts every literal '{'/'}' character,
    including ones inside quoted string *values* — it isn't JSON-aware. A
    string value containing a single unbalanced '{' throws off that count
    enough that depth never returns to 0, so strategy 4 finds nothing. The
    final regex fallback (first '{' to the *last* '}' in the whole text,
    parsed by the real json module) recovers the correct object anyway.
    """
    text = '{"note": "uses only { without a matching close brace"}'
    assert parse_json_response(text) == {"note": "uses only { without a matching close brace"}


# ---------------------------------------------------------------------------
# complete_with_retry
# ---------------------------------------------------------------------------


def test_complete_with_retry_succeeds_after_transient_failures() -> None:
    client = AsyncMock()
    client.complete.side_effect = [RuntimeError("rate limited"), RuntimeError("timeout"), "ok"]
    result = asyncio.run(complete_with_retry(client, system="s", user="u", backoff=0))
    assert result == "ok"
    assert client.complete.await_count == 3


def test_complete_with_retry_raises_last_exception_when_exhausted() -> None:
    client = AsyncMock()
    client.complete.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(complete_with_retry(client, system="s", user="u", retries=2, backoff=0))
    assert client.complete.await_count == 3  # initial + 2 retries
