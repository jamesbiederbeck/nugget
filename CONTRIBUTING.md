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
  backends/         # Backend protocol + make_backend() factory
  tools/            # Auto-discovered tool modules
  templates/
    system.j2       # System prompt template
  config.py
  session.py
  display.py
  approval.py
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

1. Implement the `Backend` protocol in `src/nugget/backends/my_backend.py`. The `run()` method signature:

   ```python
   def run(self, messages, tools, tool_executor, system_prompt) -> (text, thinking, tool_exchanges):
   ```

2. Add a branch to `make_backend()` in `src/nugget/backends/__init__.py`.

## Configuration

Config lives at `~/.config/nugget/config.json` (created on first run). Relevant keys:

| Key | Default |
|-----|---------|
| `backend` | `"textgen"` |
| `api_url` | `"http://127.0.0.1:5000"` |
| `model` | `"gemma-4-E4B-it-uncensored-Q4_K_M.gguf"` |
| `temperature` | `0.7` |
| `max_tokens` | `2048` |
| `thinking_effort` | `0` (0=off, 1–3=low/medium/high) |

Full schema in `tool_docs/TOOL_SPEC.md`.
