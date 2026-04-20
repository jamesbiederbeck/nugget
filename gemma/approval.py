"""
Approval resolution for tool calls.

Resolution order (first match wins):
  1. Config rules (ordered list, first matching rule wins)
  2. Tool's own APPROVAL gate (str or callable)
  3. Config default

Actions: "allow", "deny", "ask"

Config shape (in ~/.config/gemma/config.json):
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
from typing import Any, Callable

from . import display

VALID_ACTIONS = {"allow", "deny", "ask"}


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
    # 1. Config rules — first match wins
    for rule in approval_config.get("rules", []):
        if _match_rule(rule, tool_name, args):
            action = rule.get("action", "allow")
            return action if action in VALID_ACTIONS else "allow"

    # 2. Tool's own gate
    if tool_gate is not None:
        action = tool_gate(args) if callable(tool_gate) else tool_gate
        if action in VALID_ACTIONS:
            return action

    # 3. Config default
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
