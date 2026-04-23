# Nugget — Tool Specification

> **Repository:** [jamesbiederbeck/nugget](https://github.com/jamesbiederbeck/nugget)  
> **Description:** A CLI chat interface for locally-hosted Gemma 4 models.  
> **Language:** Python 3.11+ · **License:** MIT  
> **Version:** 0.1.0

---

## Table of Contents

1. [Overview](#overview)
2. [Backend API](#backend-api)
3. [Nugget Web Server API](#nugget-web-server-api)
4. [Built-in Tools](#built-in-tools)
   - [calculator](#calculator)
   - [get_datetime](#get_datetime)
   - [shell](#shell)
   - [filebrowser](#filebrowser)
   - [memory](#memory)
5. [Token Limits](#token-limits)
6. [Approval Rules](#approval-rules)
7. [Configuration Schema](#configuration-schema)
8. [Writing a Custom Tool](#writing-a-custom-tool)
9. [Writing a Custom Backend](#writing-a-custom-backend)

---

## Overview

Nugget wraps a locally-hosted LLM (default: Gemma 4 via `text-generation-webui`) with:

- A **CLI** (`nugget`) for interactive or one-shot chat.
- A **web server** (`nugget-server`) with a FastAPI + SSE JSON API.
- A **tool-calling framework** with five built-in tools and a simple approval system.
- **Session persistence** (SQLite/JSON) and **memory** (SQLite) across conversations.

The upstream model server speaks an **OpenAI-compatible HTTP API** on port `5000` by default. Nugget talks to that server, formats prompts using the **Gemma 4 prompt template**, and streams results back to the caller.

---

## Backend API

Nugget proxies to a running [`text-generation-webui`](https://github.com/oobabooga/text-generation-webui) instance (or any OpenAI-compatible server).

### Base URL

```
http://127.0.0.1:5000   (default, configurable via api_url or --api flag)
```

### Authentication

Optional. Pass an API key via the `Authorization` header:

```
Authorization: Bearer <your-api-key>
```

### Key endpoint used

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/completions` | Generate text (Gemma 4 prompt format) |

Nugget formats the full conversation — system prompt, messages, tool declarations, and tool call results — into a single prompt string using the Gemma 4 template, then sends it to `/v1/completions`.

---

## Nugget Web Server API

Start with:

```bash
nugget-server [--host HOST] [--port PORT]
# default: http://127.0.0.1:8000
```

All endpoints return JSON. The chat endpoint returns **Server-Sent Events (SSE)**.

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sessions` | List all saved sessions |
| `POST` | `/api/sessions` | Create a new session |
| `GET` | `/api/sessions/{id}` | Get session details and message history |
| `DELETE` | `/api/sessions/{id}` | Delete a session |

### Chat

```
POST /api/sessions/{id}/chat
Content-Type: application/json

{"message": "your message here"}
```

Returns an SSE stream. Each event is a JSON object on a `data:` line:

| `type` | Fields | Description |
|--------|--------|-------------|
| `token` | `text` | Streamed text token |
| `thinking` | `text` | Chain-of-thought token (when thinking is enabled) |
| `tool_call` | `name`, `args` | Model is calling a tool |
| `tool_result` | `name`, `result` | Tool execution result |
| `tool_denied` | `name`, `reason` | Tool call was blocked by approval policy |
| `done` | `text` | Final complete response text |
| `error` | `message` | An error occurred |

---

## Built-in Tools

All tools live in `src/nugget/tools/` and are **auto-discovered** at startup. Each module exposes a `SCHEMA` dict (OpenAI function-tool format) and an `execute(args)` function.

### calculator

Evaluates safe arithmetic expressions using Python's AST parser. No `eval()` is used.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `expression` | string | ✓ | Arithmetic expression, e.g. `"2 + 2"` or `"(10 * 3) / 4"` |

**Returns:** `{"result": <number>, "expression": <string>}` or `{"error": ..., "expression": ...}`

**Approval:** `allow` (auto-approved)

---

### get_datetime

Returns the current date and time in any IANA timezone.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `timezone` | string | — | IANA timezone string, e.g. `"UTC"`, `"America/New_York"`. Defaults to `"UTC"`. |

**Returns:**

```json
{
  "datetime": "2025-01-15T14:30:00+00:00",
  "date": "2025-01-15",
  "time": "14:30:00",
  "timezone": "UTC",
  "weekday": "Wednesday"
}
```

**Approval:** `allow` (auto-approved)

---

### shell

Runs an arbitrary shell command and returns its output. Use with caution.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `command` | string | ✓ | Shell command to execute |
| `timeout` | number | — | Timeout in seconds (default: `10`) |

**Returns:** `{"stdout": ..., "stderr": ..., "returncode": ...}` or `{"error": ...}`

**Approval:** `ask` (prompts user before executing)

---

### filebrowser

Browses the local filesystem. Supports three operations.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `operation` | string | ✓ | One of: `"cwd"`, `"ls"`, `"cat"` |
| `path` | string | — | Directory path for `ls`, file path for `cat`. Omit for `cwd`. |

**Operations:**

- `cwd` — Returns `{"cwd": "/current/working/directory"}`
- `ls` — Returns `{"path": ..., "entries": [{"name", "type", "size"}, ...]}`
- `cat` — Returns `{"path": ..., "content": ..., "size": ...}`

**Approval:** `allow` (auto-approved)

---

### memory

Persistent key-value memory backed by SQLite at `~/.local/share/nugget/memory.db`. Memories survive across sessions. Supports `memory://` URIs to link related entries.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `operation` | string | ✓ | One of: `"store"`, `"recall"`, `"search"`, `"list"`, `"delete"` |
| `key` | string | — | Memory key (required for `store`, `recall`, `delete`) |
| `value` | string | — | Value to store (required for `store`). May include `memory://key` URIs. |
| `query` | string | — | Substring to search for (required for `search`) |
| `pin` | boolean | — | If `true`, inject this memory into every system prompt |

**Operations summary:**

| Operation | Description |
|-----------|-------------|
| `store` | Save or update a key-value pair |
| `recall` | Retrieve a value by key (falls back to fuzzy match) |
| `search` | Find memories whose key or value contains the query |
| `list` | Return all stored keys, sorted by pinned-first then recency |
| `delete` | Remove a key |

**Approval:** `allow` for most operations; `ask` for `delete`

---

## Token Limits

Token limits are controlled by the `max_tokens` configuration key (default: `2048`). This is passed directly to the upstream model server as the `max_tokens` parameter in the `/v1/completions` request.

When `thinking_effort` is enabled, nugget allocates a portion of the token budget to chain-of-thought reasoning:

| `thinking_effort` | Budget tokens |
|-------------------|---------------|
| `0` (off) | — |
| `1` (low) | 1024 |
| `2` (medium) | 4096 |
| `3` (high) | 8192 |

---

## Approval Rules

Tool calls are governed by a two-level approval system.

**Resolution order (first match wins):**

1. Config rules (ordered list in `config.json`)
2. Tool module's own `APPROVAL` attribute
3. Config `default`

**Actions:**

| Action | Behaviour |
|--------|-----------|
| `allow` | Execute immediately |
| `deny` | Block the tool call |
| `ask` | Prompt the user interactively; deny automatically in non-TTY contexts |

**Default config:**

```json
"approval": {
  "default": "allow",
  "rules": [
    { "tool": "shell",  "action": "ask" },
    { "tool": "memory", "args": { "operation": "delete" }, "action": "ask" }
  ]
}
```

**Rule fields:**

| Field | Description |
|-------|-------------|
| `tool` | Tool name to match (or `"*"` for all tools) |
| `args` | Optional map of argument key-value pairs that must all match |
| `action` | `"allow"`, `"deny"`, or `"ask"` |

**Tool-level gate:** A tool module may set `APPROVAL = "ask"` (string) or define `APPROVAL` as a callable that receives the `args` dict and returns an action string.

---

## Configuration Schema

Config file: `~/.config/nugget/config.json` (created automatically on first run).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `"textgen"` | Backend to use |
| `api_url` | string | `"http://127.0.0.1:5000"` | Upstream model server URL |
| `model` | string | `"gemma-4-E4B-it-uncensored-Q4_K_M.gguf"` | Model filename |
| `temperature` | number | `0.7` | Sampling temperature |
| `max_tokens` | integer | `2048` | Maximum tokens to generate |
| `top_p` | number | `0.95` | Top-p sampling |
| `top_k` | integer | `20` | Top-k sampling |
| `thinking_effort` | integer | `0` | Chain-of-thought effort: 0=off, 1=low, 2=medium, 3=high |
| `show_thinking` | boolean | `false` | Print thinking tokens to terminal |
| `show_tool_calls` | boolean | `true` | Print tool call/response events |
| `show_tool_responses` | boolean | `false` | Print full tool response payloads |
| `show_system_prompt` | boolean | `false` | Print the system prompt at session start |
| `system_prompt` | string | `"You are a helpful assistant."` | Base system prompt |
| `append_datetime` | boolean | `true` | Append current UTC datetime to system prompt |
| `sessions_dir` | string | `~/.local/share/nugget/sessions` | Where sessions are stored |
| `debug` | boolean | `false` | Enable debug output |
| `approval` | object | see above | Approval policy (see [Approval Rules](#approval-rules)) |

---

## Writing a Custom Tool

Tools are **auto-discovered**: any `.py` file in `src/nugget/tools/` that exposes `SCHEMA` and `execute` is automatically registered at startup.

### Quickstart (from template)

1. Copy `tool_docs/_bash_tool_template.py` to `src/nugget/tools/your_tool.py`.
2. Fill in the `── CONFIGURE ──` section (tool name, description, command, args).
3. Restart nugget — the tool is live.

See `tool_docs/ping_host.py` for a fully worked example.

### Manual approach

```python
# src/nugget/tools/my_tool.py

APPROVAL = "allow"   # optional: "allow" | "deny" | "ask" | callable

SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Does something useful.",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "The input value",
                },
            },
            "required": ["input"],
        },
    },
}


def execute(args: dict) -> dict:
    value = args.get("input", "")
    # ... do work ...
    return {"result": value.upper()}
```

### Tool module contract

| Attribute | Required | Description |
|-----------|----------|-------------|
| `SCHEMA` | ✓ | OpenAI function-tool schema dict |
| `execute(args: dict) -> object` | ✓ | Called with the model's argument dict; return any JSON-serialisable value |
| `APPROVAL` | — | String (`"allow"`, `"deny"`, `"ask"`) or `callable(args) -> str` |

---

## Writing a Custom Backend

Backends live in `src/nugget/backends/` and implement the `Backend` protocol defined in `src/nugget/backends/__init__.py`.

### Protocol

```python
class Backend(Protocol):
    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        **kwargs,
    ) -> tuple[str, str | None, list[dict]]: ...
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `messages` | `list[dict]` | Conversation history (OpenAI message format) |
| `tool_schemas` | `list[dict]` | List of active tool schemas |
| `tool_executor` | `Callable[[str, dict], object]` | Call this to execute a tool: `tool_executor(tool_name, args)` |
| `system_prompt` | `str` | Fully rendered system prompt string |
| `**kwargs` | — | Optional: `thinking_effort`, `on_token`, `on_thinking`, `on_tool_call`, `on_tool_response`, `on_tool_denied` callbacks |

**Return value:** `(response_text, thinking_text_or_None, tool_exchanges_list)`

### Registering the backend

Add a branch to `make_backend()` in `src/nugget/backends/__init__.py`:

```python
def make_backend(config) -> Backend:
    name = config.get("backend", "textgen")
    if name == "textgen":
        from .textgen import TextgenBackend
        return TextgenBackend(config)
    if name == "my_backend":
        from .my_backend import MyBackend
        return MyBackend(config)
    raise ValueError(f"unknown backend: {name!r}")
```

Then set `"backend": "my_backend"` in `~/.config/nugget/config.json` or pass `--backend my_backend` on the CLI.
