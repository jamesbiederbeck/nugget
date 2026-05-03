"""Unit tests for spawn_agent — all backend calls are mocked."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nugget.subagent import _tool_ctx, _session_id, _depth


def _make_ctx(tmp_path, bindings=None, max_depth=2):
    """Build a minimal harness context for inject into _tool_ctx."""
    from nugget.config import Config
    cfg = Config({"sessions_dir": str(tmp_path)})

    backend = MagicMock()
    backend.run.return_value = ("child answer", None, [], "stop")

    return {
        "backend": backend,
        "bindings": bindings or {},
        "config": cfg,
    }


def _run(args, ctx, session_id="parent01"):
    from nugget.tools.spawn_agent import execute
    sid_token = _session_id.set(session_id)
    ctx_token = _tool_ctx.set(ctx)
    try:
        return execute(args)
    finally:
        _session_id.reset(sid_token)
        _tool_ctx.reset(ctx_token)


# ── Basic execution ───────────────────────────────────────────────────────────

def test_pure_reasoning_spawn(tmp_path):
    ctx = _make_ctx(tmp_path)
    result = _run({"task": "what is 2+2?"}, ctx)

    assert result["answer"] == "child answer"
    assert result["finish_reason"] == "stop"
    assert result["tool_calls"] == 0
    assert not result["truncated_context"]

    ctx["backend"].run.assert_called_once()
    call_kwargs = ctx["backend"].run.call_args
    # No tools passed — pure reasoning
    assert call_kwargs.kwargs["tool_schemas"] == []

def test_task_required():
    from nugget.tools.spawn_agent import execute
    result = execute({})
    assert "error" in result

def test_no_harness_context_returns_error():
    from nugget.tools.spawn_agent import execute
    result = execute({"task": "x"})
    assert "error" in result
    assert "harness context" in result["error"]


# ── context_vars resolution ───────────────────────────────────────────────────

def test_context_vars_resolved_from_bindings(tmp_path):
    ctx = _make_ctx(tmp_path, bindings={"matches": "line1\nline2"})
    result = _run({"task": "summarise", "context_vars": ["matches"]}, ctx)
    assert result["answer"] == "child answer"

    # System prompt should contain the bound value
    call_kwargs = ctx["backend"].run.call_args.kwargs
    assert "line1" in call_kwargs["system_prompt"]
    assert "### matches" in call_kwargs["system_prompt"]

def test_unbound_context_var_returns_error(tmp_path):
    ctx = _make_ctx(tmp_path, bindings={})
    result = _run({"task": "t", "context_vars": ["missing"]}, ctx)
    assert "error" in result
    assert "$missing" in result["error"]
    ctx["backend"].run.assert_not_called()


# ── Tool allowlist ────────────────────────────────────────────────────────────

def test_tool_allowlist_filters_schemas(tmp_path):
    ctx = _make_ctx(tmp_path)
    with patch("nugget.tools.schemas") as mock_schemas:
        mock_schemas.return_value = [{"function": {"name": "calculator"}}]
        result = _run({"task": "t", "tools": ["calculator"]}, ctx)

    mock_schemas.assert_called_once_with(include=["calculator"])
    call_kwargs = ctx["backend"].run.call_args.kwargs
    assert len(call_kwargs["tool_schemas"]) == 1

def test_empty_tools_means_no_schemas(tmp_path):
    ctx = _make_ctx(tmp_path)
    result = _run({"task": "t"}, ctx)
    call_kwargs = ctx["backend"].run.call_args.kwargs
    assert call_kwargs["tool_schemas"] == []


# ── Recursion depth cap ───────────────────────────────────────────────────────

def test_depth_cap_enforced(tmp_path):
    ctx = _make_ctx(tmp_path, max_depth=2)
    depth_token = _depth.set(2)
    try:
        result = _run({"task": "t"}, ctx)
    finally:
        _depth.reset(depth_token)

    assert result.get("_denied") is True
    assert "depth" in result["reason"]
    ctx["backend"].run.assert_not_called()

def test_depth_within_limit_succeeds(tmp_path):
    ctx = _make_ctx(tmp_path)
    depth_token = _depth.set(1)
    try:
        result = _run({"task": "t"}, ctx)
    finally:
        _depth.reset(depth_token)

    assert "answer" in result


# ── Oversized context truncation ──────────────────────────────────────────────

def test_oversized_context_truncated(tmp_path):
    from nugget.config import Config
    cfg = Config({"sessions_dir": str(tmp_path), "subagent": {"max_context_bytes": 100}})

    backend = MagicMock()
    backend.run.return_value = ("ok", None, [], "stop")
    ctx = {"backend": backend, "bindings": {}, "config": cfg}

    big_ctx = {"data": "x" * 10_000}
    result = _run({"task": "t", "context": big_ctx}, ctx)

    assert result["truncated_context"] is True
    call_kwargs = backend.run.call_args.kwargs
    assert "[truncated" in call_kwargs["system_prompt"]


# ── Persistence ───────────────────────────────────────────────────────────────

def test_subagent_call_persisted(tmp_path):
    ctx = _make_ctx(tmp_path)
    result = _run({"task": "hello"}, ctx, session_id="parent01")

    subagent_dir = tmp_path / "parent01" / "subagents"
    files = list(subagent_dir.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["task"] == "hello"
    assert data["parent_session_id"] == "parent01"


# ── return_thinking ───────────────────────────────────────────────────────────

def test_return_thinking_included(tmp_path):
    ctx = _make_ctx(tmp_path)
    ctx["backend"].run.return_value = ("answer", "deep thought", [], "stop")

    result = _run({"task": "t", "return_thinking": True}, ctx)
    assert result.get("thinking") == "deep thought"

def test_return_thinking_excluded_by_default(tmp_path):
    ctx = _make_ctx(tmp_path)
    ctx["backend"].run.return_value = ("answer", "deep thought", [], "stop")

    result = _run({"task": "t"}, ctx)
    assert "thinking" not in result


# ── Output routing pass-through (output is handled by the backend, not execute) ──

def test_result_shape_has_expected_keys(tmp_path):
    ctx = _make_ctx(tmp_path)
    result = _run({"task": "t"}, ctx)

    assert set(result.keys()) >= {"answer", "tool_calls", "finish_reason", "truncated_context"}
