from pathlib import Path

import pytest
from nugget.backends.textgen import (
    _gval,
    _parse_gval,
    _route_tool_result,
    parse_tool_call,
    parse_thinking,
    format_tool_declaration,
    format_tool_call_token,
    format_tool_response_token,
    build_prompt,
)

_STR = '<|"|>'


# ── _gval serialisation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("hello", f"{_STR}hello{_STR}"),
    ("", f"{_STR}{_STR}"),
    (True, "true"),
    (False, "false"),
    (None, "null"),
    (42, "42"),
    (3.14, "3.14"),
    ([], "[]"),
    ({}, "{}"),
    (["a", "b"], f"[{_STR}a{_STR},{_STR}b{_STR}]"),
    ({"k": "v"}, f"{{k:{_STR}v{_STR}}}"),
    ({"x": 1, "y": True}, "{x:1,y:true}"),
])
def test_gval_primitives(value, expected):
    assert _gval(value) == expected


def test_gval_nested():
    result = _gval({"args": {"n": 5, "flag": True}})
    assert result == "{args:{n:5,flag:true}}"


def test_gval_list_of_dicts():
    result = _gval([{"a": 1}, {"b": 2}])
    assert result == "[{a:1},{b:2}]"


# ── _parse_gval parsing ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "hello",
    "",
    True,
    False,
    None,
    42,
    [],
    ["a", "b"],
    {"k": "v"},
    {"x": 1, "y": True, "z": None},
    {"nested": {"a": [1, 2]}},
])
def test_parse_gval_roundtrip(value):
    assert _parse_gval(_gval(value)) == value


def test_parse_gval_string_with_braces():
    # Strings containing {} should survive the roundtrip
    value = "hello {world}"
    assert _parse_gval(_gval(value)) == value


def test_parse_gval_int():
    assert _parse_gval("42") == 42


def test_parse_gval_float():
    assert _parse_gval("3.14") == pytest.approx(3.14)


def test_parse_gval_true_false_null():
    assert _parse_gval("true") is True
    assert _parse_gval("false") is False
    assert _parse_gval("null") is None


# ── format_tool_* ─────────────────────────────────────────────────────────────

def test_format_tool_call_token():
    result = format_tool_call_token("shell", {"command": "ls"})
    assert result.startswith("<|tool_call>call:shell{")
    assert result.endswith("<tool_call|>")
    assert f"command:{_STR}ls{_STR}" in result


def test_format_tool_response_token_dict():
    result = format_tool_response_token("shell", {"stdout": "hi", "returncode": 0})
    assert result.startswith("<|tool_response>response:shell{")
    assert result.endswith("<tool_response|>")


def test_format_tool_response_token_scalar():
    result = format_tool_response_token("calc", 42)
    assert "result:42" in result


def test_format_tool_declaration():
    schema = {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate math",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    result = format_tool_declaration(schema)
    assert result.startswith("<|tool>declaration:calculator{")
    assert result.endswith("<tool|>")
    assert "description" in result


# ── parse_tool_call ───────────────────────────────────────────────────────────

def test_parse_tool_call_simple():
    text = f"<|tool_call>call:shell{{command:{_STR}ls -la{_STR}}}<tool_call|>"
    result = parse_tool_call(text)
    assert result is not None
    name, args = result
    assert name == "shell"
    assert args["command"] == "ls -la"


def test_parse_tool_call_no_match():
    assert parse_tool_call("just some text with no tool call") is None


def test_parse_tool_call_multiple_args():
    text = f"<|tool_call>call:memory{{operation:{_STR}store{_STR},key:{_STR}foo{_STR},value:{_STR}bar{_STR}}}<tool_call|>"
    result = parse_tool_call(text)
    assert result is not None
    name, args = result
    assert name == "memory"
    assert args["operation"] == "store"
    assert args["key"] == "foo"
    assert args["value"] == "bar"


def test_parse_tool_call_numeric_arg():
    text = f"<|tool_call>call:shell{{command:{_STR}sleep{_STR},timeout:5}}<tool_call|>"
    result = parse_tool_call(text)
    assert result is not None
    _, args = result
    assert args["timeout"] == 5


def test_parse_tool_call_embedded_in_text():
    text = (
        "Let me look that up. "
        f"<|tool_call>call:filebrowser{{operation:{_STR}cwd{_STR}}}<tool_call|>"
        " and then continue."
    )
    result = parse_tool_call(text)
    assert result is not None
    name, args = result
    assert name == "filebrowser"


# ── parse_thinking ────────────────────────────────────────────────────────────

def test_parse_thinking_with_block():
    text = "<|channel>thought\nI should check the weather.\n<channel|>The weather is nice."
    thinking, response = parse_thinking(text)
    assert thinking == "I should check the weather."
    assert response == "The weather is nice."


def test_parse_thinking_no_block():
    text = "Just a plain response."
    thinking, response = parse_thinking(text)
    assert thinking is None
    assert response == "Just a plain response."


def test_parse_thinking_strips_response():
    text = "<|channel>thought\nThinking...\n<channel|>  Final answer.  "
    thinking, response = parse_thinking(text)
    assert response == "Final answer."


def test_parse_thinking_with_trailing_tool_call():
    text = (
        f"<|channel>thought\nI need a tool.\n<channel|>"
        f"<|tool_call>call:shell{{command:{_STR}ls{_STR}}}<tool_call|>"
    )
    thinking, response = parse_thinking(text)
    assert thinking == "I need a tool."
    assert response == ""


def test_parse_thinking_multiline():
    text = "<|channel>thought\nLine one.\nLine two.\nLine three.\n<channel|>Answer."
    thinking, response = parse_thinking(text)
    assert "Line one." in thinking
    assert "Line three." in thinking
    assert response == "Answer."


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_structure_empty():
    prompt = build_prompt([], [], "You are helpful.", 0)
    assert "<|turn>system" in prompt
    assert "You are helpful." in prompt
    assert prompt.endswith("<|turn>model\n")


def test_build_prompt_user_turn():
    messages = [{"role": "user", "content": "Hello"}]
    prompt = build_prompt(messages, [], "sys", 0)
    assert "<|turn>user\nHello<turn|>" in prompt


def test_build_prompt_turn_order():
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello there", "tool_calls": []},
        {"role": "user", "content": "How are you?"},
    ]
    prompt = build_prompt(messages, [], "sys", 0)
    user_pos = [i for i, line in enumerate(prompt.split("\n")) if "user" in line]
    model_pos = [i for i, line in enumerate(prompt.split("\n")) if "model" in line]
    assert user_pos[0] < model_pos[0]


def test_build_prompt_thinking_effort_off():
    prompt = build_prompt([], [], "sys", 0)
    assert "<|think|>" not in prompt


def test_build_prompt_thinking_effort_on():
    prompt = build_prompt([], [], "sys", 2)
    assert "<|think|>" in prompt


def test_build_prompt_with_tools():
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "math",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]
    prompt = build_prompt([], schemas, "sys", 0)
    assert "calculator" in prompt
    assert "<|tool>" in prompt


# ── build_prompt routing-explanation gate ────────────────────────────────────
#
# Routing prose is now part of the model-facing protocol whenever any tools
# are exposed — it does not depend on per-tool metadata.

def test_build_prompt_routing_section_present_when_tools_exist():
    schemas = [
        {"type": "function", "function": {
            "name": "shell",
            "description": "run",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    ]
    prompt = build_prompt([], schemas, "sys", 0)
    assert "Tool output routing" in prompt
    assert 'output: "display"' in prompt


def test_build_prompt_routing_section_absent_when_no_tools():
    prompt = build_prompt([], [], "sys", 0)
    assert "Tool output routing" not in prompt


# ── _route_tool_result ───────────────────────────────────────────────────────

class _Calls:
    """Lightweight call-recorder."""
    def __init__(self):
        self.responses = []
        self.routed = []
        self.denied = []

    def on_response(self, name, result):
        self.responses.append((name, result))

    def on_routed(self, name, result, sink):
        self.routed.append((name, result, sink))

    def on_denied(self, name, reason):
        self.denied.append((name, reason))


def _route(**overrides):
    """Helper that fills in the boilerplate kwargs for _route_tool_result."""
    defaults = dict(
        on_tool_response=None,
        on_tool_routed=None,
        on_tool_denied=None,
        check_file_sink=None,
        sink_approval_prompt=None,
        approval_config=None,
        bindings={},
    )
    defaults.update(overrides)
    return _route_tool_result(**defaults)


def test_route_inline_sink_fires_on_tool_response():
    c = _Calls()
    result = {"value": 42}
    out = _route(
        name="calc", result=result, sink=None,
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
    )
    assert out is result
    assert c.responses == [("calc", result)]
    assert c.routed == []


def test_route_display_sink_fires_routed_not_response():
    c = _Calls()
    result = {"stdout": "lots of text", "returncode": 0}
    out = _route(
        name="shell", result=result, sink="display",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
    )
    assert c.responses == []
    assert c.routed == [("shell", result, "display")]
    assert out == {"status": "ok", "output": "sent to display"}
    token = format_tool_response_token("shell", out)
    assert "sent to display" in token
    assert "lots of text" not in token


def test_route_var_sink_binds_and_stubs():
    c = _Calls()
    bindings = {}
    result = {"files": ["a.txt", "b.txt"]}
    out = _route(
        name="ls", result=result, sink="$files",
        bindings=bindings,
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
    )
    assert bindings == {"files": result}
    assert out == {"status": "ok", "output": "bound to $files"}
    assert c.routed == [("ls", result, "var:$files")]
    assert c.responses == []


def test_route_var_sink_rebind_overwrites_and_flags_trace():
    c = _Calls()
    bindings = {"x": "old"}
    result = {"new": True}
    out = _route(
        name="t", result=result, sink="$x",
        bindings=bindings,
        on_tool_routed=c.on_routed,
    )
    assert bindings["x"] == result  # silent overwrite for the model
    assert out == {"status": "ok", "output": "bound to $x"}
    # Operator trace tags the rebind so it shows up in -v output.
    assert c.routed == [("t", result, "var:$x (rebind)")]


def test_route_file_sink_allow_writes_file(tmp_path):
    c = _Calls()
    target = tmp_path / "out.json"
    result = {"data": "hello"}

    def fake_check(abs_path, cwd, cfg):
        assert abs_path == target.resolve()
        return ("allow", "test allow")

    out = _route(
        name="dump", result=result, sink=f"file:{target}",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
        check_file_sink=fake_check, approval_config={},
    )
    assert target.exists()
    assert "hello" in target.read_text()
    assert c.responses == []
    assert len(c.routed) == 1
    assert c.routed[0][2].startswith("file:")
    assert out["status"] == "ok"
    assert "written to" in out["output"]


def test_route_file_sink_deny_does_not_write(tmp_path):
    c = _Calls()
    target = tmp_path / "out.json"
    out = _route(
        name="dump", result={"x": 1}, sink=f"file:{target}",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
        check_file_sink=lambda p, cw, cfg: ("deny", "outside safe zone"),
        approval_config={},
    )
    assert not target.exists()
    assert c.routed == []
    assert c.denied == [("dump", "outside safe zone")]
    assert out == {"status": "denied", "reason": "outside safe zone"}


def test_route_file_sink_ask_yes_writes(tmp_path):
    c = _Calls()
    target = tmp_path / "out.json"
    prompts = []

    def prompt(name, abs_path):
        prompts.append((name, abs_path))
        return True

    out = _route(
        name="dump", result={"v": 1}, sink=f"file:{target}",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
        check_file_sink=lambda p, cw, cfg: ("ask", "needs confirmation"),
        sink_approval_prompt=prompt, approval_config={},
    )
    assert target.exists()
    assert prompts and prompts[0][0] == "dump"
    assert prompts[0][1] == target.resolve()
    assert out["status"] == "ok"


def test_route_file_sink_ask_no_treated_as_deny(tmp_path):
    c = _Calls()
    target = tmp_path / "out.json"
    out = _route(
        name="dump", result={"v": 1}, sink=f"file:{target}",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
        check_file_sink=lambda p, cw, cfg: ("ask", "needs confirmation"),
        sink_approval_prompt=lambda n, p: False, approval_config={},
    )
    assert not target.exists()
    assert c.routed == []
    assert c.denied == [("dump", "user denied")]
    assert out == {"status": "denied", "reason": "user denied"}


def test_route_file_sink_creates_parent_dirs(tmp_path):
    target = tmp_path / "nested" / "deep" / "out.json"
    _route(
        name="dump", result={"x": 1}, sink=f"file:{target}",
        check_file_sink=lambda p, cw, cfg: ("allow", "ok"),
        approval_config={},
    )
    assert target.exists()


def test_route_file_sink_no_check_falls_back_to_inline(tmp_path):
    # When no policy is wired (e.g. web mode), file sinks degrade to inline.
    c = _Calls()
    target = tmp_path / "out.json"
    result = {"x": 1}
    out = _route(
        name="dump", result=result, sink=f"file:{target}",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
    )
    assert not target.exists()
    assert out is result
    assert c.responses == [("dump", result)]


# ── End-to-end run() loop ────────────────────────────────────────────────────
#
# Integration tests substitute a fake completion stream so the tool loop can
# be exercised without an upstream model server. They confirm that
# `_output` is parsed out of the call's args, variable references are
# substituted, and the stub (not the full result) is fed to the next
# completion.

class _FakeBackend:
    """Drives TextgenBackend.run() with a scripted sequence of completions."""
    def __init__(self, completions):
        self._completions = list(completions)
        self.prompts_seen = []

    def __call__(self, prompt, stop):
        self.prompts_seen.append(prompt)
        return self._completions.pop(0)


def _make_textgen_backend():
    from nugget.backends.textgen import TextgenBackend

    class _MinimalConfig:
        api_url = "http://nope"
        model = "x"
        temperature = 0.0
        max_tokens = 1
        top_p = 1.0
        top_k = 1
        debug = False

    return TextgenBackend(_MinimalConfig())


_DUMMY_SCHEMA = {
    "type": "function",
    "function": {"name": "x", "description": "x", "parameters": {"type": "object", "properties": {}, "required": []}},
}


def _schemas_for(name):
    return [{"type": "function", "function": {
        "name": name, "description": "x",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}]


def test_run_loop_display_sink_via_per_call_output(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:shell{{command:{_STR}ls{_STR},output:{_STR}display{_STR}}}<tool_call|>", "stop"),
        ("All done.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    routed = []
    responses = []

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "run ls"}],
        tool_schemas=_schemas_for("shell"),
        tool_executor=lambda n, a: {"stdout": "PAYLOAD" * 100, "returncode": 0},
        system_prompt="sys",
        on_tool_response=lambda n, r: responses.append((n, r)),
        on_tool_routed=lambda n, r, s: routed.append((n, r, s)),
    )

    assert text == "All done."
    assert exchanges[0]["result"] == {"status": "ok", "output": "sent to display"}
    second_prompt = fake.prompts_seen[1]
    assert "sent to display" in second_prompt
    assert "PAYLOAD" not in second_prompt
    assert routed == [("shell", {"stdout": "PAYLOAD" * 100, "returncode": 0}, "display")]
    assert responses == []
    # And the tool itself never saw output — verify by recording args:
    seen_args = []
    backend2 = _make_textgen_backend()
    monkeypatch.setattr(backend2, "_complete", _FakeBackend([
        (f"<|tool_call>call:shell{{command:{_STR}ls{_STR},output:{_STR}display{_STR}}}<tool_call|>", "stop"),
        ("done", "stop"),
    ]))
    def recorder(n, a):
        seen_args.append(dict(a))
        return {}
    backend2.run(
        messages=[{"role": "user", "content": "x"}],
        tool_schemas=_schemas_for("shell"),
        tool_executor=recorder,
        system_prompt="sys",
    )
    assert seen_args == [{"command": "ls"}]  # output stripped before execute


def test_run_loop_file_sink_writes_and_stubs(monkeypatch, tmp_path):
    backend = _make_textgen_backend()
    target = tmp_path / "result.json"
    fake = _FakeBackend([
        (f"<|tool_call>call:dump{{value:42,output:{_STR}file:{target}{_STR}}}<tool_call|>", "stop"),
        ("Saved.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "save it"}],
        tool_schemas=_schemas_for("dump"),
        tool_executor=lambda n, a: {"value": 42},
        system_prompt="sys",
        check_file_sink=lambda p, c, cfg: ("allow", "ok"),
        approval_config={},
    )
    assert target.exists()
    assert "42" in target.read_text()
    assert exchanges[0]["result"]["status"] == "ok"
    assert str(target) in exchanges[0]["result"]["output"]
    assert text == "Saved."


def test_run_loop_var_bind_then_pipe(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        # Step 1: bind result of "produce" to $payload.
        (f"<|tool_call>call:produce{{seed:1,output:{_STR}$payload{_STR}}}<tool_call|>", "stop"),
        # Step 2: consume $payload as the value of arg "data".
        (f"<|tool_call>call:consume{{data:{_STR}$payload{_STR}}}<tool_call|>", "stop"),
        ("Done.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    seen_args: list[tuple[str, dict]] = []

    def executor(name, args):
        seen_args.append((name, dict(args)))
        if name == "produce":
            return {"items": [1, 2, 3]}
        return {"received": args.get("data")}

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "pipe it"}],
        tool_schemas=[*_schemas_for("produce"), *_schemas_for("consume")],
        tool_executor=executor,
        system_prompt="sys",
    )

    # produce ran with no output (stripped), bound to $payload.
    assert seen_args[0] == ("produce", {"seed": 1})
    # consume ran with data substituted to the produce result.
    assert seen_args[1] == ("consume", {"data": {"items": [1, 2, 3]}})
    # First exchange shows the bind stub; second shows inline result.
    assert exchanges[0]["result"] == {"status": "ok", "output": "bound to $payload"}
    assert exchanges[1]["result"] == {"received": {"items": [1, 2, 3]}}
    assert text == "Done."


def test_run_loop_var_miss_rejects_call(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:consume{{data:{_STR}$nope{_STR}}}<tool_call|>", "stop"),
        ("Failed.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    executed = []
    denials = []
    backend.run(
        messages=[{"role": "user", "content": "go"}],
        tool_schemas=_schemas_for("consume"),
        tool_executor=lambda n, a: (executed.append((n, a)), {})[1],
        system_prompt="sys",
        on_tool_denied=lambda n, r: denials.append((n, r)),
    )
    assert executed == []
    assert denials and "$nope not bound" in denials[0][1]


def test_run_loop_bad_output_value_is_error_stub(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:t{{x:1,output:{_STR}garbage{_STR}}}<tool_call|>", "stop"),
        ("Failed.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    executed = []
    denials = []
    _, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "go"}],
        tool_schemas=_schemas_for("t"),
        tool_executor=lambda n, a: (executed.append(n), {})[1],
        system_prompt="sys",
        on_tool_denied=lambda n, r: denials.append((n, r)),
    )
    assert executed == []
    assert exchanges[0]["result"]["status"] == "error"
    assert "unknown sink" in exchanges[0]["result"]["reason"]
    assert denials and "unknown sink" in denials[0][1]


def test_run_loop_other_underscore_args_pass_through(monkeypatch):
    # Only `output` is reserved. Other "_"-prefixed keys reach the tool.
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:t{{_meta:1,x:2}}<tool_call|>", "stop"),
        ("ok", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    seen = []
    backend.run(
        messages=[{"role": "user", "content": "x"}],
        tool_schemas=_schemas_for("t"),
        tool_executor=lambda n, a: (seen.append(dict(a)), {})[1],
        system_prompt="sys",
    )
    assert seen == [{"_meta": 1, "x": 2}]


def test_run_loop_bindings_are_turn_scoped(monkeypatch):
    # Bindings produced in one run() do not leak into the next.
    backend = _make_textgen_backend()
    monkeypatch.setattr(backend, "_complete", _FakeBackend([
        (f"<|tool_call>call:p{{output:{_STR}$x{_STR}}}<tool_call|>", "stop"),
        ("done", "stop"),
    ]))
    backend.run(
        messages=[{"role": "user", "content": "first"}],
        tool_schemas=_schemas_for("p"),
        tool_executor=lambda n, a: {"v": 1},
        system_prompt="sys",
    )

    # New run, model tries to reference $x from the previous turn — should miss.
    monkeypatch.setattr(backend, "_complete", _FakeBackend([
        (f"<|tool_call>call:c{{data:{_STR}$x{_STR}}}<tool_call|>", "stop"),
        ("done", "stop"),
    ]))
    denials = []
    executed = []
    backend.run(
        messages=[{"role": "user", "content": "second"}],
        tool_schemas=_schemas_for("c"),
        tool_executor=lambda n, a: (executed.append(n), {})[1],
        system_prompt="sys",
        on_tool_denied=lambda n, r: denials.append((n, r)),
    )
    assert executed == []
    assert denials and "$x not bound" in denials[0][1]


# ── Pure helpers ─────────────────────────────────────────────────────────────

def test_validate_sink_accepts_known_forms():
    from nugget.backends.textgen import _validate_sink
    assert _validate_sink("display") is None
    assert _validate_sink("file:/tmp/x.json") is None
    assert _validate_sink("$payload") is None


def test_validate_sink_rejects_unknown_and_malformed():
    from nugget.backends.textgen import _validate_sink
    assert "unknown sink" in _validate_sink("garbage")
    assert "unknown sink" in _validate_sink("file:")  # empty path
    assert "unknown sink" in _validate_sink("$1bad")  # invalid name


def test_substitute_vars_whole_value_only():
    from nugget.backends.textgen import _substitute_vars
    bindings = {"x": [1, 2, 3]}
    out, err = _substitute_vars({"data": "$x", "tag": "literal", "n": 5}, bindings)
    assert err is None
    assert out == {"data": [1, 2, 3], "tag": "literal", "n": 5}


def test_substitute_vars_misses_report_first_unbound():
    from nugget.backends.textgen import _substitute_vars
    out, err = _substitute_vars({"a": "$nope"}, {})
    assert err == "$nope not bound"
    assert out == {"a": "$nope"}  # untouched


def test_substitute_vars_does_not_recurse():
    # Nested references are NOT substituted — whole-value only.
    from nugget.backends.textgen import _substitute_vars
    out, err = _substitute_vars({"a": ["$x"]}, {"x": "hi"})
    assert err is None
    assert out == {"a": ["$x"]}


# ── JMESPath colon-suffix paths ──────────────────────────────────────────────

def test_validate_sink_accepts_display_with_path():
    from nugget.backends.textgen import _validate_sink
    assert _validate_sink("display:title") is None
    assert _validate_sink("display:items[0].name") is None


def test_validate_sink_rejects_display_with_empty_path():
    from nugget.backends.textgen import _validate_sink
    err = _validate_sink("display:")
    assert err and "non-empty" in err


def test_validate_sink_rejects_display_with_bad_path():
    from nugget.backends.textgen import _validate_sink
    err = _validate_sink("display:items[")
    assert err and "invalid jmespath" in err


def test_validate_sink_accepts_var_with_path():
    from nugget.backends.textgen import _validate_sink
    assert _validate_sink("$article.body") is None
    assert _validate_sink("$x.items[0].id") is None


def test_validate_sink_rejects_var_with_bad_path():
    from nugget.backends.textgen import _validate_sink
    err = _validate_sink("$x.items[")
    assert err and "invalid jmespath" in err


def test_substitute_vars_with_path_extracts_field():
    from nugget.backends.textgen import _substitute_vars
    bindings = {"a": {"title": "T", "body": "B"}}
    out, err = _substitute_vars({"text": "$a.body"}, bindings)
    assert err is None
    assert out == {"text": "B"}


def test_substitute_vars_with_path_missing_key_errors():
    from nugget.backends.textgen import _substitute_vars
    bindings = {"a": {"title": "T"}}
    out, err = _substitute_vars({"text": "$a.body"}, bindings)
    assert err == "$a.body not present"
    assert out == {"text": "$a.body"}


def test_substitute_vars_with_unbound_var_path():
    from nugget.backends.textgen import _substitute_vars
    out, err = _substitute_vars({"text": "$nope.body"}, {})
    assert err == "$nope not bound"
    assert out == {"text": "$nope.body"}


def test_route_display_with_path_extracts_before_routing():
    c = _Calls()
    result = {"title": "Hello", "body": "lots of body content"}
    out = _route(
        name="wallabag", result=result, sink="display:title",
        on_tool_response=c.on_response, on_tool_routed=c.on_routed, on_tool_denied=c.on_denied,
    )
    # Stub stays the same; routed callback receives the path-extracted payload.
    assert out == {"status": "ok", "output": "sent to display"}
    assert c.routed == [("wallabag", "Hello", "display:title")]
    assert c.responses == []


def test_route_display_with_path_missing_key_yields_none_payload():
    c = _Calls()
    result = {"title": "T"}
    out = _route(
        name="wallabag", result=result, sink="display:body",
        on_tool_routed=c.on_routed,
    )
    assert out == {"status": "ok", "output": "sent to display"}
    assert c.routed == [("wallabag", None, "display:body")]


def test_run_loop_display_with_path(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:wallabag{{op:{_STR}get{_STR},output:{_STR}display:title{_STR}}}<tool_call|>", "stop"),
        ("Done.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    routed = []

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "fetch"}],
        tool_schemas=_schemas_for("wallabag"),
        tool_executor=lambda n, a: {"title": "MyTitle", "body": "BIG_BODY" * 50},
        system_prompt="sys",
        on_tool_routed=lambda n, r, s: routed.append((n, r, s)),
    )

    assert text == "Done."
    assert exchanges[0]["result"] == {"status": "ok", "output": "sent to display"}
    second_prompt = fake.prompts_seen[1]
    assert "sent to display" in second_prompt
    assert "BIG_BODY" not in second_prompt
    assert routed == [("wallabag", "MyTitle", "display:title")]


def test_run_loop_var_path_substitution(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:produce{{output:{_STR}$art{_STR}}}<tool_call|>", "stop"),
        (f"<|tool_call>call:consume{{text:{_STR}$art.body{_STR}}}<tool_call|>", "stop"),
        ("Ok.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    seen_args: list[tuple[str, dict]] = []

    def executor(name, args):
        seen_args.append((name, dict(args)))
        if name == "produce":
            return {"title": "T", "body": "the body"}
        return {"received": args.get("text")}

    text, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "go"}],
        tool_schemas=[*_schemas_for("produce"), *_schemas_for("consume")],
        tool_executor=executor,
        system_prompt="sys",
    )

    assert seen_args[0] == ("produce", {})
    assert seen_args[1] == ("consume", {"text": "the body"})
    assert exchanges[0]["result"] == {"status": "ok", "output": "bound to $art"}
    assert exchanges[1]["result"] == {"received": "the body"}
    assert text == "Ok."


def test_run_loop_var_path_miss_rejects_call(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:produce{{output:{_STR}$art{_STR}}}<tool_call|>", "stop"),
        (f"<|tool_call>call:consume{{text:{_STR}$art.missing{_STR}}}<tool_call|>", "stop"),
        ("Failed.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    executed = []
    denials = []

    def executor(name, args):
        executed.append((name, dict(args)))
        if name == "produce":
            return {"title": "T"}
        return {}

    backend.run(
        messages=[{"role": "user", "content": "go"}],
        tool_schemas=[*_schemas_for("produce"), *_schemas_for("consume")],
        tool_executor=executor,
        system_prompt="sys",
        on_tool_denied=lambda n, r: denials.append((n, r)),
    )
    # produce ran; consume rejected before executor was called.
    assert executed == [("produce", {})]
    assert denials and "$art.missing not present" in denials[0][1]


def test_run_loop_bad_display_path_is_error_stub(monkeypatch):
    backend = _make_textgen_backend()
    fake = _FakeBackend([
        (f"<|tool_call>call:t{{x:1,output:{_STR}display:items[{_STR}}}<tool_call|>", "stop"),
        ("Failed.", "stop"),
    ])
    monkeypatch.setattr(backend, "_complete", fake)

    executed = []
    denials = []
    _, _, exchanges, _ = backend.run(
        messages=[{"role": "user", "content": "go"}],
        tool_schemas=_schemas_for("t"),
        tool_executor=lambda n, a: (executed.append(n), {})[1],
        system_prompt="sys",
        on_tool_denied=lambda n, r: denials.append((n, r)),
    )
    assert executed == []
    assert exchanges[0]["result"]["status"] == "error"
    assert "invalid jmespath" in exchanges[0]["result"]["reason"]
    assert denials and "invalid jmespath" in denials[0][1]
