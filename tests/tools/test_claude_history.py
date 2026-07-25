import json
import subprocess

from nugget.tools.claude_history import _project_dir, _session_preview, execute


# ── _project_dir ──────────────────────────────────────────────────────────────

def test_project_dir_slug(tmp_path, monkeypatch):
    monkeypatch.setattr("nugget.tools.claude_history.Path.home", lambda: tmp_path)
    result = _project_dir("/home/user/code/myproject")
    assert result == tmp_path / ".claude" / "projects" / "-home-user-code-myproject"


# ── _session_preview ──────────────────────────────────────────────────────────

def test_session_preview_string_content(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": "hello there"}}) + "\n")
    assert _session_preview(p) == "hello there"


def test_session_preview_list_content(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]},
            }
        )
        + "\n"
    )
    assert _session_preview(p) == "part one part two"


def test_session_preview_no_user_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"content": "hi"}}) + "\n")
    assert _session_preview(p) == ""


def test_session_preview_skips_malformed_json(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("not json\n" + json.dumps({"type": "user", "message": {"content": "ok"}}) + "\n")
    assert _session_preview(p) == "ok"


def test_session_preview_truncates(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": "x" * 500}}) + "\n")
    assert _session_preview(p, max_chars=10) == "x" * 10


# ── list ──────────────────────────────────────────────────────────────────────

def _write_session(proj_dir, name, content, mtime):
    proj_dir.mkdir(parents=True, exist_ok=True)
    p = proj_dir / f"{name}.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": content}}) + "\n")
    import os

    os.utime(p, (mtime, mtime))
    return p


def test_list_no_history_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("nugget.tools.claude_history.Path.home", lambda: tmp_path)
    result = execute({"operation": "list", "directory": "/nowhere"})
    assert "error" in result


def test_list_orders_by_mtime_desc_and_respects_top(tmp_path, monkeypatch):
    monkeypatch.setattr("nugget.tools.claude_history.Path.home", lambda: tmp_path)
    directory = "/home/user/code/myproject"
    proj_dir = _project_dir(directory)
    _write_session(proj_dir, "older", "first message", 1000)
    _write_session(proj_dir, "newer", "second message", 2000)
    _write_session(proj_dir, "newest", "third message", 3000)

    result = execute({"operation": "list", "directory": directory, "top": 2})
    sessions = json.loads(result["output"])
    assert [s["session"] for s in sessions] == ["newest", "newer"]
    assert sessions[0]["preview"] == "third message"


def test_list_default_directory_is_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr("nugget.tools.claude_history.Path.home", lambda: tmp_path)
    monkeypatch.setattr("os.getcwd", lambda: "/some/cwd")
    proj_dir = _project_dir("/some/cwd")
    _write_session(proj_dir, "s1", "hi", 1000)

    result = execute({"operation": "list"})
    sessions = json.loads(result["output"])
    assert len(sessions) == 1


# ── search / within / read / outline (subprocess-backed) ──────────────────────

def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_search_requires_query():
    assert "error" in execute({"operation": "search"})


def test_search_builds_command(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    result = execute(
        {
            "operation": "search",
            "query": "some bug",
            "scope": "global",
            "top": 5,
            "hits_per_conv": 3,
            "search_mode": "semantic",
        }
    )
    assert result == {"output": "ok"}
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["claude-history", "agent", "search"]
    assert "--all" in cmd
    assert "--local" not in cmd
    assert "--top" in cmd and "5" in cmd
    assert "--hits-per-conv" in cmd and "3" in cmd
    assert "--semantic" in cmd
    assert cmd[-1] == "some bug"


def test_search_local_scope_default(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    execute({"operation": "search", "query": "x"})
    cmd = run.call_args.args[0]
    assert "--local" in cmd
    assert "--all" not in cmd


def test_within_requires_conversation_and_query():
    assert "error" in execute({"operation": "within", "query": "x"})
    assert "error" in execute({"operation": "within", "conversation": "ch_1"})


def test_within_builds_command(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    result = execute(
        {"operation": "within", "conversation": "ch_1234", "query": "topic", "top": 7, "search_mode": "lexical"}
    )
    assert result == {"output": "ok"}
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["claude-history", "agent", "within"]
    assert "--top" in cmd and "7" in cmd
    assert "--lexical" in cmd
    assert cmd[-2:] == ["ch_1234", "topic"]


def test_read_requires_refs_or_conversation():
    assert "error" in execute({"operation": "read"})


def test_read_uses_conversation_as_ref_fallback(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    result = execute({"operation": "read", "conversation": "ch_1234"})
    assert result == {"output": "ok"}
    cmd = run.call_args.args[0]
    assert cmd[-1] == "ch_1234"


def test_read_builds_flags(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    execute(
        {
            "operation": "read",
            "refs": ["ch_1234:m7..m9"],
            "focus": "m8..m8",
            "budget": 4000,
            "include_tools": True,
            "include_tool_results": True,
            "include_thinking": True,
        }
    )
    cmd = run.call_args.args[0]
    assert "--budget" in cmd and "4000" in cmd
    assert "--tools" in cmd
    assert "--tool-results" in cmd
    assert "--thinking" in cmd
    assert "--focus" in cmd and "m8..m8" in cmd
    assert cmd[-1] == "ch_1234:m7..m9"


def test_outline_requires_conversation():
    assert "error" in execute({"operation": "outline"})


def test_outline_builds_command(mocker):
    run = mocker.patch("nugget.tools.claude_history.subprocess.run", return_value=_completed(stdout="ok"))
    result = execute({"operation": "outline", "conversation": "ch_1234", "budget": 2000})
    assert result == {"output": "ok"}
    cmd = run.call_args.args[0]
    assert cmd[:3] == ["claude-history", "agent", "outline"]
    assert "--budget" in cmd and "2000" in cmd
    assert cmd[-1] == "ch_1234"


def test_unknown_operation():
    result = execute({"operation": "bogus"})
    assert "error" in result


def test_subprocess_nonzero_returncode(mocker):
    mocker.patch(
        "nugget.tools.claude_history.subprocess.run",
        return_value=_completed(stderr="boom", returncode=1),
    )
    result = execute({"operation": "outline", "conversation": "ch_1"})
    assert result == {"error": "boom"}


def test_subprocess_nonzero_no_stderr(mocker):
    mocker.patch(
        "nugget.tools.claude_history.subprocess.run",
        return_value=_completed(stderr="", returncode=2),
    )
    result = execute({"operation": "outline", "conversation": "ch_1"})
    assert result == {"error": "claude-history exited with code 2"}


def test_binary_not_found(mocker):
    mocker.patch("nugget.tools.claude_history.subprocess.run", side_effect=FileNotFoundError)
    result = execute({"operation": "outline", "conversation": "ch_1"})
    assert result == {"error": "claude-history not found — install it first"}


def test_timeout(mocker):
    mocker.patch(
        "nugget.tools.claude_history.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude-history", timeout=60),
    )
    result = execute({"operation": "outline", "conversation": "ch_1"})
    assert result == {"error": "timed out after 60s"}
