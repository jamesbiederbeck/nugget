import abc
from typing import Callable


class BackendError(Exception):
    pass


class Backend(abc.ABC):
    """
    Abstract base class for all nugget backends.

    Each backend implements a `run()` method that takes a conversation
    history, tool schemas, a tool executor callable, and a system prompt,
    and returns a 4-tuple:

        (text, thinking, tool_exchanges, finish_reason)

    Where:
        text            — the model's final text response (may be empty)
        thinking        — chain-of-thought text, or None
        tool_exchanges  — list of dicts, each with keys "name", "args",
                          "result", recording every tool call made
        finish_reason   — the terminal finish reason string from the
                          upstream API ("stop", "length", etc.), or None

    After each `run()` call, `last_usage` is populated with token-count
    stats from the upstream API when available (keys: prompt_tokens,
    completion_tokens, total_tokens), or left as None.
    """

    last_usage: dict | None = None

    @abc.abstractmethod
    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        **kwargs,
    ) -> tuple[str, str | None, list[dict], str | None]:
        """Run one conversation turn and return (text, thinking, tool_exchanges, finish_reason)."""


def make_backend(config) -> Backend:
    name = config.get("backend", "textgen")
    if name == "textgen":
        from .textgen import TextgenBackend
        return TextgenBackend(config)
    if name == "openrouter":
        from .openrouter import OpenRouterBackend
        return OpenRouterBackend(config)
    raise ValueError(f"unknown backend: {name!r}")

