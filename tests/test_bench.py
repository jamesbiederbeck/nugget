"""Tests for bench/run.py — constraint engine and target resolution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bench"))

from run import _resolve_path, resolve_target, evaluate_constraint


# ── _resolve_path ─────────────────────────────────────────────────────────────

def test_resolve_simple_key():
    assert _resolve_path({"key": "val"}, "key") == "val"

def test_resolve_missing_key():
    assert _resolve_path({"key": "val"}, "missing") is None

def test_resolve_array_value_returns_json():
    result = _resolve_path({"items": ["a", "b"]}, "items")
    assert result == '["a", "b"]'

def test_resolve_array_index():
    assert _resolve_path({"items": ["a", "b"]}, "items[0]") == "a"

def test_resolve_array_index_out_of_bounds():
    assert _resolve_path({"items": ["a"]}, "items[5]") is None

def test_resolve_nested_dict():
    obj = {"outer": {"inner": "deep"}}
    assert _resolve_path(obj, "outer.inner") == "deep"

def test_resolve_nested_array_index():
    obj = {"results": [{"name": "foo"}, {"name": "bar"}]}
    assert _resolve_path(obj, "results[1].name") == "bar"

def test_resolve_dict_value_returns_json():
    obj = {"meta": {"count": 3}}
    import json
    result = _resolve_path(obj, "meta")
    assert json.loads(result) == {"count": 3}

def test_resolve_none_obj():
    assert _resolve_path(None, "key") is None


# ── resolve_target ────────────────────────────────────────────────────────────

def _make_calls(*calls):
    return [{"name": n, "args": a} for n, a in calls]

def test_resolve_tool_call_name():
    calls = _make_calls(("grep_search", {"pattern": "foo"}))
    assert resolve_target("tool_call[0].name", calls, "", None) == "grep_search"

def test_resolve_tool_call_simple_arg():
    calls = _make_calls(("spawn_agent", {"task": "do it"}))
    assert resolve_target("tool_call[0].args.task", calls, "", None) == "do it"

def test_resolve_tool_call_array_arg_as_json():
    calls = _make_calls(("spawn_agent", {"context_vars": ["matches", "data"]}))
    result = resolve_target("tool_call[0].args.context_vars", calls, "", None)
    import json
    assert json.loads(result) == ["matches", "data"]

def test_resolve_tool_call_array_index():
    calls = _make_calls(("spawn_agent", {"context_vars": ["matches"]}))
    assert resolve_target("tool_call[0].args.context_vars[0]", calls, "", None) == "matches"

def test_resolve_tool_call_out_of_bounds():
    calls = _make_calls(("tool", {}))
    assert resolve_target("tool_call[5].name", calls, "", None) is None

def test_resolve_response():
    assert resolve_target("response", [], "hello", None) == "hello"

def test_resolve_reasoning():
    assert resolve_target("reasoning", [], "", "thought") == "thought"


# ── evaluate_constraint ───────────────────────────────────────────────────────

def test_regex_matches_within_json_array():
    # Simulates asserting context_vars contains "matches"
    extracted = '["matches", "data"]'
    assert evaluate_constraint("regex", "matches", extracted)

def test_regex_no_match():
    assert not evaluate_constraint("regex", "^exact$", "not exact")

def test_present():
    assert evaluate_constraint("present", None, "something")
    assert not evaluate_constraint("present", None, None)

def test_absent():
    assert evaluate_constraint("absent", None, None)
    assert not evaluate_constraint("absent", None, "something")
