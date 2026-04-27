"""
Tests for the OpenRouter backend.

All network calls are mocked so these tests run without an API key.
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest

from nugget.backends.openrouter import OpenRouterBackend
from nugget.backends import BackendError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(**overrides):
    cfg = MagicMock()
    cfg.get = lambda k, default=None: overrides.get(k, {
        "temperature": 0.7,
        "max_tokens": 2048,
        "openrouter_api_key": "sk-or-test",
        "openrouter_model": "openai/gpt-4o-mini",
        "debug": False,
    }.get(k, default))
    return cfg


def _chat_response(content="Hello!", tool_calls=None):
    """Build a minimal non-streaming chat-completions response body."""
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": "stop"}],
    }


def _sse_lines(*chunks, done=True):
    """Convert a sequence of delta dicts to SSE byte lines."""
    lines = []
    for chunk in chunks:
        lines.append(f"data: {json.dumps(chunk)}".encode())
    if done:
        lines.append(b"data: [DONE]")
    return lines


def _text_chunk(content):
    return {"choices": [{"delta": {"content": content}, "finish_reason": None}]}


def _tool_call_chunk(index, call_id, name, arguments_part, finish_reason=None):
    return {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": index,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments_part},
                }]
            },
            "finish_reason": finish_reason,
        }]
    }


def _simple_tool_executor(name, args):
    if name == "calculator":
        return {"result": eval(args.get("expression", "0")), "expression": args.get("expression")}
    return {"error": f"unknown tool: {name}"}


# ── Simple completion (no tools) ──────────────────────────────────────────────

def test_simple_completion(mocker):
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")
    mock_resp = MagicMock()
    mock_resp.json.return_value = _chat_response("The answer is 42.")
    mock_post.return_value = mock_resp

    text, thinking, exchanges, finish = backend.run(
        messages=[{"role": "user", "content": "What is 6 * 7?"}],
        tool_schemas=[],
        tool_executor=_simple_tool_executor,
        system_prompt="You are helpful.",
    )
    assert text == "The answer is 42."
    assert thinking is None
    assert exchanges == []
    assert finish == "stop"


# ── Tool call → result → final text ──────────────────────────────────────────

def test_single_tool_call(mocker):
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")

    # First call: model asks to use calculator
    first_resp = MagicMock()
    first_resp.json.return_value = _chat_response(
        content="",
        tool_calls=[{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression": "6*7"}'},
        }],
    )
    # Second call: model produces final answer
    second_resp = MagicMock()
    second_resp.json.return_value = _chat_response("The answer is 42.")
    mock_post.side_effect = [first_resp, second_resp]

    tool_calls_seen = []
    def on_tool_call(name, args):
        tool_calls_seen.append((name, args))

    text, thinking, exchanges, finish = backend.run(
        messages=[{"role": "user", "content": "What is 6 * 7?"}],
        tool_schemas=[{"type": "function", "function": {"name": "calculator", "parameters": {}}}],
        tool_executor=_simple_tool_executor,
        system_prompt="You are helpful.",
        on_tool_call=on_tool_call,
    )
    assert text == "The answer is 42."
    assert len(exchanges) == 1
    assert exchanges[0]["name"] == "calculator"
    assert exchanges[0]["result"]["result"] == 42
    assert tool_calls_seen == [("calculator", {"expression": "6*7"})]


# ── Multi-tool loop ───────────────────────────────────────────────────────────

def test_multi_tool_loop(mocker):
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")

    calc_tc = lambda expr, i: {
        "id": f"call_{i}",
        "type": "function",
        "function": {"name": "calculator", "arguments": json.dumps({"expression": expr})},
    }

    r1 = MagicMock()
    r1.json.return_value = _chat_response("", tool_calls=[calc_tc("2+2", 1)])
    r2 = MagicMock()
    r2.json.return_value = _chat_response("", tool_calls=[calc_tc("3*3", 2)])
    r3 = MagicMock()
    r3.json.return_value = _chat_response("Done!")
    mock_post.side_effect = [r1, r2, r3]

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "Calc two things"}],
        tool_schemas=[],
        tool_executor=_simple_tool_executor,
        system_prompt="",
    )
    assert text == "Done!"
    assert len(exchanges) == 2
    assert exchanges[0]["result"]["result"] == 4
    assert exchanges[1]["result"]["result"] == 9


# ── Sink routing pass-through (output meta-arg) ───────────────────────────────

def test_sink_routing_display(mocker):
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")

    # Tool call with output="display" meta-arg
    r1 = MagicMock()
    r1.json.return_value = _chat_response("", tool_calls=[{
        "id": "call_1",
        "type": "function",
        "function": {"name": "calculator", "arguments": '{"expression": "5+5", "output": "display"}'},
    }])
    r2 = MagicMock()
    r2.json.return_value = _chat_response("The result was displayed.")
    mock_post.side_effect = [r1, r2]

    routed = []
    def on_tool_routed(name, result, sink):
        routed.append((name, result, sink))

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "Show me 5+5"}],
        tool_schemas=[],
        tool_executor=_simple_tool_executor,
        system_prompt="",
        on_tool_routed=on_tool_routed,
    )
    assert text == "The result was displayed."
    assert len(routed) == 1
    assert routed[0][0] == "calculator"
    # The result fed back to the model is a status stub, not the raw result
    assert exchanges[0]["result"] == {"status": "ok", "output": "sent to display"}


# ── Error: HTTP 401 ───────────────────────────────────────────────────────────

def test_http_error_raises_backend_error(mocker):
    import requests as req_mod
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req_mod.HTTPError("401 Unauthorized")
    mock_post.return_value = mock_resp

    with pytest.raises(BackendError):
        backend.run(
            messages=[{"role": "user", "content": "hi"}],
            tool_schemas=[],
            tool_executor=_simple_tool_executor,
            system_prompt="",
        )


# ── Error: network failure ────────────────────────────────────────────────────

def test_network_error_raises_backend_error(mocker):
    import requests as req_mod
    backend = OpenRouterBackend(_make_config())
    mocker.patch.object(backend._session, "post", side_effect=req_mod.ConnectionError("no network"))

    with pytest.raises(BackendError):
        backend.run(
            messages=[{"role": "user", "content": "hi"}],
            tool_schemas=[],
            tool_executor=_simple_tool_executor,
            system_prompt="",
        )


# ── Streaming: simple text ────────────────────────────────────────────────────

def test_streaming_simple_text(mocker):
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")
    mock_resp = MagicMock()
    mock_resp.iter_lines.return_value = _sse_lines(
        _text_chunk("Hello"),
        _text_chunk(" world"),
    )
    mock_post.return_value = mock_resp

    tokens = []
    text, thinking, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        tool_executor=_simple_tool_executor,
        system_prompt="",
        on_token=lambda t: tokens.append(t),
    )
    assert text == "Hello world"
    assert tokens == ["Hello", " world"]
    assert exchanges == []


# ── Streaming: tool call delta merge ─────────────────────────────────────────

def test_streaming_tool_call_delta_merge(mocker):
    """Tool-call arguments are streamed as partial JSON; they must be merged."""
    backend = OpenRouterBackend(_make_config())
    mock_post = mocker.patch.object(backend._session, "post")

    # First response: streaming tool call delta
    sse_resp = MagicMock()
    sse_resp.iter_lines.return_value = _sse_lines(
        _tool_call_chunk(0, "call_1", "calculator", '{"expression":'),
        _tool_call_chunk(0, "call_1", "", ' "2+2"}'),
    )

    # Second response: final text (non-streaming)
    final_resp = MagicMock()
    final_resp.json.return_value = _chat_response("The answer is 4.")
    mock_post.side_effect = [sse_resp, final_resp]

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        tool_schemas=[{"type": "function", "function": {"name": "calculator", "parameters": {}}}],
        tool_executor=_simple_tool_executor,
        system_prompt="",
        on_token=lambda _: None,  # enable streaming for first call
    )
    assert len(exchanges) == 1
    assert exchanges[0]["name"] == "calculator"
    assert exchanges[0]["result"]["result"] == 4


# ── make_backend integration ──────────────────────────────────────────────────

def test_make_backend_openrouter():
    from nugget.backends import make_backend
    cfg = MagicMock()
    cfg.get = lambda k, default=None: {"backend": "openrouter", "openrouter_api_key": "x"}.get(k, default)
    backend = make_backend(cfg)
    assert isinstance(backend, OpenRouterBackend)
