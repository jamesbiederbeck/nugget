"""
text-generation-webui backend using /v1/completions with Gemma 4 prompt format.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable

import jinja2
import requests

from . import BackendError
from ._routing import (
    _substitute_vars,
    _validate_sink,
    _route_tool_result,
)

# ── Jinja2 template env ──────────────────────────────────────────────────────

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
_TOOL_CALL_RE = re.compile(r"<\|tool_call\>call:(\w+)(\{.*\})<tool_call\|>", re.DOTALL)
_STR_DELIM_LEN = len(_STR_DELIM)


def _parse_gval(s: str) -> Any:
    """Recursive descent parser for Gemma 4 structured values."""
    _, val = _parse_gval_at(s.strip(), 0)
    return val


def _parse_gval_at(s: str, pos: int) -> tuple[int, Any]:
    while pos < len(s) and s[pos].isspace():
        pos += 1
    if pos >= len(s):
        return pos, None

    if s[pos:pos + _STR_DELIM_LEN] == _STR_DELIM:
        start = pos + _STR_DELIM_LEN
        end = s.find(_STR_DELIM, start)
        if end == -1:
            return len(s), s[start:]
        return end + _STR_DELIM_LEN, s[start:end]

    if s[pos] == "{":
        pos += 1
        result: dict[str, Any] = {}
        while pos < len(s):
            while pos < len(s) and s[pos].isspace():
                pos += 1
            if pos < len(s) and s[pos] == "}":
                return pos + 1, result
            key_start = pos
            while pos < len(s) and s[pos] not in (":", "}", ","):
                pos += 1
            key = s[key_start:pos].strip()
            if not key:
                break
            if pos < len(s) and s[pos] == ":":
                pos += 1
            pos, val = _parse_gval_at(s, pos)
            result[key] = val
            while pos < len(s) and s[pos].isspace():
                pos += 1
            if pos < len(s) and s[pos] == ",":
                pos += 1
        return pos, result

    if s[pos] == "[":
        pos += 1
        items: list[Any] = []
        while pos < len(s):
            while pos < len(s) and s[pos].isspace():
                pos += 1
            if pos < len(s) and s[pos] == "]":
                return pos + 1, items
            pos, val = _parse_gval_at(s, pos)
            items.append(val)
            while pos < len(s) and s[pos].isspace():
                pos += 1
            if pos < len(s) and s[pos] == ",":
                pos += 1
        return pos, items

    start = pos
    while pos < len(s) and s[pos] not in (",", "}", "]"):
        pos += 1
    token = s[start:pos].strip()
    if token == "true":
        return pos, True
    if token == "false":
        return pos, False
    if token == "null":
        return pos, None
    try:
        return pos, int(token)
    except ValueError:
        pass
    try:
        return pos, float(token)
    except ValueError:
        pass
    return pos, token


def parse_tool_call(text: str) -> tuple[str, dict] | None:
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    name = m.group(1)
    args = _parse_gval(m.group(2))
    if not isinstance(args, dict):
        args = {"_raw": m.group(2)}
    return name, args


def parse_thinking(text: str) -> tuple[str | None, str]:
    m = _THINKING_RE.search(text)
    if not m:
        return None, text.strip()
    thinking = m.group(1).strip()
    response = text[m.end():].strip()
    if "<|tool_call>" in response:
        response = ""
    return thinking, response


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _render_assistant_turn(msg: dict) -> str:
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
    thinking_effort: int,
) -> str:
    has_memory = any(
        s.get("function", {}).get("name") == "memory" for s in tool_schemas
    )
    tool_declarations = [format_tool_declaration(s) for s in tool_schemas]
    tmpl = _jinja_env.get_template("system.j2")
    system_content = tmpl.render(
        system_prompt=system_prompt,
        tool_declarations=tool_declarations,
        thinking_effort=thinking_effort,
        has_memory=has_memory,
        has_tools=bool(tool_schemas),
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


# ── Per-call routing meta-args ───────────────────────────────────────────────
# Helpers imported from ._routing (also used by render_output).


# ── HTTP client + tool loop ──────────────────────────────────────────────────

class TextgenBackend:
    def __init__(self, config):
        self.cfg = config
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def _post(self, prompt: str, stop: list[str]) -> requests.Response:
        url = f"{self.cfg.api_url}/v1/completions"
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "top_p": self.cfg.top_p,
            "top_k": self.cfg.top_k,
            "prompt": prompt,
            "stop": stop,
        }
        if self.cfg.debug:
            print(json.dumps({"url": url, "payload": payload}, indent=2))
        resp = self._session.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp

    def _complete(self, prompt: str, stop: list[str]) -> tuple[str, str]:
        resp = self._post(prompt, stop)
        data = resp.json()
        choice = data["choices"][0]
        return choice["text"], choice["finish_reason"]

    def _complete_streaming(
        self,
        prompt: str,
        stop: list[str],
        on_token: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """Stream one completion turn. Fires on_token for visible text, on_thinking for thought blocks."""
        url = f"{self.cfg.api_url}/v1/completions"
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "top_p": self.cfg.top_p,
            "top_k": self.cfg.top_k,
            "prompt": prompt,
            "stop": stop,
            "stream": True,
        }
        if self.cfg.debug:
            print(json.dumps({"url": url, "streaming": True}, indent=2))

        accumulated = ""
        finish_reason = "stop"
        is_text_mode = False
        _LOOKAHEAD = 20
        _SPECIAL = ("<|channel>thought", "<|tool_call>")

        resp = self._session.post(url, json=payload, stream=True, timeout=120)
        resp.raise_for_status()

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            if raw_line == b"data: [DONE]":
                break
            if not raw_line.startswith(b"data: "):
                continue
            chunk = json.loads(raw_line[6:])
            choice = chunk["choices"][0]
            tok = choice["text"]
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr
            accumulated += tok

            if not is_text_mode:
                if len(accumulated) >= _LOOKAHEAD and not any(
                    accumulated.startswith(p) for p in _SPECIAL
                ):
                    is_text_mode = True
                    if on_token:
                        on_token(accumulated)
            elif on_token:
                on_token(tok)

        # Post-stream: handle thinking blocks and short responses
        if not is_text_mode:
            if "<|channel>thought" in accumulated:
                thinking_text, response_text = parse_thinking(accumulated)
                if thinking_text and on_thinking:
                    on_thinking(thinking_text)
                if response_text and "<|tool_call>" not in accumulated and on_token:
                    on_token(response_text)
            elif accumulated and "<|tool_call>" not in accumulated and on_token:
                # Short response that never reached the lookahead threshold
                on_token(accumulated)

        return accumulated, finish_reason

    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        thinking_effort: int = 0,
        on_thinking: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_response: Callable[[str, object], None] | None = None,
        on_tool_denied: Callable[[str, str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
        on_tool_routed: Callable[[str, object, str], None] | None = None,
        check_file_sink: Callable[[Path, Path, dict], tuple[str, str]] | None = None,
        sink_approval_prompt: Callable[[str, Path], bool] | None = None,
        approval_config: dict | None = None,
        **kwargs,
    ) -> tuple[str, str | None, list[dict], str | None]:
        has_tools = bool(tool_schemas)
        stop = ["<turn|>", "<|tool_response>"] if has_tools else ["<turn|>"]

        prompt = build_prompt(messages, tool_schemas, system_prompt, thinking_effort)
        accumulated = ""
        tool_exchanges: list[dict] = []
        finish_reason: str | None = None
        # Turn-scoped variable bindings for $name pipes. Cleared on return.
        bindings: dict[str, object] = {}

        for _ in range(16):
            try:
                if on_token is not None:
                    text, finish_reason = self._complete_streaming(
                        prompt, stop, on_token=on_token, on_thinking=on_thinking
                    )
                else:
                    text, finish_reason = self._complete(prompt, stop)
            except requests.RequestException as e:
                raise BackendError(str(e)) from e

            accumulated += text

            if finish_reason == "length":
                break

            tc = parse_tool_call(accumulated)
            if tc is None:
                break

            name, args = tc
            if on_tool_call:
                on_tool_call(name, args)

            # Strip the routing meta-arg (if any) before substitution and
            # before passing args to the tool. Other "_"-prefixed keys are
            # left alone — the tool sees its own args verbatim.
            sink = args.pop("output", None)

            sink_error: str | None = None
            if sink is not None and not isinstance(sink, str):
                sink_error = f"output must be a string, got {type(sink).__name__}"
            elif isinstance(sink, str):
                sink_error = _validate_sink(sink)

            if sink_error is not None:
                # Report up the trace and skip both substitution and execution.
                if on_tool_denied:
                    on_tool_denied(name, sink_error)
                result_for_context = {"status": "error", "reason": sink_error}
                tool_exchanges.append({"name": name, "args": args, "result": result_for_context})
                response_token = format_tool_response_token(name, result_for_context)
                prompt = prompt + accumulated + "<|tool_response>" + response_token
                accumulated = ""
                continue

            substituted_args, sub_error = _substitute_vars(args, bindings)
            if sub_error is not None:
                if on_tool_denied:
                    on_tool_denied(name, sub_error)
                result_for_context = {"status": "error", "reason": sub_error}
                tool_exchanges.append({"name": name, "args": args, "result": result_for_context})
                response_token = format_tool_response_token(name, result_for_context)
                prompt = prompt + accumulated + "<|tool_response>" + response_token
                accumulated = ""
                continue

            result = tool_executor(name, substituted_args)

            if isinstance(result, dict) and result.get("_denied"):
                reason = result.get("reason", "denied")
                if on_tool_denied:
                    on_tool_denied(name, reason)
                result_for_context = {"error": reason}
            else:
                result_for_context = _route_tool_result(
                    name=name,
                    result=result,
                    sink=sink,
                    bindings=bindings,
                    on_tool_response=on_tool_response,
                    on_tool_routed=on_tool_routed,
                    on_tool_denied=on_tool_denied,
                    check_file_sink=check_file_sink,
                    sink_approval_prompt=sink_approval_prompt,
                    approval_config=approval_config,
                )

            # Record the args as the model sent them (with output stripped,
            # but pre-substitution) so session JSON shows the model's intent.
            tool_exchanges.append({"name": name, "args": args, "result": result_for_context})

            response_token = format_tool_response_token(name, result_for_context)
            prompt = prompt + accumulated + "<|tool_response>" + response_token
            accumulated = ""

        thinking_out, final_text = parse_thinking(accumulated)
        if thinking_out and on_thinking and on_token is None:
            # In streaming mode _complete_streaming already fired on_thinking
            on_thinking(thinking_out)

        return final_text, thinking_out, tool_exchanges, finish_reason
