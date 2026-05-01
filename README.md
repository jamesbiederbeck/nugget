# Nugget

A CLI chat interface for locally-hosted models.

<img src="nugget.png" width="256" />

Why Nugget? Because it's a small, tasty way to interact with your local LLM. It's designed to be simple and intuitive, with a focus on tool use and "thinking" (chain-of-thought reasoning). It's not trying to be a full-featured chat client or knowledge management system — just a quick and easy way to ask questions, run commands, and take notes with your local model.

Also "gem" was already coined by the Gemma team, and "nugget" felt like a fun extension of that.

By default, we use a model from https://huggingface.co/collections/TrevorJS/gemma-4-uncensored. It's running locally, so why should it tell you no? Gemma 4 models in that collection have been [abliterated](https://huggingface.co/blog/mlabonne/abliteration) to remove the "refusal" activation from their vocabulary, making them more cooperative and less likely to refuse requests. You can use any model you like, but these are a good starting point. The `-E4B` variant is a smaller, faster model with good reasoning abilities.

## Status

| Branch | Tests |
|--------|-------|
| `main` | [![release](https://github.com/jamesbiederbeck/nugget/actions/workflows/release.yml/badge.svg)](https://github.com/jamesbiederbeck/nugget/actions/workflows/release.yml) |
| `staging` | [![tests](https://github.com/jamesbiederbeck/nugget/actions/workflows/test.yml/badge.svg?branch=staging)](https://github.com/jamesbiederbeck/nugget/actions/workflows/test.yml) |
| `develop` | [![tests](https://github.com/jamesbiederbeck/nugget/actions/workflows/test.yml/badge.svg?branch=develop)](https://github.com/jamesbiederbeck/nugget/actions/workflows/test.yml) |

## Requirements

- Python 3.11+
- A running text-generation-webui server (default: `http://127.0.0.1:5000`)

## Installation

```bash
# Development install (CLI only)
uv pip install -e .

# With web server support
uv pip install -e ".[web]"

# Install as a persistent tool (recommended for daily use)
uv tool install ".[web]" --force
```

## Usage

```bash
# Interactive session
nugget

# One-shot
nugget "what is the capital of france"

# One-shot, no interactive follow-up
nugget -n "summarize this" < file.txt

# Resume a session by ID
nugget --session abc12345

# Resume the most recent session
nugget --session last

# List saved sessions
nugget --list-sessions

# Enable thinking
nugget --thinking "explain backpropagation"
nugget --thinking-effort 3 "hard problem"

# Override model (openrouter backend)
nugget --model "anthropic/claude-3.5-sonnet"

# Verbose (show thinking, tool calls, system prompt)
nugget -v "what time is it"
```

## Tools

| Tool | Description | Approval |
|------|-------------|----------|
| `calculator` | Evaluate math expressions | allow |
| `get_datetime` | Get current date/time in any timezone | allow |
| `shell` | Run shell commands | ask |
| `filebrowser` | Browse, read, write, edit, and manage local files | read=allow, write=ask |
| `grep_search` | Search files with ripgrep | allow |
| `http_fetch` | Fetch URLs (GET/HEAD/POST/PUT/DELETE) | GET/HEAD=allow, mutating=ask |
| `jq` | Apply JMESPath queries to JSON or `$var` bindings | allow |
| `tasks` | SQLite-backed task list (add, list, complete, delete) | delete=ask, others=allow |
| `memory` | Persist notes across sessions; supports pinning to system prompt | delete=ask, others=allow |
| `wallabag` | Manage a Wallabag reading list (save, search, retrieve articles) | allow |
| `notify` | Send push notifications via Gotify | allow |
| `render_output` | Call any tool and route its result to display, file, or a variable | allow |

```bash
# Filter tools
nugget --include-tools calculator,get_datetime
nugget --exclude-tools shell
nugget --list-tools
```

### Pinned memories

The `memory` tool supports a `pin` field. Pinned memories are automatically injected into the system prompt at the start of every session, so the model always has them in context:

```
store key="my name" value="Victor" pin=true
```

## Configuration

Config lives at `~/.config/nugget/config.json`. Created automatically on first run.

See [`tool_docs/CONFIG.md`](tool_docs/CONFIG.md) for annotated examples and the full key reference.

## Backends

The `backend` config key (or `--backend` flag) selects which model server to talk to. Currently available:

| Backend | Description |
|---------|-------------|
| `textgen` | text-generation-webui `/v1/completions` with Gemma 4 prompt format (default) |
| `openrouter` | [OpenRouter](https://openrouter.ai) OpenAI-compatible API with native tool calling. Set `openrouter_api_key` in `config.json` or `OPENROUTER_API_KEY` env var. Use `openrouter_model` (or `--model`) to choose the model. |

```bash
# Run server with a specific backend and model
nugget-server --backend openrouter --model anthropic/claude-3.5-sonnet
```

New backends live in `src/nugget/backends/`. Each one subclasses the `Backend` ABC and implements a `run()` method that takes messages, tool schemas, and a tool executor, and returns `(text, thinking, tool_exchanges, finish_reason)`.

## Docker

```bash
docker build -t nugget .
docker run -it --network host nugget

# One-shot
docker run --network host nugget -n "what is 2+2"
```

`--network host` lets the container reach your model server at `127.0.0.1:5000`.

## Approval

Tool calls are governed by approval rules. The default policy: `shell` always asks; `filebrowser` write/edit ops ask; `http_fetch` mutating methods (POST/PUT/DELETE) ask; `memory` and `tasks` delete ops ask; everything else is auto-allowed.

Override rules in `config.json`:

```json
"approval": {
  "default": "allow",
  "rules": [
    { "tool": "shell", "action": "deny" },
    { "tool": "http_fetch", "args": { "method": "GET" }, "action": "allow" },
    { "tool": "http_fetch", "action": "ask" }
  ]
}
```

See [`tool_docs/CONFIG.md`](tool_docs/CONFIG.md) for the full approval and file-sink rule reference.

## Project layout

```
src/nugget/
  backends/
    __init__.py       # Backend ABC + make_backend() factory
    textgen.py        # text-generation-webui + Gemma 4 prompt format
    openrouter.py     # OpenRouter OpenAI-compatible backend
  tools/              # Auto-discovered tool modules
  templates/
    system.j2         # System prompt template
  config.py
  session.py
  display.py
  approval.py
tool_docs/
  TOOL_SPEC.md        # Full API + tool schema reference
  CONFIG.md           # Config key reference with examples
  SUBAGENT_SPEC.md    # Subagent framework spec (v0.4)
```

## Roadmap

See [ROADMAP.md](ROADMAP.md).
