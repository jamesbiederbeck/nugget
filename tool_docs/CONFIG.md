# Nugget — Configuration Reference

Config file: `~/.config/nugget/config.json`  
Created automatically on first run with defaults.

For the machine-readable JSON Schema see `TOOL_SPEC.md § Configuration Schema`.

---

## All keys

| Key | Default | Description |
|-----|---------|-------------|
| `backend` | `"textgen"` | `"textgen"` or `"openrouter"` |
| `api_url` | `"http://127.0.0.1:5000"` | Base URL of the upstream model server (textgen backend) |
| `model` | `"gemma-4-E4B-it-uncensored-Q4_K_M.gguf"` | Model filename (textgen) or model ID (openrouter) |
| `temperature` | `0.7` | Sampling temperature |
| `top_p` | `0.95` | Nucleus sampling cutoff |
| `top_k` | `20` | Top-K sampling |
| `max_tokens` | `2048` | Max tokens to generate per turn |
| `thinking_effort` | `0` | Chain-of-thought: 0=off, 1=low, 2=medium, 3=high |
| `show_thinking` | `false` | Print thinking blocks to the terminal |
| `show_tool_calls` | `true` | Print tool call/response summaries |
| `show_tool_responses` | `false` | Print full tool response JSON |
| `show_system_prompt` | `false` | Print the assembled system prompt at start of session |
| `system_prompt` | `"You are a helpful assistant."` | Base system prompt (pinned memories are appended) |
| `append_datetime` | `true` | Append current date/time to the system prompt |
| `sessions_dir` | `~/.local/share/nugget/sessions` | Where session JSON files are saved |
| `debug` | `false` | Enable debug logging |
| `openrouter_api_key` | `""` | OpenRouter API key (or set `OPENROUTER_API_KEY` env var) |
| `openrouter_model` | `"openai/gpt-4o-mini"` | Default model for the openrouter backend |
| `approval` | *(see below)* | Tool-call approval policy |

---

## Common configurations

### Minimal local setup (textgen default)

```json
{
  "backend": "textgen",
  "api_url": "http://127.0.0.1:5000",
  "model": "gemma-4-E4B-it-uncensored-Q4_K_M.gguf",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

### OpenRouter

```json
{
  "backend": "openrouter",
  "openrouter_api_key": "sk-or-...",
  "openrouter_model": "anthropic/claude-3.5-sonnet",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

`openrouter_api_key` can also be set via the `OPENROUTER_API_KEY` environment variable.  
Override the model per-session with `nugget --model anthropic/claude-opus-4` or `nugget-server --model ...`.

### Thinking enabled by default

```json
{
  "thinking_effort": 2,
  "show_thinking": true,
  "max_tokens": 8192
}
```

### Quiet output (tool calls hidden)

```json
{
  "show_tool_calls": false,
  "show_tool_responses": false
}
```

---

## Approval

Controls whether tool calls are executed automatically, denied, or require confirmation.

```json
{
  "approval": {
    "default": "allow",
    "rules": [
      { "tool": "shell",        "action": "ask"   },
      { "tool": "memory",       "args": { "operation": "delete" }, "action": "ask" },
      { "tool": "tasks",        "args": { "operation": "delete" }, "action": "ask" },
      { "tool": "filebrowser",  "args": { "operation": "write"  }, "action": "ask" },
      { "tool": "http_fetch",   "args": { "method": "GET"       }, "action": "allow" },
      { "tool": "http_fetch",   "action": "ask" }
    ]
  }
}
```

Rules are evaluated in order; first match wins. Then the tool's built-in `APPROVAL` gate is checked; then `default`.

**Actions:** `"allow"` — run immediately · `"deny"` — block · `"ask"` — prompt in CLI (auto-deny in web mode)

**Rule fields:**

| Field | Description |
|-------|-------------|
| `tool` | Tool name to match. Omit for wildcard. |
| `args` | Subset of call args that must all match. |
| `action` | `"allow"`, `"deny"`, or `"ask"` |

### Built-in approval gates (defaults before config rules)

| Tool | Default gate |
|------|-------------|
| `shell` | `ask` |
| `filebrowser` | read ops: `allow` · write/edit/delete ops: `ask` |
| `http_fetch` | GET/HEAD: `allow` · POST/PUT/DELETE/PATCH: `ask` |
| `tasks` | delete: `ask` · all others: `allow` |
| `memory` | delete: `ask` · all others: `allow` |
| all others | `allow` |

### Deny shell entirely

```json
{
  "approval": {
    "default": "allow",
    "rules": [
      { "tool": "shell", "action": "deny" }
    ]
  }
}
```

---

## File-sink rules

When a tool call uses `output: "file:<path>"`, a separate path-based policy decides whether the write is allowed. Independent of the tool-call rules above.

**Default policy** (used when `sink_rules` is absent):

- `/tmp/nugget/**` → allow
- `$CWD/**` → allow
- Any path that already exists → ask
- Everything else → ask

**Custom example — lock writes to a project tree:**

```json
{
  "approval": {
    "sink_rules": [
      { "subtree": "$CWD",    "action": "allow" },
      { "subtree": "/tmp",    "action": "allow" },
      { "subtree": "/etc",    "action": "deny"  },
      { "existing": true,     "action": "ask"   }
    ],
    "sink_conflict": "strictest"
  }
}
```

**Rule match keys** (one per rule):

| Key | Matches when… |
|-----|--------------|
| `subtree` | Path is equal to or under this prefix. `"$CWD"` expands at evaluation time. |
| `exact` | Path equals this value (after canonicalisation). |
| `existing` | `path.exists()` equals the given boolean. |
| `any: true` | Always. Use as a catch-all. |

**`sink_conflict`** — when multiple rules match the same path:

| Value | Behavior |
|-------|----------|
| `"strictest"` (default) | Most restrictive action wins: `deny` > `ask` > `allow` |
| `"first"` | First matching rule's action wins |
