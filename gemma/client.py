"""
API client for /v1/completions — handles the full tool-call loop.
"""

import json
from typing import Callable

import requests

from .prompt import (
    build_prompt,
    format_tool_response_token,
    parse_thinking,
    parse_tool_call,
)


class CompletionError(Exception):
    pass


class Client:
    def __init__(self, config):
        self.cfg = config
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def _base_payload(self, **overrides) -> dict:
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "top_p": self.cfg.top_p,
            "top_k": self.cfg.top_k,
        }
        payload.update(overrides)
        return payload

    def _post(self, prompt: str, stop: list[str], stream: bool = False) -> requests.Response:
        url = f"{self.cfg.api_url}/v1/completions"
        payload = self._base_payload(prompt=prompt, stop=stop, stream=stream)
        if self.cfg.debug:
            print(json.dumps({"url": url, "payload": payload}, indent=2))
        resp = self._session.post(url, json=payload, stream=stream, timeout=120)
        resp.raise_for_status()
        return resp

    def _complete(self, prompt: str, stop: list[str]) -> tuple[str, str]:
        """Returns (text, finish_reason)."""
        resp = self._post(prompt, stop)
        data = resp.json()
        choice = data["choices"][0]
        return choice["text"], choice["finish_reason"]

    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        thinking_effort: int,
        on_thinking: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_response: Callable[[str, object], None] | None = None,
    ) -> tuple[str, str | None, list[dict]]:
        """
        Run a full completion with tool loop.

        Returns (final_text, thinking, tool_exchanges).
        tool_exchanges is a list of {name, args, result}.
        """
        has_tools = bool(tool_schemas)
        stop = ["<turn|>", "<|tool_response>"] if has_tools else ["<turn|>"]

        prompt = build_prompt(messages, tool_schemas, system_prompt, thinking_effort)
        accumulated = ""
        tool_exchanges: list[dict] = []
        thinking_out: str | None = None

        for _ in range(16):  # max tool call iterations
            text, finish_reason = self._complete(prompt, stop)
            accumulated += text

            if finish_reason == "length":
                break

            # Check if this generation contains a tool call.
            # finish_reason=="stop" fires for both natural stop AND hitting the
            # <|tool_response> stop sequence, so we can't rely on it alone.
            tc = parse_tool_call(accumulated)
            if tc is None:
                break  # No tool call → final answer

            name, args = tc
            if on_tool_call:
                on_tool_call(name, args)

            result = tool_executor(name, args)
            if on_tool_response:
                on_tool_response(name, result)

            tool_exchanges.append({"name": name, "args": args, "result": result})

            # Inject tool response and continue generation
            response_token = format_tool_response_token(name, result)
            prompt = prompt + accumulated + "<|tool_response>" + response_token
            accumulated = ""

        thinking_out, final_text = parse_thinking(accumulated)
        if thinking_out and on_thinking:
            on_thinking(thinking_out)

        return final_text, thinking_out, tool_exchanges
