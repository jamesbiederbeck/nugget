"""
text-generation-webui backend using /v1/completions with Gemma 4 prompt format.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import jinja2
import requests

from . import BackendError, Backend
from . import _openai_chat
from ._routing import (
    _substitute_vars,
    _validate_sink,
    _route_tool_result,
)
from ..subagent import _tool_ctx

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


def _has_attachment(messages: list[dict]) -> bool:
    """
    True if any prior tool call in this conversation produced an image
    attachment. The Gemma-4 token grammar (`_gval`) has no representation
    for image content, so once this is true the backend must speak OpenAI
    chat-completions (see `_run_chat_mode`) instead of `/v1/completions`.
    """
    return any(
        isinstance(tc.get("result"), dict) and tc["result"].get("_attachment") and tc["result"].get("images")
        for m in messages
        for tc in m.get("tool_calls", [])
    )


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _render_assistant_turn(msg: dict) -> str:
    parts = []
    for tc in msg.get("tool_calls", []):
        parts.append(format_tool_call_token(tc["name"], tc["args"]))
        parts.append("<|tool_response>")
        parts.append(format_tool_response_token(tc["name"], tc["result"]))
    if msg.get("content"):
        parts.append(msg["content"])
    return "".join(parts)


@lru_cache(maxsize=8)
def _render_system_content(
    system_prompt: str,
    tool_declarations: tuple[str, ...],
    thinking_effort: int,
    has_memory: bool,
    has_tools: bool,
) -> str:
    tmpl = _jinja_env.get_template("system.j2")
    return tmpl.render(
        system_prompt=system_prompt,
        tool_declarations=list(tool_declarations),
        thinking_effort=thinking_effort,
        has_memory=has_memory,
        has_tools=has_tools,
    )


def build_prompt(
    messages: list[dict],
    tool_schemas: list[dict],
    system_prompt: str,
    thinking_effort: int,
) -> str:
    has_memory = any(
        s.get("function", {}).get("name") == "memory" for s in tool_schemas
    )
    tool_declarations = tuple(format_tool_declaration(s) for s in tool_schemas)
    system_content = _render_system_content(
        system_prompt,
        tool_declarations,
        thinking_effort,
        has_memory,
        bool(tool_schemas),
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

class TextgenBackend(Backend):
    def __init__(self, config):
        self.cfg = config
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def list_models(self) -> list[str]:
        """All gguf models on disk, per text-generation-webui's internal API — not just the loaded one."""
        url = f"{self.cfg.api_url}/v1/internal/model/list"
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BackendError(str(e)) from e
        return sorted(resp.json().get("model_names", []))

    def current_model(self) -> str:
        url = f"{self.cfg.api_url}/v1/internal/model/info"
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BackendError(str(e)) from e
        return resp.json().get("model_name", "")

    def load_model(self, name: str) -> None:
        """Hot-swap the loaded gguf on the server. Can take a while and uses GPU memory."""
        url = f"{self.cfg.api_url}/v1/internal/model/load"
        try:
            resp = self._session.post(url, json={"model_name": name}, timeout=300)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BackendError(str(e)) from e

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
        self.last_usage = data.get("usage") or None
        choice = data["choices"][0]
        return choice["text"], choice["finish_reason"]

    def _complete_streaming(
        self,
        prompt: str,
        stop: list[str],
        on_token: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        on_thinking_end: Callable[[], None] | None = None,
    ) -> tuple[str, str]:
        """
        Stream one completion turn. Fires on_token incrementally for visible
        text, on_thinking incrementally for thought-block content as it
        arrives, and on_thinking_end once when a thought block closes.
        """
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

        self.last_usage = None
        accumulated = ""
        finish_reason = "stop"
        _LOOKAHEAD = 20
        _THOUGHT_HEADER = "<|channel>thought"
        _THOUGHT_END = "<channel|>"

        # mode: 'unknown' (still classifying the start of the stream) ->
        # 'thinking' | 'text' | 'silent' (buffered tool-call, never shown).
        # 'post' classifies what follows a closed thought block, using the
        # same unknown -> text|silent logic via post_mode.
        mode = "unknown"
        post_mode = "unknown"
        post_buf = ""
        hold = ""  # tail held back in 'thinking' mode in case the end marker is split across chunks

        def _emit_thinking(buf: str) -> str:
            nonlocal mode, post_buf
            idx = buf.find(_THOUGHT_END)
            if idx == -1:
                keep = len(_THOUGHT_END) - 1
                emit, remainder = buf[: len(buf) - keep], buf[len(buf) - keep :]
                if emit and on_thinking:
                    on_thinking(emit)
                return remainder
            emit = buf[:idx]
            if emit and on_thinking:
                on_thinking(emit)
            if on_thinking_end:
                on_thinking_end()
            mode = "post"
            post_buf = buf[idx + len(_THOUGHT_END) :]
            return ""

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

            if mode == "unknown":
                if len(accumulated) >= _LOOKAHEAD:
                    if accumulated.startswith(_THOUGHT_HEADER):
                        mode = "thinking"
                        hold = _emit_thinking(accumulated[len(_THOUGHT_HEADER) :].lstrip("\n"))
                    elif accumulated.startswith("<|tool_call>"):
                        mode = "silent"
                    else:
                        mode = "text"
                        if on_token:
                            on_token(accumulated)
            elif mode == "thinking":
                hold += tok
                hold = _emit_thinking(hold)
            elif mode == "text":
                if on_token:
                    on_token(tok)
            elif mode == "post":
                post_buf += tok
                if post_mode == "unknown":
                    if len(post_buf) >= _LOOKAHEAD:
                        if post_buf.startswith("<|tool_call>"):
                            post_mode = "silent"
                        else:
                            post_mode = "text"
                            if on_token:
                                on_token(post_buf)
                elif post_mode == "text":
                    if on_token:
                        on_token(tok)
            # mode == "silent": nothing to do, stays buffered in `accumulated`

        # Post-stream: flush anything left unresolved — short responses that
        # never crossed a classification threshold, or a thought block that
        # never reached its closing marker before the stream ended.
        if mode == "unknown":
            if "<|channel>thought" in accumulated:
                thinking_text, response_text = parse_thinking(accumulated)
                if thinking_text and on_thinking:
                    on_thinking(thinking_text)
                    if on_thinking_end:
                        on_thinking_end()
                if response_text and "<|tool_call>" not in accumulated and on_token:
                    on_token(response_text)
            elif accumulated and "<|tool_call>" not in accumulated and on_token:
                on_token(accumulated)
        elif mode == "thinking":
            if hold and on_thinking:
                on_thinking(hold)
            if on_thinking_end:
                on_thinking_end()
        elif mode == "post" and post_mode == "unknown":
            if post_buf and "<|tool_call>" not in post_buf and on_token:
                on_token(post_buf)

        return accumulated, finish_reason

    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        thinking_effort: int = 0,
        on_thinking: Callable[[str], None] | None = None,
        on_thinking_end: Callable[[], None] | None = None,
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
        if _has_attachment(messages):
            return self._run_chat_mode(
                messages, tool_schemas, tool_executor, system_prompt,
                on_thinking=on_thinking, on_thinking_end=on_thinking_end,
                on_tool_call=on_tool_call, on_tool_response=on_tool_response,
                on_tool_denied=on_tool_denied, on_token=on_token,
                on_tool_routed=on_tool_routed, check_file_sink=check_file_sink,
                sink_approval_prompt=sink_approval_prompt, approval_config=approval_config,
            )

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
                        prompt, stop, on_token=on_token, on_thinking=on_thinking,
                        on_thinking_end=on_thinking_end,
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
                _, accumulated_no_thinking = parse_thinking(accumulated)
                prompt = prompt + accumulated_no_thinking + "<|tool_response>" + response_token
                accumulated = ""
                continue

            substituted_args, sub_error = _substitute_vars(args, bindings)
            if sub_error is not None:
                if on_tool_denied:
                    on_tool_denied(name, sub_error)
                result_for_context = {"status": "error", "reason": sub_error}
                tool_exchanges.append({"name": name, "args": args, "result": result_for_context})
                response_token = format_tool_response_token(name, result_for_context)
                _, accumulated_no_thinking = parse_thinking(accumulated)
                prompt = prompt + accumulated_no_thinking + "<|tool_response>" + response_token
                accumulated = ""
                continue

            ctx_token = _tool_ctx.set({"backend": self, "bindings": bindings, "config": self.cfg})
            try:
                result = tool_executor(name, substituted_args)
            finally:
                _tool_ctx.reset(ctx_token)

            if isinstance(result, dict) and result.get("_denied"):
                reason = result.get("reason", "denied")
                if on_tool_denied:
                    on_tool_denied(name, reason)
                result_for_context = {"error": reason}
            elif isinstance(result, dict) and result.get("_attachment") and result.get("images"):
                # Cannot represent inline in the Gemma-4 token grammar — hand
                # the rest of this turn off to OpenAI chat-completions mode,
                # replaying the exchanges made so far this run() plus this one.
                # Sink routing (display/file/$var) isn't supported for
                # attachments in v1 — only the default (goes back to the
                # model) path.
                if sink is None and on_tool_response:
                    on_tool_response(name, result)
                tool_exchanges.append({"name": name, "args": args, "result": result})
                return self._run_chat_mode(
                    messages, tool_schemas, tool_executor, system_prompt,
                    on_thinking=on_thinking, on_thinking_end=on_thinking_end,
                    on_tool_call=on_tool_call, on_tool_response=on_tool_response,
                    on_tool_denied=on_tool_denied, on_token=on_token,
                    on_tool_routed=on_tool_routed, check_file_sink=check_file_sink,
                    sink_approval_prompt=sink_approval_prompt, approval_config=approval_config,
                    seed_tool_exchanges=tool_exchanges,
                )
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
            _, accumulated_no_thinking = parse_thinking(accumulated)
            prompt = prompt + accumulated_no_thinking + "<|tool_response>" + response_token
            accumulated = ""

        thinking_out, final_text = parse_thinking(accumulated)
        if thinking_out and on_thinking and on_token is None:
            # In streaming mode _complete_streaming already fired on_thinking
            on_thinking(thinking_out)
            if on_thinking_end:
                on_thinking_end()

        return final_text, thinking_out, tool_exchanges, finish_reason

    def _run_chat_mode(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        on_thinking: Callable[[str], None] | None = None,
        on_thinking_end: Callable[[], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_response: Callable[[str, object], None] | None = None,
        on_tool_denied: Callable[[str, str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
        on_tool_routed: Callable[[str, object, str], None] | None = None,
        check_file_sink: Callable[[Path, Path, dict], tuple[str, str]] | None = None,
        sink_approval_prompt: Callable[[str, Path], bool] | None = None,
        approval_config: dict | None = None,
        seed_tool_exchanges: list[dict] | None = None,
    ) -> tuple[str, str | None, list[dict], str | None]:
        """
        OpenAI chat-completions tool loop, used once an image attachment
        enters the conversation (see `_has_attachment`). Structurally mirrors
        OpenRouterBackend.run()'s loop; wire-format details (message
        building, request/response parsing, attachment expansion) come from
        `_openai_chat`.

        `seed_tool_exchanges`, when set, are exchanges already made earlier
        in this same logical turn under the Gemma-4 token loop before an
        attachment result forced the switch to chat mode — they're replayed
        as a synthetic assistant turn so the model sees them in context.
        """
        full_messages = list(messages)
        if seed_tool_exchanges:
            full_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"call_{i}", "name": ex["name"], "args": ex["args"], "result": ex["result"]}
                    for i, ex in enumerate(seed_tool_exchanges)
                ],
            })
        oai_messages = _openai_chat.build_messages(full_messages, system_prompt)
        url = f"{self.cfg.api_url}/v1/chat/completions"

        tool_exchanges: list[dict] = list(seed_tool_exchanges or [])
        bindings: dict[str, object] = {}
        final_text = ""
        final_thinking: str | None = None
        finish_reason: str | None = None

        for _ in range(16):
            if on_token is not None:
                text, thinking, raw_tcs, usage = _openai_chat.complete_streaming(
                    self._session, url, self.cfg.model, oai_messages, tool_schemas,
                    temperature=self.cfg.temperature, max_tokens=self.cfg.max_tokens,
                    on_token=on_token, on_thinking=on_thinking, on_thinking_end=on_thinking_end,
                    debug=self.cfg.debug,
                )
            else:
                text, thinking, raw_tcs, usage = _openai_chat.complete(
                    self._session, url, self.cfg.model, oai_messages, tool_schemas,
                    temperature=self.cfg.temperature, max_tokens=self.cfg.max_tokens,
                    debug=self.cfg.debug,
                )
            self.last_usage = usage

            if thinking and not final_thinking:
                final_thinking = thinking

            if not raw_tcs:
                final_text = text
                finish_reason = "stop"
                break

            assistant_tool_calls = []
            tool_result_messages = []

            for raw_tc in raw_tcs:
                fn = raw_tc.get("function", {})
                name = fn.get("name", "")
                call_id = raw_tc.get("id", f"call_{name}")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if on_tool_call:
                    on_tool_call(name, args)

                sink = args.pop("output", None)
                sink_error: str | None = None
                if sink is not None and not isinstance(sink, str):
                    sink_error = f"output must be a string, got {type(sink).__name__}"
                elif isinstance(sink, str):
                    sink_error = _validate_sink(sink)

                if sink_error is not None:
                    if on_tool_denied:
                        on_tool_denied(name, sink_error)
                    result_for_context = {"status": "error", "reason": sink_error}
                else:
                    substituted_args, sub_error = _substitute_vars(args, bindings)
                    if sub_error is not None:
                        if on_tool_denied:
                            on_tool_denied(name, sub_error)
                        result_for_context = {"status": "error", "reason": sub_error}
                    else:
                        ctx_token = _tool_ctx.set({"backend": self, "bindings": bindings, "config": self.cfg})
                        try:
                            result = tool_executor(name, substituted_args)
                        finally:
                            _tool_ctx.reset(ctx_token)
                        if isinstance(result, dict) and result.get("_denied"):
                            reason = result.get("reason", "denied")
                            if on_tool_denied:
                                on_tool_denied(name, reason)
                            result_for_context = {"error": reason}
                        elif isinstance(result, dict) and result.get("_attachment") and result.get("images"):
                            if on_tool_response:
                                on_tool_response(name, result)
                            result_for_context = result
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

                tool_exchanges.append({"name": name, "args": args, "result": result_for_context, "id": call_id})
                assistant_tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                })
                if isinstance(result_for_context, dict) and result_for_context.get("_attachment") and result_for_context.get("images"):
                    tool_result_messages.append(_openai_chat._tool_stub_message({"id": call_id}, result_for_context))
                    tool_result_messages.append(_openai_chat._attachment_followup_message(result_for_context))
                else:
                    tool_result_messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result_for_context),
                    })

            oai_messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": assistant_tool_calls,
            })
            oai_messages.extend(tool_result_messages)

        else:
            finish_reason = "length"

        return final_text, final_thinking, tool_exchanges, finish_reason
