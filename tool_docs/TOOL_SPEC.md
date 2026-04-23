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

### Key Upstream Endpoints Used by Nugget

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/v1/completions` | Text completion (used by the `textgen` backend) |
| `POST` | `/v1/chat/completions` | Chat completion (OpenAI-compatible) |
| `POST` | `/v1/internal/model/load` | Load a model at runtime |
| `GET`  | `/v1/internal/model/list` | List available models |
| `GET`  | `/v1/models` | List currently loaded models |
| `POST` | `/v1/embeddings` | Sentence embeddings (requires `sentence-transformers`) |
| `POST` | `/v1/images/generations` | Image generation (requires an image model) |

### Completions — Input Shape

```json
{
  "prompt": "string",
  "max_tokens": 2048,
  "temperature": 0.7,
  "top_p": 0.95,
  "top_k": 20,
  "stream": false
}
```

### Chat Completions — Input Shape

```json
{
  "messages": [
    { "role": "system",    "content": "string" },
    { "role": "user",      "content": "string" },
    { "role": "assistant", "content": "string" }
  ],
  "temperature": 0.7,
  "top_p": 0.95,
  "top_k": 20,
  "max_tokens": 2048,
  "stream": false,
  "tools": [ /* optional — see Tool Calling below */ ]
}
```

Multimodal content parts are supported:

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "Describe this image." },
    { "type": "image_url", "image_url": { "url": "https://..." } }
  ]
}
```

### Chat Completions — Output Shape

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1764791227,
  "model": "...",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "string",
        "tool_calls": [
          {
            "id": "call_...",
            "type": "function",
            "function": {
              "name": "tool_name",
              "arguments": "{\"key\": \"value\"}"
            }
          }
        ]
      },
      "finish_reason": "stop | tool_calls | length"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

### SSE Streaming

Add `"stream": true` to any request. Each chunk is a `data:` line in [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) format:

```
data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}

data: [DONE]
```

---

## Nugget Web Server API

Start with:

```bash
nugget-server [--host 127.0.0.1] [--port 8000]
# or via extras:
uv pip install -e ".[web]"
```

Base URL: `http://127.0.0.1:8000`

### Session Endpoints

| Method   | Endpoint                            | Description                      |
|----------|-------------------------------------|----------------------------------|
| `GET`    | `/api/sessions`                     | List all saved sessions          |
| `POST`   | `/api/sessions`                     | Create a new session             |
| `GET`    | `/api/sessions/{session_id}`        | Get session details + history    |
| `DELETE` | `/api/sessions/{session_id}`        | Delete a session                 |
| `POST`   | `/api/sessions/{session_id}/chat`   | Send a message (SSE stream)      |

### `GET /api/sessions` — Output Shape

```json
[
  {
    "id": "abc12345",
    "created_at": "2026-04-23T08:00:00Z",
    "updated_at": "2026-04-23T08:01:00Z"
  }
]
```

### `POST /api/sessions` — Output Shape

```json
{ "id": "abc12345" }
```

### `GET /api/sessions/{session_id}` — Output Shape

```json
{
  "id": "abc12345",
  "created_at": "2026-04-23T08:00:00Z",
  "updated_at": "2026-04-23T08:01:00Z",
  "messages": [
    { "role": "user",      "content": "Hello!" },
    { "role": "assistant", "content": "Hi there!" }
  ]
}
```

### `POST /api/sessions/{session_id}/chat` — Input Shape

```json
{ "message": "string" }
```

### `POST /api/sessions/{session_id}/chat` — SSE Output Events

Each line is `data: <JSON>\n\n`. Event types:

| `type`          | Additional fields                              | Description                              |
|-----------------|------------------------------------------------|------------------------------------------|
| `token`         | `text: string`                                 | A streamed text token from the model     |
| `thinking`      | `text: string`                                 | Internal chain-of-thought text           |
| `tool_call`     | `name: string`, `args: object`                 | Model is requesting a tool call          |
| `tool_result`   | `name: string`, `result: object`               | Tool executed successfully               |
| `tool_denied`   | `name: string`, `reason: string`               | Tool call blocked by approval policy     |
| `done`          | `text: string`                                 | Final assembled response text            |
| `error`         | `message: string`                              | Fatal error during generation            |

**Example stream:**

```
data: {"type": "thinking", "text": "The user wants to know..."}

data: {"type": "tool_call", "name": "get_datetime", "args": {"timezone": "UTC"}}

data: {"type": "tool_result", "name": "get_datetime", "result": {"datetime": "2026-04-23T08:00:00+00:00", ...}}

data: {"type": "token", "text": "The current time is "}

data: {"type": "token", "text": "08:00 UTC."}

data: {"type": "done", "text": "The current time is 08:00 UTC."}
```

---

## Built-in Tools

All tools are auto-discovered from `src/nugget/tools/`. Each module exposes a `SCHEMA` dict (OpenAI function-calling format) and an `execute(args: dict) -> dict` function. An optional `APPROVAL` attribute (string or callable) governs the default approval gate.

---

### `calculator`

Evaluate safe arithmetic expressions without `eval`.

**JSON Schema:**

```json
{
  "type": "function",
  "function": {
    "name": "calculator",
    "description": "Evaluate a safe arithmetic expression",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Arithmetic expression to evaluate, e.g. '2 + 2' or '(10 * 3) / 4'"
        }
      },
      "required": ["expression"]
    }
  }
}
```

**Input:**

```json
{ "expression": "(10 * 3) / 4" }
```

**Output (success):**

```json
{ "result": 7.5, "expression": "(10 * 3) / 4" }
```

**Output (error):**

```json
{ "error": "unsupported node: Call", "expression": "os.system('ls')" }
```

**Supported operators:** `+`, `-`, `*`, `/`, `**`, `%`, `//`, unary `-`/`+`  
**Approval gate:** `allow` (no confirmation required)

---

### `get_datetime`

Return the current date and time in any IANA timezone.

**JSON Schema:**

```json
{
  "type": "function",
  "function": {
    "name": "get_datetime",
    "description": "Get the current date and time, optionally in a specific timezone",
    "parameters": {
      "type": "object",
      "properties": {
        "timezone": {
          "type": "string",
          "description": "IANA timezone string, e.g. 'UTC', 'America/New_York', 'Europe/London'. Defaults to UTC."
        }
      },
      "required": []
    }
  }
}
```

**Input:**

```json
{ "timezone": "America/New_York" }
```

**Output (success):**

```json
{
  "datetime": "2026-04-23T04:00:00-04:00",
  "date": "2026-04-23",
  "time": "04:00:00",
  "timezone": "America/New_York",
  "weekday": "Thursday"
}
```

**Output (error):**

```json
{ "error": "unknown timezone: 'Fake/Zone'" }
```

**Approval gate:** `allow`

---

### `shell`

Run an arbitrary shell command and return its output. **High-risk tool.**

**JSON Schema:**

```json
{
  "type": "function",
  "function": {
    "name": "shell",
    "description": "Run a shell command and return its output. Use with caution.",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "description": "Shell command to execute"
        },
        "timeout": {
          "type": "number",
          "description": "Timeout in seconds (default 10)"
        }
      },
      "required": ["command"]
    }
  }
}
```

**Input:**

```json
{ "command": "ls -la /tmp", "timeout": 5 }
```

**Output (success):**

```json
{
  "stdout": "total 0\ndrwxrwxrwt ...",
  "stderr": "",
  "returncode": 0
}
```

**Output (timeout):**

```json
{ "error": "command timed out after 5s" }
```

**Output (denied):**

```json
{ "_denied": true, "reason": "tool 'shell' requires approval (non-interactive: denied)" }
```

**Approval gate:** `ask` (always prompts in CLI; converts to `allow` in web mode where there is no TTY)

---

### `filebrowser`

Browse and read the local filesystem.

**JSON Schema:**

```json
{
  "type": "function",
  "function": {
    "name": "filebrowser",
    "description": "Browse the local filesystem. Operations: 'cwd' returns the current working directory; 'ls' lists files in a directory; 'cat' reads the contents of a file.",
    "parameters": {
      "type": "object",
      "properties": {
        "operation": {
          "type": "string",
          "description": "One of: 'cwd', 'ls', 'cat'"
        },
        "path": {
          "type": "string",
          "description": "Path for 'ls' (directory) or 'cat' (file). Omit for 'cwd'."
        }
      },
      "required": ["operation"]
    }
  }
}
```

**`cwd` — Input / Output:**

```json
// Input
{ "operation": "cwd" }

// Output
{ "cwd": "/home/user/projects" }
```

**`ls` — Input / Output:**

```json
// Input
{ "operation": "ls", "path": "/home/user" }

// Output
{
  "path": "/home/user",
  "entries": [
    { "name": "Documents", "type": "dir",  "size": 4096 },
    { "name": "notes.txt", "type": "file", "size": 1234 }
  ]
}
```

**`cat` — Input / Output:**

```json
// Input
{ "operation": "cat", "path": "/home/user/notes.txt" }

// Output
{ "path": "/home/user/notes.txt", "content": "Hello world\n", "size": 12 }
```

**Approval gate:** `allow`

---

### `memory`

Persistent key-value store backed by SQLite at `~/.local/share/nugget/memory.db`. Supports pinning memories into the system prompt.

**JSON Schema:**

```json
{
  "type": "function",
  "function": {
    "name": "memory",
    "description": "Persistent key-value memory across conversations. Operations: 'store', 'recall', 'search', 'list', 'delete'.",
    "parameters": {
      "type": "object",
      "properties": {
        "operation": {
          "type": "string",
          "description": "One of: 'store', 'recall', 'search', 'list', 'delete'"
        },
        "key": {
          "type": "string",
          "description": "Memory key (required for store, recall, delete)"
        },
        "value": {
          "type": "string",
          "description": "Value to store (required for store). May include memory:// URIs to link related keys."
        },
        "query": {
          "type": "string",
          "description": "Substring to search for (required for search)"
        },
        "pin": {
          "type": "boolean",
          "description": "If true, mark this memory as pinned into the system prompt. If false, unpin. Omit to leave unchanged."
        }
      },
      "required": ["operation"]
    }
  }
}
```

**Operations and examples:**

| Operation | Required fields | Optional fields |
|-----------|----------------|-----------------|
| `store`   | `key`, `value`  | `pin`           |
| `recall`  | `key`           | —               |
| `search`  | `query`         | —               |
| `list`    | —               | —               |
| `delete`  | `key`           | —               |

**`store` output:**

```json
{ "stored": "my-name", "pinned": true }
```

**`recall` output (found):**

```json
{
  "key": "my-name",
  "value": "Victor",
  "updated_at": "2026-04-23T08:00:00+00:00",
  "pinned": true,
  "links": []
}
```

**`search` output:**

```json
{
  "query": "Victor",
  "results": [
    { "key": "my-name", "value": "Victor", "updated_at": "...", "pinned": true }
  ]
}
```

**`list` output:**

```json
{
  "keys": [
    { "key": "my-name", "updated_at": "...", "pinned": true },
    { "key": "project",  "updated_at": "...", "pinned": false }
  ]
}
```

**`delete` output:**

```json
{ "deleted": "my-name" }
```

**Memory links:** Values may contain `memory://key` URIs. When recalling, linked memories are auto-fetched and returned in a `links` array.

**Approval gate:** Dynamic — `ask` when `operation == "delete"`, otherwise `allow`.

---

## Token Limits

Token limits are governed by the loaded model and the `ctx_size` passed to the backend server.

| Setting           | Default  | Notes                                                          |
|-------------------|----------|----------------------------------------------------------------|
| `max_tokens`      | `2048`   | Configurable in `~/.config/nugget/config.json` or `--max-tokens` |
| Context window    | Model-dependent | Gemma 4 E4B: up to **128K** tokens (set `ctx_size` when loading) |
| Thinking tokens   | Varies   | `--thinking-effort` `1`/`2`/`3` adds chain-of-thought overhead; LOW effort ~20% fewer thinking tokens |

**Embedding model token limits** (when using `/v1/embeddings`):

| Model                     | Dimensions | Max Input Tokens |
|---------------------------|------------|-----------------|
| `all-mpnet-base-v2`       | 768        | 384             |
| `all-MiniLM-L6-v2`        | 384        | 256             |

> ⚠️ You cannot mix embeddings from different models, even if their dimensions match.

---

## Approval Rules

Tool calls go through a three-step resolution. **First match wins.**

```
1. Config rules   (ordered list in config.json)
2. Tool's APPROVAL gate (static string or callable)
3. Config default
```

**Actions:**

| Action  | Behavior                                                                 |
|---------|--------------------------------------------------------------------------|
| `allow` | Execute immediately, no prompt                                           |
| `deny`  | Block unconditionally                                                    |
| `ask`   | Prompt the user (CLI only). In non-interactive / web mode: auto-deny     |

**Config shape** (`~/.config/nugget/config.json`):

```json
{
  "approval": {
    "default": "allow",
    "rules": [
      { "tool": "shell",  "action": "ask" },
      { "tool": "memory", "args": { "operation": "delete" }, "action": "ask" },
      { "tool": "filebrowser", "args": { "operation": "cat" }, "action": "allow" }
    ]
  }
}
```

**Rule fields:**

| Field    | Type   | Description                                                          |
|----------|--------|----------------------------------------------------------------------|
| `tool`   | string | Tool name to match. Use `"*"` or omit for wildcard.                  |
| `args`   | object | Key-value pairs that must all match the call's args (subset match).  |
| `action` | string | `"allow"`, `"deny"`, or `"ask"`                                      |

**Tool gate in a module:**

```python
# Static gate
APPROVAL = "ask"    # always ask
APPROVAL = "deny"   # always deny

# Dynamic gate (callable)
def APPROVAL(args: dict) -> str:
    return "ask" if args.get("operation") == "delete" else "allow"
```

---

## Configuration Schema

Full JSON Schema for `~/.config/nugget/config.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "backend": {
      "type": "string",
      "default": "textgen",
      "description": "Backend identifier. Currently only 'textgen' is available."
    },
    "api_url": {
      "type": "string",
      "format": "uri",
      "default": "http://127.0.0.1:5000",
      "description": "Base URL of the upstream model server."
    },
    "model": {
      "type": "string",
      "default": "gemma-4-E4B-it-uncensored-Q4_K_M.gguf",
      "description": "Model filename to request from the backend."
    },
    "temperature": {
      "type": "number",
      "minimum": 0,
      "maximum": 2,
      "default": 0.7
    },
    "max_tokens": {
      "type": "integer",
      "minimum": 1,
      "default": 2048
    },
    "thinking_effort": {
      "type": "integer",
      "enum": [0, 1, 2, 3],
      "default": 0,
      "description": "0=off, 1=low, 2=medium, 3=high chain-of-thought effort."
    },
    "sessions_dir": {
      "type": "string",
      "default": "~/.local/share/nugget/sessions",
      "description": "Directory where session JSON files are saved."
    },
    "approval": {
      "type": "object",
      "properties": {
        "default": {
          "type": "string",
          "enum": ["allow", "deny", "ask"],
          "default": "allow"
        },
        "rules": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "tool":   { "type": "string" },
              "args":   { "type": "object" },
              "action": { "type": "string", "enum": ["allow", "deny", "ask"] }
            },
            "required": ["action"]
          }
        }
      }
    }
  }
}
```

---

## Writing a Custom Tool

Place a new file in `src/nugget/tools/`. It is auto-discovered on startup.

**Minimal template:**

```python
# src/nugget/tools/my_tool.py

# Optional: static or dynamic approval gate
APPROVAL = "allow"          # or "ask" / "deny"
# def APPROVAL(args: dict) -> str: ...

SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What this tool does.",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "Description of param1."
                }
            },
            "required": ["param1"],
        },
    },
}


def execute(args: dict) -> dict:
    """Return a JSON-serialisable dict."""
    value = args.get("param1", "")
    return {"result": value.upper()}
```

**Conventions:**

- Always return a `dict`. On error, include an `"error"` key.
- Never raise exceptions; catch them and return `{"error": str(e)}`.
- The `SCHEMA` name must be unique across all loaded tools.
- Use `APPROVAL = "ask"` for any tool that modifies system state.

---

## Writing a Custom Backend

Backends live in `src/nugget/backends/` and must implement the `Backend` protocol:

```python
from nugget.backends import Backend

class MyBackend:
    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: callable,
        system_prompt: str,
        thinking_effort: int = 0,
        on_token: callable = None,
        on_thinking: callable = None,
        on_tool_call: callable = None,
        on_tool_response: callable = None,
        on_tool_denied: callable = None,
    ) -> tuple[str, str, list]:
        """
        Returns:
          text           — final assistant text
          thinking       — raw chain-of-thought string (empty if disabled)
          exchanges      — list of tool call/response dicts for session history
        """
        ...
```

Register it in `src/nugget/backends/__init__.py` inside `make_backend()`.
