import json

from nugget.commands import CommandContext, dispatch
from nugget.config import Config
from nugget.session import Session
from nugget.backends.textgen import TextgenBackend


def _ctx(tmp_path, session):
    cfg = Config({"backend": "textgen", "api_url": "http://127.0.0.1:5000"})
    backend = TextgenBackend(cfg)
    return CommandContext(
        session_cell=[session],
        cfg=cfg,
        active_schemas_cell=[[]],
        backend_cell=[backend],
        get_system_prompt=lambda: "You are helpful.",
        get_thinking_effort=lambda: 0,
        sessions_path=tmp_path,
        cli_overrides={},
        cli_include=None,
        cli_exclude=None,
    )


def test_export_writes_rendered_prompt_to_default_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = Session.new(tmp_path)
    session.add_user("hello there")
    ctx = _ctx(tmp_path, session)

    dispatch("/export", ctx)

    out_file = tmp_path / f"nugget-export-{session.id}.txt"
    assert out_file.exists()
    content = out_file.read_text()
    assert "hello there" in content
    assert "You are helpful." in content


def test_export_writes_to_given_path(tmp_path):
    session = Session.new(tmp_path)
    session.add_user("hi")
    ctx = _ctx(tmp_path, session)
    dest = tmp_path / "subdir" / "export.txt"

    dispatch(f"/export {dest}", ctx)

    assert dest.exists()
    assert "hi" in dest.read_text()
