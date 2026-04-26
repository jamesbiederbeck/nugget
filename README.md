# Nugget

A CLI chat interface for locally-hosted models.

<img src="nugget.png" width="256" />

Why Nugget? Because it's a small, tasty way to interact with your local LLM. It's designed to be simple and intuitive, with a focus on tool use and "thinking" (chain-of-thought reasoning). It's not trying to be a full-featured chat client or knowledge management system — just a quick and easy way to ask questions, run commands, and take notes with your local model.

Also "gem" was already coined by the Gemma team, and "nugget" felt like a fun extension of that.

By default, we use a model from https://huggingface.co/collections/TrevorJS/gemma-4-uncensored. It's running locally, so why should it tell you no? Gemma 4 models in that collection have been [abliterated](https://huggingface.co/blog/mlabonne/abliteration) to remove the "refusal" activation from their vocabulary, making them more cooperative and less likely to refuse requests. You can use any model you like, but these are a good starting point. The `-E4B` variant is a smaller, faster model with good reasoning abilities.

## Requirements

- Python 3.11+
- A running text-generation-webui server (default: `http://127.0.0.1:5000`)

## Installation

```bash
pip install -e .
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

# Verbose (show thinking, tool calls, system prompt)
nugget -v "what time is it"
```

## Tools

| Tool | Description |
|------|-------------|
| `calculator` | Evaluate math expressions |
| `get_datetime` | Get current date/time in any timezone |
| `shell` | Run shell commands (asks for approval) |
| `filebrowser` | Read and list files |
| `memory` | Persist notes across sessions; supports pinning to system prompt |

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

| Key | Default |
|-----|---------|
| `backend` | `"textgen"` |
| `api_url` | `"http://127.0.0.1:5000"` |
| `model` | `"gemma-4-E4B-it-uncensored-Q4_K_M.gguf"` |
| `temperature` | `0.7` |
| `max_tokens` | `2048` |
| `thinking_effort` | `0` (0=off, 1=low, 2=medium, 3=high) |
| `sessions_dir` | `~/.local/share/nugget/sessions` |

## Backends

The `backend` config key (or `--backend` flag) selects which model server to talk to. Currently available:

| Backend | Description |
|---------|-------------|
| `textgen` | text-generation-webui `/v1/completions` with Gemma 4 prompt format (default) |

New backends live in `src/nugget/backends/`. Each one implements the `Backend` protocol: a `run()` method that takes messages, tool schemas, and a tool executor, and returns `(text, thinking, tool_exchanges, finish_reason)`.

## Docker

```bash
docker build -t nugget .
docker run -it --network host nugget

# One-shot
docker run --network host nugget -n "what is 2+2"
```

`--network host` lets the container reach your model server at `127.0.0.1:5000`.

## Approval

Tool calls are governed by approval rules. By default, `shell` prompts before running and `memory` delete operations ask for confirmation; everything else is auto-allowed. Rules can be customized in `config.json`:

```json
"approval": {
  "default": "allow",
  "rules": [
    { "tool": "shell", "action": "ask" },
    { "tool": "memory", "args": { "operation": "delete" }, "action": "ask" }
  ]
}
```

## Project layout

```
src/nugget/
  backends/
    __init__.py       # Backend protocol + make_backend() factory
    textgen.py        # text-generation-webui + Gemma 4 prompt format
  tools/              # Auto-discovered tool modules
  templates/
    system.j2         # System prompt template
  config.py
  session.py
  display.py
  approval.py
```

## Roadmap

See [ROADMAP.md](ROADMAP.md).
