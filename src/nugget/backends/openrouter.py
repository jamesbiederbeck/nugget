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
from . import _openai_chat
from ._routing import (
    _substitute_vars,
    _validate_sink,
    _route_tool_result,
)
from ..subagent import _tool_ctx

_DEFAULT_MODEL = "openai/gpt-4o-mini"
_MAX_TOOL_LOOPS = 16


class OpenRouterBackend(Backend):
    def __init__(self, config):
        self.cfg = config
        api_key = config.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
        raw_url = (
            config.get("api_url")
            or config.get("openrouter_base_url")
            or "https://openrouter.ai/api"
        ).rstrip("/")
        self._url = f"{raw_url}/v1/chat/completions"
        is_local = raw_url.startswith("http://localhost") or raw_url.startswith("http://127.")
        if not api_key and not is_local:
            raise ValueError(
                "OpenRouter backend requires an API key. "
                "Set 'openrouter_api_key' in config.json or the OPENROUTER_API_KEY environment variable."
            )
        self._session = requests.Session()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if not is_local:
            headers["HTTP-Referer"] = "https://github.com/jamesbiederbeck/nugget"
            headers["X-Title"] = "nugget"
        self._session.headers.update(headers)
        self._model = config.get("openrouter_model", _DEFAULT_MODEL)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        return _openai_chat.build_messages(messages, system_prompt)

    def _complete(
        self,
        oai_messages: list[dict],
        tool_schemas: list[dict],
    ) -> tuple[str, str | None, list[dict]]:
        text, thinking, tool_calls, usage = _openai_chat.complete(
            self._session, self._url, self._model, oai_messages, tool_schemas,
            temperature=self.cfg.get("temperature", 0.7),
            max_tokens=self.cfg.get("max_tokens", 2048),
            debug=self.cfg.get("debug", False),
        )
        self.last_usage = usage
        return text, thinking, tool_calls

    def _complete_streaming(
        self,
        oai_messages: list[dict],
        tool_schemas: list[dict],
        on_token: Callable[[str], None] | None,
        on_thinking: Callable[[str], None] | None,
        on_thinking_end: Callable[[], None] | None = None,
    ) -> tuple[str, str | None, list[dict]]:
        self.last_usage = None
        text, thinking, tool_calls, usage = _openai_chat.complete_streaming(
            self._session, self._url, self._model, oai_messages, tool_schemas,
            temperature=self.cfg.get("temperature", 0.7),
            max_tokens=self.cfg.get("max_tokens", 2048),
            on_token=on_token, on_thinking=on_thinking, on_thinking_end=on_thinking_end,
            debug=self.cfg.get("debug", False),
        )
        self.last_usage = usage
        return text, thinking, tool_calls

    # ── Main entry point ─────────────────────────────────────────────────────

    def run(
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
        **kwargs,
    ) -> tuple[str, str | None, list[dict], str | None]:
        # Build the running message list that we extend with each tool round.
        oai_messages = self._build_messages(messages, system_prompt)
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
                        oai_messages, tool_schemas, on_token=on_token, on_thinking=on_thinking,
                        on_thinking_end=on_thinking_end,
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
                            # Sink routing isn't supported for attachments in
                            # v1 — only the default (goes back to the model) path.
                            if sink is None and on_tool_response:
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
