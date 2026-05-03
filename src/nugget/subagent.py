"""
Subagent helpers — system-prompt assembly, context rendering, depth tracking,
and ContextVar-based harness injection for spawn_agent.

Three ContextVars are used to thread harness state into tool execute() calls
without changing the tool registry protocol (which only passes `args: dict`):

  _tool_ctx        Set by each backend before calling tool_executor. Carries
                   backend, bindings, and config for the current tool call.

  _session_id      Set by __main__ and server before backend.run(). Identifies
                   the parent session for persistence.

  _depth           Incremented across recursive spawn_agent calls. Enforces
                   subagent.max_depth from config.

  _event_callbacks Set by server.py to receive subagent_call / subagent_done
                   SSE events. Not set in CLI mode (events are silent there).
"""

import contextvars
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── ContextVars ──────────────────────────────────────────────────────────────

_tool_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "nugget_tool_ctx", default=None
)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "nugget_session_id", default=None
)
_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "nugget_subagent_depth", default=0
)
_event_callbacks: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "nugget_subagent_events", default=None
)

# ── Context rendering ────────────────────────────────────────────────────────

_DEFAULT_SYSTEM_PROMPT = (
    "You are a focused subagent. Read the provided context and return a "
    "concise answer to the task. Do not ask follow-up questions."
)


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return repr(value)


def build_child_system_prompt(
    task: str,
    context: dict[str, Any],
    base_prompt: str,
    max_context_bytes: int,
) -> tuple[str, bool]:
    """
    Build the child session's system prompt from task + context blobs.
    Returns (prompt, truncated) where truncated=True if any context was cut.
    """
    parts: list[str] = [base_prompt, ""]
    truncated = False

    if context:
        parts.append("## Provided context")
        parts.append("")
        total_bytes = 0
        for name, value in context.items():
            block = f"### {name}\n{_render_value(value)}"
            block_bytes = len(block.encode())
            if total_bytes + block_bytes > max_context_bytes:
                remaining = max(0, max_context_bytes - total_bytes)
                if remaining > 0:
                    cut = block.encode()[:remaining].decode(errors="replace")
                    omitted = block_bytes - remaining
                    parts.append(cut)
                    parts.append(f"... [truncated, {omitted} bytes omitted]")
                else:
                    parts.append(f"### {name}\n... [truncated, {block_bytes} bytes omitted]")
                truncated = True
                break
            parts.append(block)
            total_bytes += block_bytes
        parts.append("")

    parts.append("## Task")
    parts.append("")
    parts.append(task)
    return "\n".join(parts), truncated


# ── Persistence ───────────────────────────────────────────────────────────────

def save_subagent_call(
    parent_id: str,
    call_id: str,
    sessions_dir: Path,
    data: dict,
) -> None:
    subdir = sessions_dir / parent_id / "subagents"
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / f"{call_id}.json").write_text(json.dumps(data, indent=2))


def new_call_id() -> str:
    return str(uuid.uuid4())[:8]
