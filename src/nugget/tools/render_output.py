"""
render_output — call any tool and route its result to a sink.

The model calls this tool when it wants to display a result, write it to a
file, or bind it to a variable, rather than receiving the raw result inline.

Supported output sinks (passed as the `output` arg):
  display               Print to the user.
  display:<jmespath>    Extract a field, then print.
  file:<path>           Write JSON to a file (subject to file-sink policy).
  $name                 Bind to a turn-scoped variable for later substitution.

Design note: render_output calls the wrapped tool's execute() directly, so
  the wrapped tool cannot itself use output routing or produce turn-variable
  bindings accessible from later tool calls. This is intentional — recursive
  routing is not supported.

Approval note: only the wrapped tool's own APPROVAL gate is consulted here.
  Config-level approval rules are not evaluated when the wrapped tool is
  invoked from inside render_output.
"""

from ..backends._routing import _validate_sink, _route_tool_result
from ..approval import check_file_sink, check as approval_check, _resolve_action
from ..subagent import _event_callbacks
from .. import tools as tool_registry

SCHEMA = {
    "type": "function",
    "function": {
        "name": "render_output",
        "description": (
            "Call any tool and send its output somewhere. "
            "Use this when you want to display a tool's result to the user, "
            "save it to a file, or bind it to a variable — "
            "instead of calling the tool directly and receiving the result inline. "
            "Specify the destination with the output argument. "
            "Note: render_output calls the wrapped tool directly; the wrapped tool "
            "cannot itself use output routing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to call, e.g. 'wallabag' or 'shell'",
                },
                "tool_args": {
                    "type": "object",
                    "description": "Arguments to pass to the tool",
                },
                "output": {
                    "type": "string",
                    "description": (
                        "Where to send the result. One of: "
                        "'display' (show to user), "
                        "'display:<jmespath>' (extract field then show), "
                        "'file:<path>' (write JSON to file), "
                        "'$name' (bind to a variable)."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "text"],
                    "description": (
                        "Rendering hint for display sinks. "
                        "'markdown' renders rich formatting (default). "
                        "'text' renders as plain text."
                    ),
                },
            },
            "required": ["tool_name", "tool_args", "output"],
        },
    },
}

APPROVAL = "allow"


def execute(args: dict) -> dict:
    tool_name = args.get("tool_name")
    tool_args = args.get("tool_args")
    # `output` is present when called directly (e.g. in tests).
    # When called via the backend tool loop, the backend has already stripped
    # `output` as a meta-arg and will handle routing itself; in that case
    # this defaults to None and the raw result is returned inline.
    output = args.get("output")
    fmt = args.get("format", "markdown")

    # ── Validate inputs ──────────────────────────────────────────────────────
    if not tool_name:
        return {"status": "error", "reason": "tool_name is required"}
    if not isinstance(tool_args, dict):
        return {"status": "error", "reason": "tool_args must be an object"}

    # ── Validate sink ────────────────────────────────────────────────────────
    if output is not None:
        sink_err = _validate_sink(output)
        if sink_err:
            return {"status": "error", "reason": sink_err}

    # ── Check wrapped tool exists ────────────────────────────────────────────
    if tool_name not in tool_registry.list_names():
        return {"status": "error", "reason": f"unknown tool: {tool_name!r}"}

    # ── Check approval for the wrapped tool (gate only, no config rules) ─────
    gate = tool_registry.gate(tool_name)
    action = _resolve_action(tool_name, tool_args, gate, {})
    if action == "deny":
        return {"status": "error", "reason": f"tool '{tool_name}' blocked by approval policy"}
    if action == "ask":
        cb = _event_callbacks.get() or {}
        web_ask = cb.get("web_ask")
        if web_ask is not None:
            approved, reason = web_ask(tool_name, tool_args)
        else:
            approved, reason = approval_check(tool_name, tool_args, gate, {})
        if not approved:
            return {"status": "error", "reason": reason}

    # ── Execute the wrapped tool ─────────────────────────────────────────────
    result = tool_registry.execute(tool_name, tool_args)

    # ── Route result ─────────────────────────────────────────────────────────
    if output is None:
        # Backend handles routing via the outer sink. Wrap with format hint
        # so the display layer knows how to render — the model only sees the
        # {"status": "ok", "output": "sent to display"} stub, never this wrapper.
        return {"_display_format": fmt, "_content": result}

    bindings: dict = {}
    return _route_tool_result(
        name=tool_name,
        result=result,
        sink=output,
        bindings=bindings,
        on_tool_response=None,
        on_tool_routed=None,
        on_tool_denied=None,
        check_file_sink=check_file_sink,
        sink_approval_prompt=None,
        approval_config={},
    )

