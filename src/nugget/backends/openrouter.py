"""
OpenRouter backend — OpenAI-compatible /v1/chat/completions with native tool calling.

Config keys:
    backend: "openrouter"
    openrouter_api_key: <string>  (or env OPENROUTER_API_KEY)
    openrouter_model:   <string>  (default: "openai/gpt-4o-mini")

OpenRouter speaks the OpenAI chat-completions protocol. Tool calling uses the
native `tools` + `tool_calls` fields. Streaming merges partial-JSON deltas
across chunks before executing tools.

Reasoning/thinking is captured from `reasoning_content` in the delta when
present (some models, e.g. openai/o1).
"""

import json
import os
from pathlib import Path
from typing import Callable

import requests

from . import BackendError, Backend
from ._routing import (
    _substitute_vars,
    _validate_sink,
    _route_tool_result,
)

_DEFAULT_MODEL = "openai/gpt-4o-mini"
_MAX_TOOL_LOOPS = 16


class OpenRouterBackend(Backend):
    def __init__(self, config):
        self.cfg = config
        api_key = config.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OpenRouter backend requires an API key. "
                "Set 'openrouter_api_key' in config.json or the OPENROUTER_API_KEY environment variable."
            )
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/jamesbiederbeck/nugget",
            "X-Title": "nugget",
        })
        self._model = config.get("openrouter_model", _DEFAULT_MODEL)
        self._url = "https://openrouter.ai/api/v1/chat/completions"

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        messages: list[dict],
        system_prompt: str,
        tool_exchanges_accumulated: list[dict],
    ) -> list[dict]:
        """
        Build the OpenAI-format message list from nugget's internal format.
        system_prompt goes as a "system" role message first.
        tool_exchanges_accumulated holds completed tool calls for this turn.
        """
        out: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if msg["role"] == "user":
                out.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "assistant":
                # Reconstruct the assistant turn from stored tool_calls if any.
                assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or ""}
                if msg.get("tool_calls"):
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]),
                            },
                        }
                        for i, tc in enumerate(msg["tool_calls"])
                    ]
                out.append(assistant_msg)
                for tc in msg.get("tool_calls", []):
                    out.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "call_0"),
                        "content": json.dumps(tc["result"]),
                    })
        return out

    def _complete(
        self,
        oai_messages: list[dict],
        tool_schemas: list[dict],
    ) -> tuple[str, str | None, list[dict]]:
        """
        Non-streaming completion. Returns (text, thinking, tool_calls_raw).
        tool_calls_raw is a list of OpenAI tool call dicts.
        """
        payload: dict = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": self.cfg.get("temperature", 0.7),
            "max_tokens": self.cfg.get("max_tokens", 2048),
        }
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "auto"
        if self.cfg.get("debug"):
            print(json.dumps({"url": self._url, "payload": payload}, indent=2))
        try:
            resp = self._session.post(self._url, json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BackendError(str(e)) from e
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        text = msg.get("content") or ""
        thinking = msg.get("reasoning_content")
        tool_calls = msg.get("tool_calls") or []
        return text, thinking, tool_calls

    def _complete_streaming(
        self,
        oai_messages: list[dict],
        tool_schemas: list[dict],
        on_token: Callable[[str], None] | None,
        on_thinking: Callable[[str], None] | None,
    ) -> tuple[str, str | None, list[dict]]:
        """
        Streaming completion. Fires on_token for visible text, on_thinking for
        reasoning content. Assembles partial tool-call-argument deltas across
        chunks. Returns (text, thinking, tool_calls_raw).
        """
        payload: dict = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": self.cfg.get("temperature", 0.7),
            "max_tokens": self.cfg.get("max_tokens", 2048),
            "stream": True,
        }
        if tool_schemas:
            payload["tools"] = tool_schemas
            payload["tool_choice"] = "auto"
        if self.cfg.get("debug"):
            print(json.dumps({"url": self._url, "streaming": True}, indent=2))
        try:
            resp = self._session.post(self._url, json=payload, stream=True, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BackendError(str(e)) from e

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        # tool_calls_buf: index → {"id", "name", "args_str"}
        tool_calls_buf: dict[int, dict] = {}

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            if raw_line == b"data: [DONE]":
                break
            if not raw_line.startswith(b"data: "):
                continue
            chunk = json.loads(raw_line[6:])
            choice = chunk["choices"][0]
            delta = choice.get("delta", {})

            # Reasoning / thinking
            reasoning_delta = delta.get("reasoning_content") or ""
            if reasoning_delta:
                thinking_parts.append(reasoning_delta)

            # Visible text
            content_delta = delta.get("content") or ""
            if content_delta:
                text_parts.append(content_delta)
                if on_token:
                    on_token(content_delta)

            # Tool call argument deltas — merge by index
            for tc_delta in delta.get("tool_calls") or []:
                idx = tc_delta.get("index", 0)
                if idx not in tool_calls_buf:
                    tool_calls_buf[idx] = {"id": "", "name": "", "args_str": ""}
                buf = tool_calls_buf[idx]
                if tc_delta.get("id"):
                    buf["id"] = tc_delta["id"]
                fn = tc_delta.get("function") or {}
                if fn.get("name"):
                    buf["name"] += fn["name"]
                if fn.get("arguments"):
                    buf["args_str"] += fn["arguments"]

        full_text = "".join(text_parts)
        full_thinking = "".join(thinking_parts) or None

        if full_thinking and on_thinking:
            on_thinking(full_thinking)

        # Convert buf → OpenAI tool_calls format, preserving stream order via index
        tool_calls_raw = [
            {
                "id": buf["id"],
                "type": "function",
                "function": {"name": buf["name"], "arguments": buf["args_str"]},
            }
            for _, buf in sorted(tool_calls_buf.items())
        ]
        return full_text, full_thinking, tool_calls_raw

    # ── Main entry point ─────────────────────────────────────────────────────

    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
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
        # Build the running message list that we extend with each tool round.
        oai_messages = self._build_messages(messages, system_prompt, [])
        tool_exchanges: list[dict] = []
        # Turn-scoped variable bindings for $name pipes.
        bindings: dict[str, object] = {}
        final_text = ""
        final_thinking: str | None = None
        finish_reason: str | None = None

        for _ in range(_MAX_TOOL_LOOPS):
            try:
                if on_token is not None:
                    text, thinking, raw_tcs = self._complete_streaming(
                        oai_messages, tool_schemas, on_token=on_token, on_thinking=on_thinking
                    )
                else:
                    text, thinking, raw_tcs = self._complete(oai_messages, tool_schemas)
            except BackendError:
                raise

            if thinking and not final_thinking:
                final_thinking = thinking

            if not raw_tcs:
                final_text = text
                finish_reason = "stop"
                break

            # ── Process each tool call in this round ─────────────────────────
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

                # Strip routing meta-arg
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

                tool_exchanges.append({"name": name, "args": args, "result": result_for_context, "id": call_id})
                assistant_tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                })
                tool_result_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result_for_context),
                })

            # Append this round's assistant message + tool results
            oai_messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": assistant_tool_calls,
            })
            oai_messages.extend(tool_result_messages)

        else:
            finish_reason = "length"

        return final_text, final_thinking, tool_exchanges, finish_reason
