"""Unit tests for src/nugget/subagent.py helpers."""

import json
import pytest
from pathlib import Path

from nugget.subagent import (
    build_child_system_prompt,
    save_subagent_call,
    _render_value,
)


# ── _render_value ─────────────────────────────────────────────────────────────

def test_render_string_verbatim():
    assert _render_value("hello world") == "hello world"

def test_render_dict_as_json():
    result = _render_value({"key": "val"})
    assert json.loads(result) == {"key": "val"}

def test_render_list_as_json():
    result = _render_value([1, 2, 3])
    assert json.loads(result) == [1, 2, 3]

def test_render_other_as_repr():
    assert _render_value(42) == "42"
    assert _render_value(None) == "None"


# ── build_child_system_prompt ─────────────────────────────────────────────────

def test_build_no_context():
    prompt, truncated = build_child_system_prompt(
        task="do a thing",
        context={},
        base_prompt="You are helpful.",
        max_context_bytes=32768,
    )
    assert "## Task" in prompt
    assert "do a thing" in prompt
    assert "## Provided context" not in prompt
    assert not truncated

def test_build_with_string_context():
    prompt, truncated = build_child_system_prompt(
        task="summarise",
        context={"matches": "line1\nline2"},
        base_prompt="Base.",
        max_context_bytes=32768,
    )
    assert "### matches" in prompt
    assert "line1" in prompt
    assert "## Task" in prompt
    assert not truncated

def test_build_with_dict_context():
    prompt, truncated = build_child_system_prompt(
        task="analyse",
        context={"data": {"count": 3}},
        base_prompt="Base.",
        max_context_bytes=32768,
    )
    assert "### data" in prompt
    assert '"count": 3' in prompt
    assert not truncated

def test_build_truncates_oversized_context():
    big_value = "x" * 100_000
    prompt, truncated = build_child_system_prompt(
        task="do it",
        context={"big": big_value},
        base_prompt="Base.",
        max_context_bytes=500,
    )
    assert truncated
    assert "[truncated" in prompt

def test_build_base_prompt_appears_first():
    prompt, _ = build_child_system_prompt(
        task="t",
        context={},
        base_prompt="CUSTOM BASE",
        max_context_bytes=32768,
    )
    assert prompt.startswith("CUSTOM BASE")


# ── save_subagent_call ────────────────────────────────────────────────────────

def test_save_and_load(tmp_path):
    data = {"call_id": "abc123", "task": "hello", "messages": []}
    save_subagent_call("parent01", "abc123", tmp_path, data)

    out = tmp_path / "parent01" / "subagents" / "abc123.json"
    assert out.exists()
    assert json.loads(out.read_text()) == data

def test_save_creates_directory(tmp_path):
    sessions_dir = tmp_path / "sessions"
    save_subagent_call("p1", "c1", sessions_dir, {"x": 1})
    assert (sessions_dir / "p1" / "subagents" / "c1.json").exists()

def test_list_sessions_unaffected_by_subagent_dir(tmp_path):
    """Session.list_sessions() must not return subagent JSON files."""
    from nugget.session import Session

    # Create a real session
    s = Session.new(tmp_path)
    s.save()

    # Create a subagent file in a subdirectory
    save_subagent_call(s.id, "sub01", tmp_path, {"task": "x"})

    sessions = Session.list_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["id"] == s.id

def test_load_subagents(tmp_path):
    from nugget.session import Session

    save_subagent_call("p1", "c1", tmp_path, {"call_id": "c1", "task": "a"})
    save_subagent_call("p1", "c2", tmp_path, {"call_id": "c2", "task": "b"})

    results = Session.load_subagents("p1", tmp_path)
    assert len(results) == 2
    call_ids = {r["call_id"] for r in results}
    assert call_ids == {"c1", "c2"}

def test_load_subagents_empty_when_none(tmp_path):
    from nugget.session import Session

    results = Session.load_subagents("no-such-parent", tmp_path)
    assert results == []
