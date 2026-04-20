"""
Builds raw Gemma 4 prompts for the /v1/completions endpoint.
Uses Jinja2 for the system turn; history turns are rendered in Python.
"""

import re
from pathlib import Path
from typing import Any

import jinja2

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
)

# ── Gemma 4 value serialiser ─────────────────────────────────────────────────

_STR_DELIM = '<|"|>'


def _gval(v: Any) -> str:
    """Recursively serialise a Python value into Gemma 4 structured-data format."""
    if isinstance(v, dict):
        pairs = ",".join(f"{k}:{_gval(val)}" for k, val in v.items())
        return "{" + pairs + "}"
    if isinstance(v, list):
        return "[" + ",".join(_gval(i) for i in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, str):
        return f"{_STR_DELIM}{v}{_STR_DELIM}"
    return str(v)


# ── Tool formatting ──────────────────────────────────────────────────────────

def format_tool_declaration(schema: dict) -> str:
    fn = schema["function"]
    body: dict[str, Any] = {}
    if "description" in fn:
        body["description"] = fn["description"]
    if "parameters" in fn:
        body["parameters"] = fn["parameters"]
    return f"<|tool>declaration:{fn['name']}{_gval(body)}<tool|>"


def format_tool_call_token(name: str, args: dict) -> str:
    return f"<|tool_call>call:{name}{_gval(args)}<tool_call|>"


def format_tool_response_token(name: str, result: Any) -> str:
    if isinstance(result, dict):
        body = result
    else:
        body = {"result": result}
    return f"<|tool_response>response:{name}{_gval(body)}<tool_response|>"


# ── Parsing model output ─────────────────────────────────────────────────────

_THINKING_RE = re.compile(r"<\|channel\>thought\n(.*?)\n?<channel\|>", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"<\|tool_call\>call:(\w+)(\{.*?\})<tool_call\|>", re.DOTALL)
_STR_TOKEN_RE = re.compile(r'<\|"\|>(.*?)<\|"\|>', re.DOTALL)


def _parse_gval(s: str) -> Any:
    """Best-effort parse of a Gemma 4 structured value back to Python."""
    s = s.strip()
    # Replace <|"|>...<|"|> string tokens first
    s_py = _STR_TOKEN_RE.sub(lambda m: repr(m.group(1)), s)
    # Replace remaining bare number-like values — handled below
    try:
        import ast
        # Attempt to eval as Python literal after cleaning up key formatting
        # Convert {key:val,...} to {"key":val,...}
        py_str = re.sub(r"(?<!['\"])(\b[a-zA-Z_]\w*\b)(?=\s*:)", r'"\1"', s_py)
        return ast.literal_eval(py_str)
    except Exception:
        return s  # return raw string on failure


def parse_tool_call(text: str) -> tuple[str, dict] | None:
    """Extract first tool call from model output. Returns (name, args) or None."""
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    name = m.group(1)
    args_str = m.group(2)
    args = _parse_gval(args_str)
    if not isinstance(args, dict):
        args = {"_raw": args_str}
    return name, args


def parse_thinking(text: str) -> tuple[str | None, str]:
    """Split model output into (thinking, response). thinking may be None."""
    m = _THINKING_RE.search(text)
    if not m:
        return None, text.strip()
    thinking = m.group(1).strip()
    response = text[m.end():].strip()
    # Strip any remaining tool_call tokens from the "response" if it's actually
    # a tool call turn (tool_call text isn't the final visible response)
    if "<|tool_call>" in response:
        response = ""
    return thinking, response


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _render_assistant_turn(msg: dict) -> str:
    """Reconstruct a stored assistant message into raw Gemma 4 format."""
    parts = []
    if msg.get("thinking"):
        parts.append(f"<|channel>thought\n{msg['thinking']}\n<channel|>")
    for tc in msg.get("tool_calls", []):
        parts.append(format_tool_call_token(tc["name"], tc["args"]))
        parts.append("<|tool_response>")
        parts.append(format_tool_response_token(tc["name"], tc["result"]))
    if msg.get("content"):
        parts.append(msg["content"])
    return "".join(parts)


def build_prompt(
    messages: list[dict],
    tool_schemas: list[dict],
    system_prompt: str,
    thinking_effort: int,  # 0=off 1=low 2=med 3=high
) -> str:
    tmpl = _jinja_env.get_template("system.j2")
    system_content = tmpl.render(
        system_prompt=system_prompt,
        tools=tool_schemas,
        thinking_effort=thinking_effort,
        format_tool_declaration=format_tool_declaration,
    )

    parts = [system_content]
    for msg in messages:
        if msg["role"] == "user":
            parts.append(f"<|turn>user\n{msg['content']}<turn|>")
        elif msg["role"] == "assistant":
            inner = _render_assistant_turn(msg)
            parts.append(f"<|turn>model\n{inner}<turn|>")

    parts.append("<|turn>model\n")
    return "\n".join(parts)
