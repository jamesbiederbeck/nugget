import pytest
from nugget.approval import _match_rule, _resolve_action, check

_APPROVAL_CFG = {
    "default": "allow",
    "rules": [
        {"tool": "shell", "action": "ask"},
        {"tool": "memory", "args": {"operation": "delete"}, "action": "ask"},
        {"tool": "filebrowser", "args": {"operation": "cat"}, "action": "allow"},
    ],
}


# ── _match_rule ───────────────────────────────────────────────────────────────

def test_match_rule_by_tool_name():
    rule = {"tool": "shell", "action": "ask"}
    assert _match_rule(rule, "shell", {}) is True
    assert _match_rule(rule, "memory", {}) is False


def test_match_rule_with_args():
    rule = {"tool": "memory", "args": {"operation": "delete"}, "action": "ask"}
    assert _match_rule(rule, "memory", {"operation": "delete"}) is True
    assert _match_rule(rule, "memory", {"operation": "store"}) is False


def test_match_rule_wildcard():
    rule = {"tool": "*", "action": "deny"}
    assert _match_rule(rule, "anything", {}) is True


def test_match_rule_no_tool_key():
    rule = {"action": "deny"}
    assert _match_rule(rule, "shell", {}) is True


def test_match_rule_partial_args():
    rule = {"tool": "memory", "args": {"operation": "delete"}, "action": "ask"}
    # Extra args in the call should still match if the required ones are present
    assert _match_rule(rule, "memory", {"operation": "delete", "key": "x"}) is True


# ── _resolve_action ───────────────────────────────────────────────────────────

def test_config_rule_wins_over_gate():
    # shell is "ask" in config; tool gate says "allow" — config wins
    result = _resolve_action("shell", {}, "allow", _APPROVAL_CFG)
    assert result == "ask"


def test_gate_used_when_no_rule_matches():
    result = _resolve_action("calculator", {}, "deny", _APPROVAL_CFG)
    assert result == "deny"


def test_default_used_when_no_rule_and_no_gate():
    result = _resolve_action("calculator", {}, None, _APPROVAL_CFG)
    assert result == "allow"


def test_args_rule_match():
    result = _resolve_action("memory", {"operation": "delete"}, None, _APPROVAL_CFG)
    assert result == "ask"


def test_args_rule_no_match_falls_to_default():
    result = _resolve_action("memory", {"operation": "store"}, None, _APPROVAL_CFG)
    assert result == "allow"


def test_callable_gate():
    gate = lambda args: "deny" if args.get("dangerous") else "allow"
    assert _resolve_action("calculator", {"dangerous": True}, gate, {"default": "allow", "rules": []}) == "deny"
    assert _resolve_action("calculator", {}, gate, {"default": "allow", "rules": []}) == "allow"


# ── check() ───────────────────────────────────────────────────────────────────

def test_check_allow():
    approved, reason = check("calculator", {}, None, {"default": "allow", "rules": []})
    assert approved is True
    assert reason is None


def test_check_deny():
    approved, reason = check("badtool", {}, None, {"default": "deny", "rules": []})
    assert approved is False
    assert reason is not None


def test_check_ask_non_interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    approved, reason = check("shell", {}, None, _APPROVAL_CFG)
    assert approved is False
    assert reason is not None


def test_check_ask_interactive_yes(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    approved, reason = check("shell", {}, None, _APPROVAL_CFG)
    assert approved is True


def test_check_ask_interactive_no(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    approved, reason = check("shell", {}, None, _APPROVAL_CFG)
    assert approved is False


def test_check_ask_interactive_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    approved, reason = check("shell", {}, None, _APPROVAL_CFG)
    assert approved is False
