import pytest
from nugget.backends.textgen import (
    _gval,
    _parse_gval,
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
