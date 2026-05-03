# Config Profiles — Design Notes

A feature to let users define named configuration overlays in `config.json` and activate one with a single CLI flag.

## Goals

- Switch between named working modes (`pure-chat`, `code-agent`, etc.) without editing `config.json`
- Any profile can be used for subagents — either explicitly via `spawn_agent`'s `profile` arg, or via a default declared in the `subagent` config block
- No new files, no registration — all profiles live in `config.json`

---

## CLI

```bash
nugget --profile code-agent "refactor this function"
nugget-server --profile pure-chat
```

Unknown profile names are a hard error. Available profile names are listed in the error message.

---

## Config shape

```json
{
  "backend": "openrouter",
  "openrouter_api_key": "sk-or-...",
  "openrouter_model": "anthropic/claude-3.5-sonnet",
  "temperature": 0.7,
  "max_tokens": 4096,
  "system_prompt": "You are a helpful assistant.",
  "append_datetime": true,
  "thinking_effort": 0,
  "show_tool_calls": true,
  "subagent": {
    "max_depth": 2,
    "max_turns_default": 4,
    "default_profile": "lean"
  },
  "approval": {
    "default": "allow",
    "rules": [
      { "tool": "shell", "action": "ask" }
    ]
  },
  "profiles": {
    "pure-chat": {
      "include_tools": [],
      "thinking_effort": 0,
      "system_prompt": "You are a concise assistant. No code, no tools.",
      "subagent": {
        "max_depth": 0
      }
    },
    "code-agent": {
      "temperature": 0.2,
      "thinking_effort": 2,
      "max_tokens": 16384,
      "show_thinking": true,
      "system_prompt": "You are a precise coding assistant. Prefer minimal diffs.",
      "approval": {
        "default": "ask",
        "rules": [
          { "tool": "shell",       "action": "ask"   },
          { "tool": "filebrowser", "action": "allow" }
        ]
      }
    },
    "lean": {
      "openrouter_model": "openai/gpt-4o-mini",
      "temperature": 0.3,
      "max_tokens": 2048,
      "thinking_effort": 0,
      "include_tools": ["calculator", "memory", "grep_search"],
      "subagent": {
        "max_depth": 0
      }
    }
  }
}
```

---

## Merge semantics

Resolution order (later layers win):

```
DEFAULTS → config.json base → selected profile → CLI flags
```

- A profile only needs to declare keys that differ from the base config.
- Nested objects (`approval`, `subagent`) are **whole-block replacement**, not deep merge. If a profile sets `approval`, that block fully replaces the base `approval`.
- The `profiles` key itself is stripped before the config object is built — it is metadata, not a runtime setting.

---

## Subagent profile

`spawn_agent` accepts an optional `profile` arg. The child session's config is resolved as:

```
DEFAULTS → config.json base → profile (explicit arg, else subagent.default_profile, else no overlay)
```

The parent's active profile does **not** bleed into the child.

- `spawn_agent(task="...", profile="lean")` — uses the `lean` profile explicitly
- `spawn_agent(task="...")` — falls back to `subagent.default_profile` if set, otherwise base config
- An unknown profile name in either the arg or `subagent.default_profile` is a hard error

---

## New config keys introduced

| Key | Type | Scope | Description |
|-----|------|-------|-------------|
| `profiles` | object | top-level | Dict of profile name → partial config object |
| `include_tools` | array of strings | top-level or profile | Allowlist of tool names to expose. All others are excluded. |
| `exclude_tools` | array of strings | top-level or profile | Denylist of tool names. All others are exposed. Cannot be combined with `include_tools`. |
| `subagent.default_profile` | string | `subagent` block | Profile to apply to child sessions when `spawn_agent` is called without an explicit `profile` arg. |

`include_tools` and `exclude_tools` mirror the existing `--include-tools` / `--exclude-tools` CLI flags and share the same application logic.

---

## Current valid config keys (for reference)

| Key | Type | Default |
|-----|------|---------|
| `backend` | string | `"textgen"` |
| `api_url` | string (URI) | `"http://127.0.0.1:5000"` |
| `model` | string | `"gemma-4-E4B-it-uncensored-Q4_K_M.gguf"` |
| `temperature` | number 0–2 | `0.7` |
| `top_p` | number 0–1 | `0.95` |
| `top_k` | integer ≥0 | `20` |
| `max_tokens` | integer ≥1 | `2048` |
| `thinking_effort` | 0\|1\|2\|3 | `0` |
| `show_thinking` | boolean | `false` |
| `show_tool_calls` | boolean | `true` |
| `show_tool_responses` | boolean | `false` |
| `show_system_prompt` | boolean | `false` |
| `system_prompt` | string | `"You are a helpful assistant."` |
| `append_datetime` | boolean | `true` |
| `sessions_dir` | string (path) | `~/.local/share/nugget/sessions` |
| `debug` | boolean | `false` |
| `openrouter_api_key` | string | `""` |
| `openrouter_model` | string | `"openai/gpt-4o-mini"` |
| `approval` | object | *(see CONFIG.md)* |
| `subagent` | object | *(max_depth, max_context_bytes, max_turns_default, max_turns_cap, stream_inner, default_system_prompt)* |
