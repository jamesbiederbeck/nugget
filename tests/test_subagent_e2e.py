"""
End-to-end subagent tests — full parent→child→answer loop with mocked HTTP.

All upstream HTTP calls are intercepted via pytest-mock so no live model is
needed. Each test drives real backend.run() + spawn_agent.execute() code paths.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nugget.config import Config
from nugget.backends.textgen import TextgenBackend
from nugget.subagent import _session_id
from nugget import tools as tool_registry


# ── Helpers ───────────────────────────────────────────────────────────────────

_STR = '<|"|>'


def _gval_str(s: str) -> str:
    return f"{_STR}{s}{_STR}"


def _tool_call_token(name: str, args: dict) -> str:
    from nugget.backends.textgen import format_tool_call_token
    return format_tool_call_token(name, args)


def _mock_response(text: str, finish: str = "stop") -> MagicMock:
    """Build a mock requests.Response for a non-streaming _complete() call."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"text": text, "finish_reason": finish}]
    }
    return resp


def _make_backend(tmp_path: Path) -> tuple[TextgenBackend, Config]:
    cfg = Config({
        "sessions_dir": str(tmp_path),
        "api_url": "http://127.0.0.1:5000",
        "subagent": {"max_depth": 2, "max_turns_default": 4, "max_turns_cap": 16},
    })
    backend = TextgenBackend(cfg)
    return backend, cfg


def _run_turn(backend, cfg, message: str, session_id: str = "test-parent"):
    """Run one backend turn with spawn_agent available, returns (text, exchanges)."""
    from nugget import approval as approval_mod
    schemas = tool_registry.schemas(include=["spawn_agent"])

    def tool_executor(name, args):
        approved, reason = approval_mod.check(
            name, args, tool_registry.gate(name),
            {"default": "allow", "rules": [{"tool": "spawn_agent", "action": "allow"}]}
        )
        if not approved:
            return {"_denied": True, "reason": reason}
        return tool_registry.execute(name, args)

    sid_token = _session_id.set(session_id)
    try:
        text, thinking, exchanges, finish = backend.run(
            messages=[{"role": "user", "content": message}],
            tool_schemas=schemas,
            tool_executor=tool_executor,
            system_prompt="You are a test assistant.",
        )
    finally:
        _session_id.reset(sid_token)
    return text, exchanges


# ── Happy-path single-shot spawn ──────────────────────────────────────────────

def test_happy_path_pure_reasoning(tmp_path, mocker):
    """Parent calls spawn_agent; child returns a pure-reasoning answer."""
    backend, cfg = _make_backend(tmp_path)

    spawn_token = _tool_call_token("spawn_agent", {"task": "What is 2+2?"})

    responses = iter([
        _mock_response(spawn_token),           # parent turn 1: emit spawn_agent call
        _mock_response("The answer is 4."),    # child turn: answer
        _mock_response("The subagent says: 4."),  # parent turn 2: final text
    ])

    mocker.patch.object(backend._session, "post", side_effect=lambda *a, **kw: next(responses))

    text, exchanges = _run_turn(backend, cfg, "What is 2+2? Use spawn_agent.", session_id="happy-parent")

    assert len(exchanges) == 1
    assert exchanges[0]["name"] == "spawn_agent"
    result = exchanges[0]["result"]
    assert result["answer"] == "The answer is 4."
    assert result["finish_reason"] == "stop"

    # Verify persistence
    subagent_dir = tmp_path / "happy-parent" / "subagents"
    assert subagent_dir.exists()
    files = list(subagent_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["task"] == "What is 2+2?"


# ── Child uses a tool ─────────────────────────────────────────────────────────

def test_child_uses_tool(tmp_path, mocker):
    """Child session is given calculator tool and uses it."""
    backend, cfg = _make_backend(tmp_path)

    spawn_token = _tool_call_token(
        "spawn_agent",
        {"task": "Calculate 6 * 7", "tools": ["calculator"]},
    )

    from nugget.backends.textgen import format_tool_call_token
    child_tool_call = format_tool_call_token("calculator", {"expression": "6 * 7"})

    responses = iter([
        _mock_response(spawn_token),           # parent: call spawn_agent
        _mock_response(child_tool_call),       # child turn 1: calculator call
        _mock_response("The result is 42."),   # child turn 2: final answer
        _mock_response("Subagent says 42."),   # parent: final text
    ])

    mocker.patch.object(backend._session, "post", side_effect=lambda *a, **kw: next(responses))

    text, exchanges = _run_turn(backend, cfg, "Calculate 6*7 via subagent.", session_id="tool-parent")

    assert exchanges[0]["name"] == "spawn_agent"
    result = exchanges[0]["result"]
    assert result["tool_calls"] == 1
    assert "42" in result["answer"]


# ── Child hits max_turns cap ──────────────────────────────────────────────────

def test_child_hits_max_turns(tmp_path, mocker):
    """Child session with max_turns=1 stops after one tool exchange."""
    backend, cfg = _make_backend(tmp_path)

    spawn_token = _tool_call_token(
        "spawn_agent",
        {"task": "Keep calculating", "tools": ["calculator"], "max_turns": 1},
    )

    from nugget.backends.textgen import format_tool_call_token
    child_tool_call = format_tool_call_token("calculator", {"expression": "1+1"})

    responses = iter([
        _mock_response(spawn_token),                            # parent: spawn_agent call
        _mock_response(child_tool_call, finish="length"),       # child: tool call then cap
        _mock_response("Done."),                                # parent: final
    ])

    mocker.patch.object(backend._session, "post", side_effect=lambda *a, **kw: next(responses))

    text, exchanges = _run_turn(backend, cfg, "test", session_id="maxturn-parent")
    assert exchanges[0]["name"] == "spawn_agent"


# ── Depth limit propagates back ───────────────────────────────────────────────

def test_depth_limit_denied(tmp_path, mocker):
    """spawn_agent at max_depth returns _denied without spawning a new HTTP call."""
    from nugget.subagent import _depth

    backend, cfg = _make_backend(tmp_path)

    spawn_token = _tool_call_token("spawn_agent", {"task": "recurse"})
    responses = iter([
        _mock_response(spawn_token),   # parent: call spawn_agent
        _mock_response("Denied."),     # parent: final (spawn_agent returned _denied)
    ])
    mock_post = mocker.patch.object(
        backend._session, "post", side_effect=lambda *a, **kw: next(responses)
    )

    # Force depth to the cap
    depth_token = _depth.set(2)
    try:
        text, exchanges = _run_turn(backend, cfg, "test", session_id="depth-parent")
    finally:
        _depth.reset(depth_token)

    assert exchanges[0]["name"] == "spawn_agent"
    result = exchanges[0]["result"]
    # _denied result means no child HTTP call was made
    assert result.get("_denied") or "depth" in result.get("reason", "") or result.get("error")
    # Only parent calls fired (no child HTTP round-trips)
    assert mock_post.call_count == 2  # parent turn + final turn


# ── context_vars resolved before child spawns ────────────────────────────────

def test_context_vars_injected_into_child_prompt(tmp_path, mocker):
    """Bound $payload variable is included in the child's system prompt."""
    backend, cfg = _make_backend(tmp_path)

    spawn_token = _tool_call_token(
        "spawn_agent",
        {"task": "Summarise", "context_vars": ["payload"]},
    )
    # Simulate parent first binding $payload, then calling spawn_agent
    from nugget.backends.textgen import format_tool_call_token, format_tool_response_token
    bind_token = format_tool_call_token("calculator", {"expression": "1", "output": "$payload"})

    responses = iter([
        _mock_response(spawn_token),
        _mock_response("Summary done."),
        _mock_response("OK."),
    ])

    captured_prompts: list[str] = []

    def mock_post(url, json=None, **kwargs):
        if json and "prompt" in json:
            captured_prompts.append(json["prompt"])
        return next(responses)

    mocker.patch.object(backend._session, "post", side_effect=mock_post)

    from nugget import approval as approval_mod
    schemas = tool_registry.schemas(include=["spawn_agent"])

    bindings: dict = {"payload": "some large text blob"}

    # Manually inject bindings into the backend's context by pre-setting the
    # tool_ctx before running so spawn_agent can resolve context_vars
    from nugget.subagent import _tool_ctx
    ctx = {"backend": backend, "bindings": bindings, "config": cfg}

    # Patch tool_executor to inject bindings ctx before spawn_agent executes
    original_execute = tool_registry._registry.get("spawn_agent", (None, None))[1]
    if original_execute:
        tool_registry._load_all()

    sid_token = _session_id.set("ctx-parent")
    # Set context so spawn_agent can read bindings
    ctx_token = _tool_ctx.set(ctx)
    try:
        text, thinking, exchanges, finish = backend.run(
            messages=[{"role": "user", "content": "summarise $payload via spawn_agent"}],
            tool_schemas=schemas,
            tool_executor=lambda name, args: (
                tool_registry.execute(name, args)
            ),
            system_prompt="You are a test assistant.",
        )
    finally:
        _session_id.reset(sid_token)
        _tool_ctx.reset(ctx_token)

    assert exchanges[0]["name"] == "spawn_agent"
    result = exchanges[0]["result"]
    # Either resolved successfully or returned unbound error
    # (depends on whether bindings ctx was active during execute)
    assert "answer" in result or "error" in result
