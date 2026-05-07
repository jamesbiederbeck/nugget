import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "nugget"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "backend": "textgen",
    "api_url": "http://127.0.0.1:5000",
    "model": "gemma-4-E4B-it-uncensored-Q4_K_M.gguf",
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 0.95,
    "top_k": 20,
    "sessions_dir": str(Path.home() / ".local" / "share" / "nugget" / "sessions"),
    "system_prompt": "You are a helpful assistant.",
    "append_datetime": True,
    "thinking_effort": 0,
    "show_thinking": False,
    "show_tool_calls": True,
    "show_tool_responses": False,
    "show_system_prompt": False,
    "debug": False,
    # OpenRouter backend config. api_key may also be set via OPENROUTER_API_KEY env var.
    "openrouter_api_key": "",
    "openrouter_model": "openai/gpt-4o-mini",
    # The "approval" section governs tool calls. Two additional *optional*
    # keys govern where tools with OUTPUT="file:<path>" may write:
    #
    #   "sink_rules": list of dicts (see nugget.approval.DEFAULT_SINK_RULES
    #       for the out-of-box policy). Absence means use the defaults:
    #       /tmp/nugget and $CWD are auto-allowed; anything that would
    #       overwrite an existing file asks; everything else asks.
    #
    #   "sink_conflict": "strictest" (default) or "first". Controls which
    #       action wins when multiple rules match the same path —
    #       "strictest" ranks deny > ask > allow; "first" takes the
    #       action of the first matching rule in list order.
    #
    # Both keys are left out of the auto-generated config so users see the
    # minimal defaults; add them explicitly to override.
    "approval": {
        "default": "allow",
        "rules": [
            {"tool": "shell", "action": "ask"},
            {"tool": "memory", "args": {"operation": "delete"}, "action": "ask"},
        ],
    },
    "subagent": {
        "max_depth": 2,
        "max_context_bytes": 32768,
        "max_turns_default": 4,
        "max_turns_cap": 16,
        "stream_inner": False,
        "default_system_prompt": (
            "You are a focused subagent. Read the provided context and return a "
            "concise answer to the task. Do not ask follow-up questions."
        ),
    },
}


class Config:
    def __init__(self, overrides: dict[str, Any] | None = None, profile: str | None = None):
        self._data = dict(DEFAULTS)
        self._raw_file_data: dict[str, Any] = {}
        self._profiles: dict[str, dict] = {}

        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                raw = json.load(f)
            self._profiles = raw.pop("profiles", {})
            self._raw_file_data = raw
            self._data.update(raw)

        if profile is not None:
            if profile not in self._profiles:
                available = sorted(self._profiles.keys())
                msg = f"unknown profile {profile!r}"
                if available:
                    msg += f"; available: {', '.join(available)}"
                raise ValueError(msg)
            self._data.update(self._profiles[profile])

        if overrides:
            self._data.update(overrides)

        if self._data.get("include_tools") and self._data.get("exclude_tools"):
            raise ValueError("include_tools and exclude_tools cannot both be set")

    def child_config(self, profile: str | None = None) -> "Config":
        """Build a child config: DEFAULTS → file base → profile (no CLI flag inheritance)."""
        if profile is not None and profile not in self._profiles:
            available = sorted(self._profiles.keys())
            msg = f"unknown profile {profile!r}"
            if available:
                msg += f"; available: {', '.join(available)}"
            raise ValueError(msg)
        child = Config.__new__(Config)
        child._raw_file_data = self._raw_file_data
        child._profiles = self._profiles
        child._data = dict(DEFAULTS)
        child._data.update(self._raw_file_data)
        if profile is not None:
            child._data.update(self._profiles[profile])
        return child

    def __getattr__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    @classmethod
    def ensure_default(cls) -> "Config":
        if not CONFIG_FILE.exists():
            c = cls()
            c.save()
        return cls()

    def approval_config(self) -> dict:
        return self._data.get("approval", DEFAULTS["approval"])

    def sessions_path(self) -> Path:
        p = Path(self._data["sessions_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p
