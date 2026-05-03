"""
spawn_agent — spawn a focused child Nugget session to handle a delegated task.

The child runs the same Backend.run() machinery as the parent, but with:
  - A fresh in-memory message history
  - A custom system prompt seeded with the provided context
  - An optionally-narrower tool allowlist
  - A recursion-depth cap enforced via contextvars

Result flows through the standard output-routing machinery (sink meta-arg).
"""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..subagent import (
    _tool_ctx,
    _session_id,
    _depth,
    _event_callbacks,
    build_child_system_prompt,
    save_subagent_call,
    new_call_id,
    _DEFAULT_SYSTEM_PROMPT,
)

SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "Spawn a focused sub-session to handle a delegated task. "
            "The child session runs with a custom system prompt, the provided "
            "context, and a tool allowlist. Returns the child's final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What the subagent should accomplish, in plain English.",
                },
                "context": {
                    "type": "object",
                    "description": "Inline named context blobs to inject into the child's system prompt.",
                },
                "context_vars": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of turn-bound variables ($var) to inject into the child's context.",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional custom system prompt for the child. Defaults to a focused-assistant template.",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Allowlist of tool names available to the child. Default: empty (no tools — pure reasoning).",
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Tool-loop iteration cap for the child (default 4, max 16).",
                },
                "return_thinking": {
                    "type": "boolean",
                    "description": "If true, include the child's chain-of-thought in the result. Default false.",
                },
                "skill": {
                    "type": "string",
                    "description": "Reserved. Skill-bundle integration — accepted but ignored in v0.4.",
                },
            },
            "required": ["task"],
        },
    },
}

APPROVAL = "ask"


def execute(args: dict) -> dict:
    from .. import tools as tool_registry
    from .. import approval as approval_mod

    task = args.get("task", "").strip()
    if not task:
        return {"error": "task is required"}

    # ── Read harness context from ContextVars ────────────────────────────────
    ctx = _tool_ctx.get()
    if ctx is None:
        return {"error": "spawn_agent: no harness context — cannot spawn outside a backend run()"}

    backend = ctx["backend"]
    bindings = ctx["bindings"]
    config = ctx["config"]
    parent_sid = _session_id.get()

    # ── Depth check ──────────────────────────────────────────────────────────
    current_depth = _depth.get()
    max_depth = config.get("subagent", {}).get("max_depth", 2)
    if current_depth >= max_depth:
        return {"_denied": True, "reason": "subagent depth limit exceeded"}

    # ── Resolve context_vars from parent bindings ────────────────────────────
    context: dict = dict(args.get("context") or {})
    for var_name in (args.get("context_vars") or []):
        if var_name not in bindings:
            return {"error": f"${var_name} not bound"}
        context[var_name] = bindings[var_name]

    # ── Build child system prompt ────────────────────────────────────────────
    subagent_cfg = config.get("subagent", {})
    base_prompt = args.get("system_prompt") or subagent_cfg.get(
        "default_system_prompt", _DEFAULT_SYSTEM_PROMPT
    )
    max_context_bytes = subagent_cfg.get("max_context_bytes", 32768)
    child_system_prompt, truncated = build_child_system_prompt(
        task, context, base_prompt, max_context_bytes
    )

    # ── Build child tool schemas (allowlist) ─────────────────────────────────
    allowed_tools: list[str] | None = args.get("tools") or None
    if allowed_tools is not None:
        child_schemas = tool_registry.schemas(include=allowed_tools)
    else:
        child_schemas = []

    # ── Child tool executor with approval ───────────────────────────────────
    approval_config = config.approval_config()

    def child_tool_executor(name: str, child_args: dict) -> object:
        approved, reason = approval_mod.check(
            name, child_args, tool_registry.gate(name), approval_config
        )
        if not approved:
            return {"_denied": True, "reason": reason}
        # Inject harness context for nested spawn_agent calls
        child_ctx = {
            "backend": backend,
            "bindings": child_bindings,
            "config": config,
        }
        token = _tool_ctx.set(child_ctx)
        try:
            return tool_registry.execute(name, child_args)
        finally:
            _tool_ctx.reset(token)

    child_bindings: dict = {}

    # ── Emit subagent_call SSE event (web mode) ──────────────────────────────
    cbs = _event_callbacks.get()
    if cbs and cbs.get("on_subagent_call"):
        cbs["on_subagent_call"](
            task=task,
            tool_count=len(child_schemas),
            parent_depth=current_depth,
        )

    # ── Run child session ────────────────────────────────────────────────────
    max_turns_default = subagent_cfg.get("max_turns_default", 4)
    max_turns_cap = subagent_cfg.get("max_turns_cap", 16)
    max_turns = min(int(args.get("max_turns") or max_turns_default), max_turns_cap)

    depth_token = _depth.set(current_depth + 1)
    t0 = time.perf_counter()
    try:
        child_text, child_thinking, child_exchanges, child_finish = backend.run(
            messages=[{"role": "user", "content": task}],
            tool_schemas=child_schemas,
            tool_executor=child_tool_executor,
            system_prompt=child_system_prompt,
        )
    except Exception as e:
        return {"error": f"subagent error: {e}"}
    finally:
        _depth.reset(depth_token)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # ── Build result ─────────────────────────────────────────────────────────
    result: dict = {
        "answer": child_text,
        "tool_calls": len(child_exchanges),
        "finish_reason": child_finish,
        "truncated_context": truncated,
    }
    if args.get("return_thinking") and child_thinking:
        result["thinking"] = child_thinking

    # ── Persist per-call transcript ──────────────────────────────────────────
    if parent_sid is not None:
        call_id = new_call_id()
        sessions_dir = config.sessions_path()
        save_subagent_call(
            parent_id=parent_sid,
            call_id=call_id,
            sessions_dir=sessions_dir,
            data={
                "call_id": call_id,
                "parent_session_id": parent_sid,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": elapsed_ms,
                "task": task,
                "system_prompt": child_system_prompt,
                "tool_allowlist": allowed_tools,
                "truncated_context": truncated,
                "messages": [
                    {"role": "user", "content": task},
                    {
                        "role": "assistant",
                        "content": child_text,
                        **({"thinking": child_thinking} if child_thinking else {}),
                        **({"tool_calls": child_exchanges} if child_exchanges else {}),
                    },
                ],
                "finish_reason": child_finish,
            },
        )

    # ── Emit subagent_done SSE event (web mode) ──────────────────────────────
    if cbs and cbs.get("on_subagent_done"):
        cbs["on_subagent_done"](
            answer=child_text,
            tool_calls=len(child_exchanges),
            finish_reason=child_finish,
        )

    return result
