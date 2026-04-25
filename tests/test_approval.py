from pathlib import Path

import pytest
from nugget.approval import (
    DEFAULT_SINK_RULES,
    _match_rule,
    _resolve_action,
    check,
    check_file_sink,
    resolve_sink_path,
)

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


# ── resolve_sink_path ─────────────────────────────────────────────────────────

def test_resolve_sink_path_strips_traversal(tmp_path):
    # We don't manually sanitise; resolve() canonicalises so the result has
    # no leftover `..` segments. The destination depends on the cwd depth.
    cwd = tmp_path / "a" / "b" / "c"
    cwd.mkdir(parents=True)
    result = resolve_sink_path("../../../d.txt", cwd=cwd)
    assert ".." not in result.parts
    # 3 levels up from a/b/c lands at tmp_path.
    assert result == (tmp_path / "d.txt").resolve()


def test_resolve_sink_path_relative_uses_cwd(tmp_path):
    result = resolve_sink_path("notes.md", cwd=tmp_path)
    assert result == tmp_path.resolve() / "notes.md"


def test_resolve_sink_path_expands_home(tmp_path):
    result = resolve_sink_path("~/x.txt", cwd=tmp_path)
    assert result == Path.home().resolve() / "x.txt"


def test_resolve_sink_path_preserves_absolute(tmp_path):
    result = resolve_sink_path("/etc/hosts", cwd=tmp_path)
    assert result == Path("/etc/hosts")


def test_resolve_sink_path_resolves_symlink(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("hi")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    result = resolve_sink_path(str(link))
    assert result == real.resolve()


def test_resolve_sink_path_default_cwd_is_path_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = resolve_sink_path("foo")
    assert result == tmp_path.resolve() / "foo"


# ── check_file_sink — strictest ───────────────────────────────────────────────

def test_check_file_sink_strictest_allow_plus_ask(tmp_path):
    cfg = {
        "sink_rules": [
            {"subtree": str(tmp_path), "action": "allow"},
            {"any": True, "action": "ask"},
        ],
        "sink_conflict": "strictest",
    }
    action, _ = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "ask"


def test_check_file_sink_strictest_allow_plus_deny(tmp_path):
    cfg = {
        "sink_rules": [
            {"subtree": str(tmp_path), "action": "allow"},
            {"any": True, "action": "deny"},
        ],
        "sink_conflict": "strictest",
    }
    action, _ = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "deny"


def test_check_file_sink_strictest_no_match_is_ask(tmp_path):
    cfg = {"sink_rules": [{"subtree": "/never", "action": "allow"}],
           "sink_conflict": "strictest"}
    action, reason = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "ask"
    assert "no sink rule" in reason


# ── check_file_sink — first ───────────────────────────────────────────────────

def test_check_file_sink_first_allow_before_ask(tmp_path):
    cfg = {
        "sink_rules": [
            {"subtree": str(tmp_path), "action": "allow"},
            {"any": True, "action": "ask"},
        ],
        "sink_conflict": "first",
    }
    action, _ = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "allow"


def test_check_file_sink_first_ask_before_allow(tmp_path):
    cfg = {
        "sink_rules": [
            {"any": True, "action": "ask"},
            {"subtree": str(tmp_path), "action": "allow"},
        ],
        "sink_conflict": "first",
    }
    action, _ = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "ask"


def test_check_file_sink_first_no_match_is_ask(tmp_path):
    cfg = {"sink_rules": [{"subtree": "/never", "action": "allow"}],
           "sink_conflict": "first"}
    action, _ = check_file_sink(tmp_path / "f.txt", tmp_path, cfg)
    assert action == "ask"


# ── $CWD expansion ────────────────────────────────────────────────────────────

def test_check_file_sink_cwd_token_uses_cwd_arg(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    here = tmp_path / "here"
    here.mkdir()

    cfg = {
        "sink_rules": [{"subtree": "$CWD", "action": "allow"}],
        "sink_conflict": "first",
    }
    target = here / "f.txt"
    # cwd=here matches; cwd=other does not.
    action_here, _ = check_file_sink(target.resolve(), here, cfg)
    action_other, _ = check_file_sink(target.resolve(), other, cfg)
    assert action_here == "allow"
    assert action_other == "ask"  # no rule matched → fallback


# ── existing rule ─────────────────────────────────────────────────────────────

def test_check_file_sink_existing_true_only_when_present(tmp_path):
    present = tmp_path / "present.txt"
    present.write_text("x")
    absent = tmp_path / "absent.txt"

    cfg = {
        "sink_rules": [{"existing": True, "action": "ask"}],
        "sink_conflict": "first",
    }
    a_present, _ = check_file_sink(present.resolve(), tmp_path, cfg)
    a_absent, _ = check_file_sink(absent.resolve(), tmp_path, cfg)
    assert a_present == "ask"
    assert a_absent == "ask"  # no match → fallback "ask" with no-match reason

    # Verify the reasons distinguish them.
    _, r_present = check_file_sink(present.resolve(), tmp_path, cfg)
    _, r_absent = check_file_sink(absent.resolve(), tmp_path, cfg)
    assert "already exists" in r_present
    assert "no sink rule" in r_absent


# ── DEFAULT_SINK_RULES integration ────────────────────────────────────────────

def test_default_rules_allow_tmp_nugget():
    cfg = {}  # no overrides → DEFAULT_SINK_RULES
    action, _ = check_file_sink(Path("/tmp/nugget/foo.json"), Path("/some/cwd"), cfg)
    assert action == "allow"


def test_default_rules_allow_under_cwd(tmp_path):
    cfg = {}
    target = tmp_path / "out.json"
    action, _ = check_file_sink(target.resolve(), tmp_path, cfg)
    assert action == "allow"


def test_default_rules_existing_outside_safe_zones(tmp_path):
    # Create a file outside the cwd safe zone, point cwd at a sibling.
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    target = outside_root / "important.txt"
    target.write_text("data")

    cwd = tmp_path / "project"
    cwd.mkdir()

    cfg = {}
    action, reason = check_file_sink(target.resolve(), cwd, cfg)
    # strictest of [existing→ask, any→ask] is ask.
    assert action == "ask"
    assert "already exists" in reason or "matched any rule" in reason


def test_default_rules_nonexistent_outside_safe_zones(tmp_path):
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    target = outside_root / "new.txt"
    cwd = tmp_path / "project"
    cwd.mkdir()

    action, _ = check_file_sink(target.resolve(), cwd, {})
    assert action == "ask"


def test_default_sink_rules_constant_is_list_of_rules():
    # Sanity: the constant is what we claim it is so config-comment docs match.
    assert isinstance(DEFAULT_SINK_RULES, list)
    actions = {r["action"] for r in DEFAULT_SINK_RULES}
    assert actions == {"allow", "ask"}
