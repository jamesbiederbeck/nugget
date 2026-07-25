import subprocess

from nugget.prompt_context import build_prompt_context, render_system_prompt


def test_render_plain_text_unchanged():
    assert render_system_prompt("You are a helpful assistant.") == "You are a helpful assistant."


def test_render_cwd_and_hostname(tmp_path):
    ctx = build_prompt_context(cwd=str(tmp_path))
    assert ctx["cwd"] == str(tmp_path)
    assert ctx["hostname"]
    assert ctx["now"]


def test_render_unknown_var_is_blank():
    assert render_system_prompt("Hello {{ nonexistent }}!") == "Hello !"


def test_render_invalid_jinja_falls_back():
    text = "Weird prompt with {{ unclosed"
    assert render_system_prompt(text) == text


def test_render_git_vars_in_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://example.com/x.git"], cwd=tmp_path, check=True)
    result = render_system_prompt(
        "repo={{ repo_name }} remotes={{ git_remotes }}", cwd=str(tmp_path)
    )
    assert f"repo={tmp_path.name}" in result
    assert "remotes=origin" in result


def test_render_git_vars_outside_repo(tmp_path):
    result = render_system_prompt("branch=[{{ git_branch }}]", cwd=str(tmp_path))
    assert result == "branch=[]"
