"""
Per-call output routing helpers shared by all backends.

These are intentionally kept pure (no I/O, no UI imports) so that both
the textgen backend and render_output can import them without side effects.
"""

import json
import re
from pathlib import Path
from typing import Callable

import jmespath

from ..approval import resolve_sink_path

# ── Variable-reference regex ─────────────────────────────────────────────────

# `$name` or `$name.<jmespath>` — name must be a valid identifier; the
# optional trailing path is anything after the first `.`.
_VARREF_RE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)(?:\.(.+))?$")


def _parse_var_ref(value: object) -> tuple[str, str | None] | None:
    """
    If `value` is a `$name` or `$name.<path>` reference, return (name, path).
    `path` is None when no `.` suffix is present.
    """
    if not isinstance(value, str):
        return None
    m = _VARREF_RE.match(value)
    if not m:
        return None
    return m.group(1), m.group(2)


def _is_var_ref(value: object) -> str | None:
    """Return the variable name if `value` is a `$name` or `$name.<path>` reference."""
    parsed = _parse_var_ref(value)
    return parsed[0] if parsed else None


def _compile_path(path: str) -> tuple[object | None, str | None]:
    """Compile a JMESPath expression. Returns (compiled, error_reason)."""
    try:
        return jmespath.compile(path), None
    except jmespath.exceptions.ParseError as e:
        return None, f"invalid jmespath {path!r}: {e}"


def _substitute_vars(args: dict, bindings: dict) -> tuple[dict, str | None]:
    """
    Replace any top-level arg value of the form '$name' (or '$name.<path>')
    with the bound value (optionally pathed via jmespath).
    Returns (substituted_args, error_reason). On miss, returns (args, reason).
    """
    out = {}
    for k, v in args.items():
        parsed = _parse_var_ref(v)
        if parsed is None:
            out[k] = v
            continue
        name, path = parsed
        if name not in bindings:
            return args, f"${name} not bound"
        value = bindings[name]
        if path is not None:
            compiled, perr = _compile_path(path)
            if perr is not None:
                return args, perr
            value = compiled.search(value)
            if value is None:
                return args, f"${name}.{path} not present"
        out[k] = value
    return out, None


def _split_display_path(sink: str) -> tuple[str, str | None]:
    """Split `display` or `display:<path>` into (sink, path)."""
    if sink == "display":
        return "display", None
    if sink.startswith("display:"):
        rest = sink[len("display:"):]
        return "display", rest if rest else None
    return sink, None


def _validate_sink(sink: str) -> str | None:
    """Return None if `sink` is a recognised output value, else an error reason."""
    if sink == "display":
        return None
    if sink.startswith("display:"):
        path = sink[len("display:"):]
        if not path:
            return "display: requires a non-empty jmespath after the colon"
        _, perr = _compile_path(path)
        return perr
    if sink.startswith("file:") and len(sink) > len("file:"):
        return None
    parsed = _parse_var_ref(sink)
    if parsed is not None:
        _, path = parsed
        if path is not None:
            _, perr = _compile_path(path)
            return perr
        return None
    return f"unknown sink: {sink!r}"


def _route_tool_result(
    *,
    name: str,
    result: object,
    sink: str | None,
    bindings: dict,
    on_tool_response: Callable[[str, object], None] | None,
    on_tool_routed: Callable[[str, object, str], None] | None,
    on_tool_denied: Callable[[str, str], None] | None,
    check_file_sink: Callable[[Path, Path, dict], tuple[str, str]] | None,
    sink_approval_prompt: Callable[[str, Path], bool] | None,
    approval_config: dict | None,
) -> object:
    """
    Resolve a per-call sink and produce the result value that will be
    serialised into the model's <|tool_response> token.

    sink=None         → inline; fires on_tool_response; returns the full result.
    sink="display"    → fires on_tool_routed; returns a status stub.
    sink="file:<p>"   → path policy via check_file_sink; on allow writes file.
    sink="$name"      → stores result in `bindings[name]`; status stub names
                        the binding. Re-binds overwrite silently but the
                        on_tool_routed sink string flags the rebind so it
                        appears in operator-facing traces.
    """
    if sink is None:
        if on_tool_response:
            on_tool_response(name, result)
        return result

    base, display_path = _split_display_path(sink) if sink.startswith("display") else (sink, None)
    if base == "display":
        if display_path is not None:
            compiled, _ = _compile_path(display_path)
            payload = compiled.search(result) if compiled is not None else None
        else:
            payload = result
        if on_tool_routed:
            on_tool_routed(name, payload, sink)
        return {"status": "ok", "output": "sent to display"}

    var = _is_var_ref(sink)
    if var is not None:
        rebound = var in bindings
        bindings[var] = result
        sink_label = f"var:${var}" + (" (rebind)" if rebound else "")
        if on_tool_routed:
            on_tool_routed(name, result, sink_label)
        return {"status": "ok", "output": f"bound to ${var}"}

    if sink.startswith("file:"):
        if check_file_sink is None:
            if on_tool_response:
                on_tool_response(name, result)
            return result

        abs_path = resolve_sink_path(sink[len("file:"):])
        action, reason = check_file_sink(abs_path, Path.cwd(), approval_config or {})
        if action == "ask":
            ok = sink_approval_prompt(name, abs_path) if sink_approval_prompt else False
            if ok:
                action = "allow"
            else:
                action = "deny"
                reason = "user denied"

        if action == "allow":
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(json.dumps(result, indent=2))
            if on_tool_routed:
                on_tool_routed(name, result, f"file:{abs_path}")
            return {"status": "ok", "output": f"written to {abs_path}"}

        if on_tool_denied:
            on_tool_denied(name, reason)
        return {"status": "denied", "reason": reason}

    # Should be unreachable thanks to _validate_sink upstream — defensive only.
    if on_tool_response:
        on_tool_response(name, result)
    return result
