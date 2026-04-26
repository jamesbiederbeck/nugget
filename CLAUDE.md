# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Nugget** is a CLI chat interface (`nugget`) and optional web server (`nugget-server`) for locally-hosted LLMs (default: Gemma 4 via text-generation-webui). It provides a tool-calling framework, session persistence, and a pinned-memory system.

## Commands

```bash
# Install for development (CLI only)
uv pip install -e .

# Install with web server support
uv pip install -e ".[web]"

# Install with dev/test deps
uv pip install -e ".[dev]"

# Run tests
uv run pytest

# Run a single test file
uv run pytest tests/test_session.py

# Run a single test by name
uv run pytest tests/test_session.py::test_function_name -v

# Run CLI
nugget
nugget "your message"
nugget -v --thinking "hard question"

# Run web server
nugget-server --host 127.0.0.1 --port 8000
```

## Branching strategy

`develop` → `staging` → `main`

- **`develop`**: experimental / AI-generated work; tests run on push, no Docker build
- **`staging`**: integration testing; tests + `staging`-tagged Docker image on push
- **`main`**: stable releases; full release pipeline (tests → tag → versioned Docker image)

PRs flow `develop → staging → main`. Direct commits to `main` are for meta changes only.

## Architecture

### Request flow

`__main__.py` → `Config` → `make_backend()` → `TextgenBackend.run()` → tool loop → `Session.save()`

The backend's `run()` method assembles a Gemma 4 prompt, calls the upstream `/v1/completions` endpoint, parses tool calls out of the raw completion text, executes them via `tool_executor`, and loops up to 16 times until there are no more tool calls.

### Key subsystems

**Backends** (`src/nugget/backends/`): Implement the `Backend` protocol — a `run()` method that takes messages, tool schemas, a tool executor callable, and a system prompt, and returns `(text, thinking, tool_exchanges)`. Register new backends in `make_backend()` in `backends/__init__.py`.

**Tools** (`src/nugget/tools/`): Auto-discovered at startup. Each module must expose `SCHEMA` (OpenAI function-calling format dict) and `execute(args: dict) -> dict`. An optional `APPROVAL` attribute (string `"allow"/"deny"/"ask"` or a callable) sets the default approval gate.

**Approval** (`src/nugget/approval.py`): Three-level resolution — config rules (first match) → tool's `APPROVAL` gate → config default. The `"ask"` action prompts interactively in CLI mode; in web mode all `"ask"` rules are silently converted to `"allow"`.

**Session** (`src/nugget/session.py`): JSON files at `~/.local/share/nugget/sessions/<id>.json`. Each file stores the full message list including thinking blocks and tool call/response pairs.

**Memory tool** (`src/nugget/tools/memory.py`): SQLite at `~/.local/share/nugget/memory.db`. Supports `store/recall/search/list/delete`. Memories with `pin=true` are injected into the system prompt at the start of every session.

**Prompt assembly** (`src/nugget/backends/textgen.py`): Uses a Jinja2 template (`src/nugget/templates/system.j2`) for the system turn, then manually formats Gemma 4 special tokens (`<|turn>`, `<|channel>thought`, `<|tool_call>`, `<|tool_response>`, etc.) for all conversation turns.

**Web server** (`src/nugget/server.py`): FastAPI app with SSE streaming. The `/api/sessions/{id}/chat` endpoint runs the backend in a background thread and emits typed events (`token`, `thinking`, `tool_call`, `tool_result`, `done`, `error`). Static files from `src/nugget/web/` are served at `/`.

### Configuration

Config lives at `~/.config/nugget/config.json`. `Config.ensure_default()` creates it on first run. See the full schema in `tool_docs/TOOL_SPEC.md`.

### Adding a tool

Create `src/nugget/tools/my_tool.py` with `SCHEMA`, `execute(args)`, and optionally `APPROVAL`. It is discovered automatically — no registration needed.

### Adding a backend

Implement the `Backend` protocol in `src/nugget/backends/my_backend.py`, then add a branch to `make_backend()` in `src/nugget/backends/__init__.py`.
