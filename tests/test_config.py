import json
import pytest
from nugget.config import Config, DEFAULTS


def test_defaults_loaded(tmp_config_file):
    cfg = Config()
    assert cfg.backend == "textgen"
    assert cfg.temperature == DEFAULTS["temperature"]
    assert cfg.max_tokens == DEFAULTS["max_tokens"]
    assert cfg.thinking_effort == 0


def test_overrides_applied(tmp_config_file):
    cfg = Config({"temperature": 0.1, "max_tokens": 512})
    assert cfg.temperature == 0.1
    assert cfg.max_tokens == 512
    assert cfg.model == DEFAULTS["model"]  # non-overridden key stays default


def test_getattr_missing_key(tmp_config_file):
    cfg = Config()
    with pytest.raises(AttributeError):
        _ = cfg.nonexistent_key


def test_get_with_default(tmp_config_file):
    cfg = Config()
    assert cfg.get("nonexistent", "fallback") == "fallback"
    assert cfg.get("backend") == "textgen"


def test_save_and_reload(tmp_config_file, monkeypatch):
    cfg = Config({"temperature": 0.99})
    cfg.save()
    assert tmp_config_file.exists()
    loaded = Config()
    assert loaded.temperature == 0.99


def test_file_config_merged_with_defaults(tmp_config_file):
    tmp_config_file.write_text(json.dumps({"temperature": 0.3}))
    cfg = Config()
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == DEFAULTS["max_tokens"]


def test_overrides_win_over_file(tmp_config_file):
    tmp_config_file.write_text(json.dumps({"temperature": 0.3}))
    cfg = Config({"temperature": 0.99})
    assert cfg.temperature == 0.99


def test_ensure_default_creates_file(tmp_config_file):
    assert not tmp_config_file.exists()
    Config.ensure_default()
    assert tmp_config_file.exists()


def test_ensure_default_idempotent(tmp_config_file):
    Config.ensure_default()
    Config.ensure_default()
    assert tmp_config_file.exists()


def test_approval_config_default(tmp_config_file):
    cfg = Config()
    approval = cfg.approval_config()
    assert "default" in approval
    assert "rules" in approval


def test_sessions_path_created(tmp_config_file, tmp_path):
    sessions_dir = tmp_path / "sessions"
    cfg = Config({"sessions_dir": str(sessions_dir)})
    path = cfg.sessions_path()
    assert path.exists()
    assert path.is_dir()


# ── Profile tests ─────────────────────────────────────────────────────────────

_PROFILE_CONFIG = {
    "temperature": 0.7,
    "profiles": {
        "lean": {
            "temperature": 0.3,
            "max_tokens": 512,
        },
        "strict": {
            "approval": {"default": "ask", "rules": []},
            "temperature": 0.1,
        },
    },
}


def test_profile_applied(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    cfg = Config(profile="lean")
    assert cfg.temperature == 0.3
    assert cfg.max_tokens == 512


def test_profile_unknown_raises(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    with pytest.raises(ValueError, match="unknown profile"):
        Config(profile="nonexistent")


def test_profile_unknown_lists_available(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    with pytest.raises(ValueError, match="lean"):
        Config(profile="nonexistent")


def test_profile_cli_flags_win(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    cfg = Config({"temperature": 0.99}, profile="lean")
    assert cfg.temperature == 0.99
    assert cfg.max_tokens == 512


def test_profile_nested_block_replacement(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    cfg = Config(profile="strict")
    assert cfg.approval_config()["default"] == "ask"
    assert cfg.approval_config()["rules"] == []


def test_no_profile_uses_base(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    cfg = Config()
    assert cfg.temperature == 0.7


def test_profiles_stripped_from_data(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    cfg = Config()
    assert cfg.get("profiles") is None


def test_child_config_no_profile(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    parent = Config({"temperature": 0.99}, profile="lean")
    child = parent.child_config()
    assert child.temperature == 0.7  # file base, not parent CLI flag or profile


def test_child_config_with_profile(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    parent = Config()
    child = parent.child_config("lean")
    assert child.temperature == 0.3
    assert child.max_tokens == 512


def test_child_config_unknown_profile(tmp_config_file):
    tmp_config_file.write_text(json.dumps(_PROFILE_CONFIG))
    parent = Config()
    with pytest.raises(ValueError, match="unknown profile"):
        parent.child_config("ghost")


def test_include_exclude_mutually_exclusive(tmp_config_file):
    tmp_config_file.write_text(json.dumps({
        "profiles": {
            "bad": {"include_tools": ["a"], "exclude_tools": ["b"]},
        }
    }))
    with pytest.raises(ValueError, match="include_tools and exclude_tools"):
        Config(profile="bad")
