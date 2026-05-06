"""
Tests for render_output.execute().

These tests call execute() directly, so `output` is visible in args (the
backend would normally pop it as a meta-arg). This covers the "direct call"
code path and lets us unit-test all sink types.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nugget.tools.render_output import execute


# ── Helpers ───────────────────────────────────────────────────────────────────

def _calc_result(n: int = 4) -> dict:
    return {"result": n, "expression": f"2+{n - 2}"}


# ── display sink ──────────────────────────────────────────────────────────────

def test_display_sink_returns_status_stub():
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "2+2"},
        "output": "display",
    })
    assert result == {"status": "ok", "output": "sent to display"}


def test_display_jmespath_sink():
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "3*3"},
        "output": "display:result",
    })
    assert result == {"status": "ok", "output": "sent to display"}


# ── file sink ─────────────────────────────────────────────────────────────────

def test_file_sink_writes_json(tmp_path):
    out_file = tmp_path / "calc_result.json"
    # Allow the tmp_path directory explicitly so the test doesn't depend on
    # the default sink rules (which only auto-allow /tmp/nugget and $CWD).
    with patch("nugget.tools.render_output.check_file_sink", return_value=("allow", "allowed for test")):
        result = execute({
            "tool_name": "calculator",
            "tool_args": {"expression": "5+5"},
            "output": f"file:{out_file}",
        })
    assert result["status"] == "ok"
    assert "written to" in result["output"]
    written = json.loads(out_file.read_text())
    assert written["result"] == 10


def test_file_sink_approval_deny(tmp_path):
    out_file = tmp_path / "denied.json"
    # Patch check_file_sink to always deny
    with patch("nugget.tools.render_output.check_file_sink", return_value=("deny", "blocked by policy")):
        result = execute({
            "tool_name": "calculator",
            "tool_args": {"expression": "1+1"},
            "output": f"file:{out_file}",
        })
    assert result["status"] == "denied"
    assert "reason" in result


# ── $var sink ─────────────────────────────────────────────────────────────────

def test_var_sink_returns_bound_stub():
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "7+3"},
        "output": "$myresult",
    })
    assert result == {"status": "ok", "output": "bound to $myresult"}


# ── no output (inline / backend-controlled) ───────────────────────────────────

def test_no_output_returns_wrapped_result():
    # When output is omitted the backend handles routing; execute() returns a
    # display-format wrapper so the display layer can render it correctly.
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "2+2"},
    })
    assert "_display_format" in result
    assert result["_content"]["result"] == 4


# ── unknown wrapped tool ──────────────────────────────────────────────────────

def test_unknown_tool_returns_error():
    result = execute({
        "tool_name": "nonexistent_tool_xyz",
        "tool_args": {},
        "output": "display",
    })
    assert result["status"] == "error"
    assert "unknown tool" in result["reason"]


# ── approval-denied wrapped tool ──────────────────────────────────────────────

def test_approval_denied_tool():
    # Patch the tool gate to always deny
    with patch("nugget.tools.render_output.tool_registry.list_names", return_value=["deny_tool"]), \
         patch("nugget.tools.render_output.tool_registry.gate", return_value="deny"):
        result = execute({
            "tool_name": "deny_tool",
            "tool_args": {},
            "output": "display",
        })
    assert result["status"] == "error"
    assert "blocked by approval policy" in result["reason"]


def test_approval_ask_tool_is_denied():
    # "ask" cannot be resolved interactively inside execute(); treat as deny
    with patch("nugget.tools.render_output.tool_registry.list_names", return_value=["ask_tool"]), \
         patch("nugget.tools.render_output.tool_registry.gate", return_value="ask"):
        result = execute({
            "tool_name": "ask_tool",
            "tool_args": {},
            "output": "display",
        })
    assert result["status"] == "error"
    assert "non-interactive" in result["reason"]


# ── missing required arg ──────────────────────────────────────────────────────

def test_missing_tool_name():
    result = execute({"tool_args": {}, "output": "display"})
    assert result["status"] == "error"
    assert "tool_name" in result["reason"]


def test_tool_args_not_a_dict():
    result = execute({"tool_name": "calculator", "tool_args": "bad", "output": "display"})
    assert result["status"] == "error"
    assert "tool_args" in result["reason"]


# ── invalid sink ──────────────────────────────────────────────────────────────

def test_invalid_sink_rejected():
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "1+1"},
        "output": "invalid_sink_format",
    })
    assert result["status"] == "error"
    assert "unknown sink" in result["reason"]


def test_empty_display_path_rejected():
    result = execute({
        "tool_name": "calculator",
        "tool_args": {"expression": "1+1"},
        "output": "display:",
    })
    assert result["status"] == "error"
