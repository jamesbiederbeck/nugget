"""
Approval resolution for tool calls.

Resolution order (first match wins):
  1. Config rules (ordered list, first matching rule wins)
  2. Tool's own APPROVAL gate (str or callable)
  3. Config default

Actions: "allow", "deny", "ask"

Config shape (in ~/.config/nugget/config.json):
  "approval": {
    "default": "allow",
    "rules": [
      {"tool": "shell", "action": "ask"},
      {"tool": "memory", "args": {"operation": "delete"}, "action": "ask"},
      {"tool": "filebrowser", "args": {"operation": "cat"}, "action": "allow"}
    ]
  }

Tool gate shape (in tool module):
  APPROVAL = "ask"                          # always ask
  APPROVAL = "deny"                         # always deny
  def APPROVAL(args: dict) -> str: ...      # dynamic
"""

import sys
from pathlib import Path
from typing import Any, Callable

from . import display

VALID_ACTIONS = {"allow", "deny", "ask"}

# ── File-sink path policy ────────────────────────────────────────────────────
#
# Parallel to the tool-call approval system above. Governs *where* a tool
# whose OUTPUT is "file:<path>" may write. Keyed on the resolved absolute
# path, not the raw sink string.
#
# Rule match keys (exactly one per rule):
#   subtree: str    — path is equal to or inside this prefix; "$CWD" expands
#                     to the cwd arg at evaluation time
#   exact:   str    — path equals this one
#   existing: bool  — matches iff path.exists() equals the given bool
#   any:     bool   — matches iff the given bool is truthy
#
# Actions: "allow" | "deny" | "ask". Conflict resolution defaults to
# "strictest" (deny > ask > allow); set sink_conflict="first" to use the
# action of the first matching rule instead.

DEFAULT_SINK_RULES: list[dict] = [
    {"subtree": "/tmp/nugget", "action": "allow"},
    {"subtree": "$CWD",        "action": "allow"},
    {"existing": True,         "action": "ask"},
]
# Note: an explicit `{"any": True, "action": "ask"}` would interact badly
# with strictest conflict resolution by forcing every match to ≥ ask. The
# "no rule matched → ask" fallback inside check_file_sink covers the
# everything-else case without that side-effect.

_SINK_RANK = {"allow": 0, "ask": 1, "deny": 2}


def resolve_sink_path(raw: str, cwd: Path | None = None) -> Path:
    """
    Canonicalise a sink path. Expands ~, joins relative paths to `cwd`
    (defaulting to Path.cwd()), then calls Path.resolve() — which is the
    sole traversal defence. Do not sanitise strings before calling this.
    """
    base = cwd if cwd is not None else Path.cwd()
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def _match_sink_rule(rule: dict, abs_path: Path, cwd: Path) -> tuple[bool, str]:
    if "subtree" in rule:
        raw = rule["subtree"]
        expanded = str(cwd) if raw == "$CWD" else raw
        prefix = resolve_sink_path(expanded, cwd)
        if abs_path == prefix or prefix in abs_path.parents:
            return True, f"path is inside {prefix}"
        return False, ""
    if "exact" in rule:
        target = resolve_sink_path(rule["exact"], cwd)
        if abs_path == target:
            return True, f"exact match on {target}"
        return False, ""
    if "existing" in rule:
        want = bool(rule["existing"])
        if abs_path.exists() == want:
            state = "already exists" if want else "does not exist"
            return True, f"file {state} at {abs_path}"
        return False, ""
    if "any" in rule:
        if rule["any"]:
            return True, "matched any rule"
        return False, ""
    return False, ""


def check_file_sink(
    abs_path: Path,
    cwd: Path,
    config: dict,
) -> tuple[str, str]:
    """
    Apply sink rules to `abs_path`. Returns (action, reason).

    `abs_path` must already be resolved. `cwd` is used for `$CWD` expansion
    in subtree rules. `config` is the approval-config dict returned by
    Config.approval_config().
    """
    rules = config.get("sink_rules", DEFAULT_SINK_RULES)
    strategy = config.get("sink_conflict", "strictest")

    matches: list[tuple[str, str]] = []
    for rule in rules:
        matched, reason = _match_sink_rule(rule, abs_path, cwd)
        if not matched:
            continue
        action = rule.get("action", "ask")
        if action not in VALID_ACTIONS:
            action = "ask"
        matches.append((action, reason))

    if not matches:
        return "ask", "no sink rule matched"

    if strategy == "first":
        return matches[0]
    # strictest — highest rank wins
    return max(matches, key=lambda m: _SINK_RANK[m[0]])


def _match_rule(rule: dict, tool_name: str, args: dict) -> bool:
    if rule.get("tool") not in (tool_name, None, "*"):
        return False
    for k, v in rule.get("args", {}).items():
        if args.get(k) != v:
            return False
    return True


def _resolve_action(
    tool_name: str,
    args: dict,
    tool_gate: str | Callable | None,
    approval_config: dict,
) -> str:
    for rule in approval_config.get("rules", []):
        if _match_rule(rule, tool_name, args):
            action = rule.get("action", "allow")
            return action if action in VALID_ACTIONS else "allow"

    if tool_gate is not None:
        action = tool_gate(args) if callable(tool_gate) else tool_gate
        if action in VALID_ACTIONS:
            return action

    default = approval_config.get("default", "allow")
    return default if default in VALID_ACTIONS else "allow"


def check(
    tool_name: str,
    args: dict,
    tool_gate: Any,
    approval_config: dict,
) -> tuple[bool, str | None]:
    """
    Returns (approved: bool, denial_reason: str | None).
    Prompts the user when action is 'ask' and stdin is a tty.
    Non-interactive 'ask' falls back to deny.
    """
    action = _resolve_action(tool_name, args, tool_gate, approval_config)

    if action == "allow":
        return True, None

    if action == "deny":
        return False, f"tool '{tool_name}' blocked by approval policy"

    # action == "ask"
    if not sys.stdin.isatty():
        return False, f"tool '{tool_name}' requires approval (non-interactive: denied)"

    import json
    args_str = json.dumps(args, indent=2)
    print(f"\n{display.BOLD}{display.YELLOW}[approval]{display.RESET} "
          f"{display.CYAN}{tool_name}{display.RESET}")
    for line in args_str.splitlines():
        print(f"  {display.DIM}{line}{display.RESET}")
    try:
        answer = input(f"{display.BOLD}Allow? [y/N]{display.RESET} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = ""

    if answer in ("y", "yes"):
        return True, None
    return False, f"tool '{tool_name}' denied by user"
