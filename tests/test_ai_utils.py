"""Tests for parse_json_response's multi-strategy JSON extraction."""

from src.ai.utils import parse_json_response


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
