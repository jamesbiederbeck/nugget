"""Templated variables available inside `system_prompt` (e.g. `{{ cwd }}`, `{{ git_branch }}`).

Rendering is best-effort: an unrenderable prompt (bad Jinja syntax, stray `{{`
typed as literal text) falls back to the raw string rather than raising, since
`system_prompt` is free-form user text, not an authored template.
"""

import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jinja2

_jinja_env = jinja2.Environment(undefined=jinja2.Undefined)


def _git(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_prompt_context(cwd: str | None = None) -> dict[str, Any]:
    """Assemble the variables available for interpolation in `system_prompt`."""
    cwd = cwd or str(Path.cwd())

    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    remotes_raw = _git(["remote", "-v"], cwd)
    remotes = ""
    repo_name = ""
    if remotes_raw:
        seen = []
        for line in remotes_raw.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in seen:
                seen.append(parts[0])
                remotes = ", ".join(seen)
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if toplevel:
        repo_name = Path(toplevel).name

    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "cwd": cwd,
        "hostname": hostname,
        "git_branch": branch or "",
        "git_remotes": remotes,
        "repo_name": repo_name,
    }


def render_system_prompt(text: str, cwd: str | None = None) -> str:
    """Render `{{ var }}` placeholders in `text` against build_prompt_context().

    Falls back to the original text unchanged if it isn't valid Jinja (or
    fails to render for any other reason), so plain-text prompts containing
    stray `{{`/`}}` are unaffected.
    """
    try:
        template = _jinja_env.from_string(text)
        return template.render(**build_prompt_context(cwd))
    except jinja2.TemplateError:
        return text
