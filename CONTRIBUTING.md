# Contributing to Nugget

## Setup

```bash
# Clone and install with dev deps
git clone <repo>
cd nugget
uv pip install -e ".[dev]"

# Install with web server support too
uv pip install -e ".[web,dev]"
```

You'll need a running [text-generation-webui](https://github.com/oobabooga/text-generation-webui) server at `http://127.0.0.1:5000` to run the full stack locally.

## Branching strategy

```
develop  →  staging  →  main
```

- **`develop`** — AI-generated and experimental work lands here. Tests run on every push; no Docker image is built.
- **`staging`** — Integration testing. Promote from `develop` via PR when a feature is ready to validate end-to-end. Tests run on push and a `staging`-tagged Docker image is published (`ghcr.io/<owner>/nugget:staging`).
- **`main`** — Stable, production releases only. Promote from `staging` via PR. On merge, the release pipeline runs: tests gate a Docker build, and a version tag + versioned image are created if the version in `pyproject.toml` changed.

PRs should flow `develop → staging` or `staging → main`. Direct commits to `main` are for meta changes (docs, version bumps) only.

## Running tests

```bash
uv run pytest

# Single file
uv run pytest tests/test_session.py

# Single test
uv run pytest tests/test_session.py::test_function_name -v
```

## Project layout

```
src/nugget/
  backends/
    __init__.py     # Backend ABC + make_backend() factory
    textgen.py      # text-generation-webui + Gemma 4 prompt format
    openrouter.py   # OpenRouter OpenAI-compatible backend
  tools/            # Auto-discovered tool modules (add new tools here)
  templates/
    system.j2       # System prompt template
  config.py
  session.py
  display.py
  approval.py
tool_docs/
  TOOL_SPEC.md      # Full API + tool schema reference
  CONFIG.md         # Config key reference with examples
  SUBAGENT_SPEC.md  # Subagent framework spec (v0.4)
```

## Architecture

**Request flow:** `__main__.py` → `Config` → `make_backend()` → `TextgenBackend.run()` → tool loop → `Session.save()`

The backend assembles a Gemma 4 prompt, calls the upstream `/v1/completions` endpoint, parses tool calls out of the raw completion text, executes them, and loops up to 16 times until no more tool calls remain.

## Adding a tool

Create `src/nugget/tools/my_tool.py` — it is auto-discovered at startup. The module must expose:

```python
SCHEMA = {
    "name": "my_tool",
    "description": "...",
    "parameters": { ... }  # JSON Schema
}

def execute(args: dict) -> dict:
    ...
```

Optionally add `APPROVAL = "allow"` / `"deny"` / `"ask"` (or a callable) to set the default approval gate. See `src/nugget/approval.py` for how three-level resolution works: config rules → tool's `APPROVAL` → config default.

## Adding a backend

1. Implement the `Backend` ABC in `src/nugget/backends/my_backend.py`. The `run()` method signature:

   ```python
   def run(
       self,
       messages: list[dict],
       tool_schemas: list[dict],
       tool_executor: Callable[[str, dict], object],
       system_prompt: str,
       **kwargs,
   ) -> tuple[str, str | None, list[dict], str | None]:
       """Return (text, thinking, tool_exchanges, finish_reason)."""
   ```

   The ABC and its full docstring live in `src/nugget/backends/__init__.py`.

2. Add a branch to `make_backend()` in `src/nugget/backends/__init__.py`.

## Configuration

Config lives at `~/.config/nugget/config.json` (created on first run). See [`tool_docs/CONFIG.md`](tool_docs/CONFIG.md) for the full key reference, JSON Schema, and annotated examples.

## Releasing

The version field in `pyproject.toml` is the single source of truth. There is no `__version__` in the source — the CLI reads the installed package version at runtime via `importlib.metadata`.

**Steps to cut a release:**

1. Bump `version` in `pyproject.toml` on a feature branch:
   ```toml
   version = "0.2.0"
   ```
2. Open and merge a PR to `main`. The PR template checklist will remind you.
3. On merge, `release.yml` runs tests, then:
   - Creates and pushes `v0.2.0` (skipped if that tag already exists)
   - Builds and pushes to GHCR: `ghcr.io/<owner>/nugget:0.2.0` and `ghcr.io/<owner>/nugget:latest`

Every push to `main` (release or not) also produces a SHA-tagged image: `ghcr.io/<owner>/nugget:<git-sha>`. The docker build is skipped if tests fail.
