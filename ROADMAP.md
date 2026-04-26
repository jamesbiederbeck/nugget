# Nugget — Roadmap

## Done
- [x] Basic chat interface
- [x] Tool calling framework
- [x] Thinking (chain-of-thought)
- [x] Session management (save, resume by ID, resume last)
- [x] Swappable backends
- [x] Pinned memories in system prompt
- [x] Output routing — `display`, `file:`, `$var` sinks
- [x] Prompt compliance bench with SQLite result storage
- [x] Shell commands tool (`tools/shell.py`)
- [x] `render_output` stub + bench cases

## Backlog

Items ordered by priority. "Requires" lists hard blockers (✓ = already done).
"Unblocks" lists items that cannot start until this one is complete.

| # | Item | Requires | Unblocks |
|---|------|----------|---------|
| 1 | `render_output` dispatch | output routing ✓, shell ✓ | Jinja sink, bench updates |
| 2 | Backend ABC | `Backend` Protocol ✓ | OpenRouter backend |
| 3 | OpenRouter backend | Backend ABC (#2) | — |
| 4 | Session title computation | backend ✓, session ✓ | Status bar title field |
| 5 | Tool approvals in web UI | approval system ✓, SSE ✓ | — |
| 6 | Status bar — CLI + web | session title (#4) | Streaming thinking display |
| 7 | Streaming thinking blocks | SSE ✓; status bar (#6) for CLI | — |
| 8 | Tool toggles in web UI | web server ✓ | — |
| 9 | Jinja template sink | `render_output` (#1), `$var` binding ✓ | — |
| 10 | Agent configs | config ✓, memory ✓, approval ✓ | Skill support, subagents |
| 11 | Skill support | agent configs (#10) | Subagent framework |
| 12 | Subagent framework | session ✓, backends ✓, agent configs (#10), skills (#11) | — |
| 13 | Semantic search | memory.db ✓ | — |
| 14 | Bench: prompt-variant sweeping | bench ✓ | — |
| 15 | Bench: flakiness report | bench ✓ | — |

---

## Output routing

### `render_output` dispatch tool
`render_output` stub exists in `tools/render_output.py`; `execute()` raises
`NotImplementedError`. Implementation: look up `tool_name` in the tool registry,
call its `execute()`, then route the result through the existing output sink
mechanism. `output` arg is optional; absent means `display`.

```
render_output(tool_name, tool_args)                        → display (default)
render_output(tool_name, tool_args, output="file:/tmp/x")  → file
render_output(tool_name, tool_args, output="$var")         → variable binding
```

Bench cases should be updated to assert `tool_call[0].name == "render_output"`
and `tool_call[0].args.tool_name` rather than annotated domain calls.

### Jinja template sink
Add a `template` output sink. The model binds tool outputs to named variables
(`output: "$article"`) then writes its final response as a Jinja2 template
(`The title is {{ article.title }}`). The harness renders it before displaying
or saving — the model never needs large tool payloads inlined into context.

Implementation sketch:
- New sink value: `output: "template"` (or `output: "render"`)
- When the turn ends with bound variables and `finish_reason="stop"`, render
  `final_text` as a Jinja2 template with the bindings as context
- Bench test: `constraint_type=regex`, `constraint_value=^template$`,
  `target=tool_call[0].args.output`

---

## Tools

### Tool toggles in web UI
Per-tool enable/disable controls in the web interface, mirroring the config-level
`tools.disabled` list. No backend changes needed — the tool list passed to
`Backend.run()` is already filtered at call time.

### Tool approvals in web UI
Surface the approval gate interactively in the web UI (currently `"ask"` silently
upgrades to `"allow"` in server mode). Requires a new SSE event type
(`tool_approval_request`) that the frontend handles with a modal; the backend
thread blocks on a `Future` until the response arrives over a companion
`/api/sessions/{id}/approve` endpoint.

---

## Backends

### Backend abstract base class
The `Backend` Protocol in `backends/__init__.py` is already `@runtime_checkable`.
Formalize it as an ABC with typed signatures so type-checkers validate new
implementations and the `make_backend` factory has a concrete return type.
Small refactor — no behavior changes.

### OpenRouter backend
A backend that targets the OpenRouter `/v1/chat/completions` API, enabling any
model available on OpenRouter without running a local inference server.
Config key: `"backend": "openrouter"` + `"openrouter_api_key"` + `"openrouter_model"`.

---

## Sessions

### Session title computation
After the first user message, fire a separate lightweight completion call with
the message content and an instruction to produce a short topic title (≤5 words).
Store the result as `"title"` in the session JSON. Display it in session lists,
the status bar, and the web UI header. Use a fast model or the same backend with
a one-shot prompt; don't block the main response.

---

## Status bar

Add a persistent status line to both the CLI (via `rich.live` / `rich.layout`)
and the web UI (footer bar). Fields:

- **Session ID** — current session identifier
- **Session title** — computed title once available; blank until set
- **Backend** — active backend name (e.g. `textgen`, `openrouter`)
- **Session tokens** — running total for the current session
- **Thinking tokens** — cumulative count for hidden thinking blocks, updated
  from streamed token counts even when thinking content is not displayed
- **Tokens/s** — throughput of the most recent response

### Streaming thinking blocks
Show thinking content as it streams in both CLI and web UI, with a
collapse/expand toggle. The thinking token counter in the status bar updates
regardless of whether the block is expanded. For the CLI this is part of the
`rich` live layout; for the web UI it is an existing SSE `thinking` event already
emitted by the server — the frontend just needs to render it.

---

## Agent configs

Named, persistent configurations stored in `~/.config/nugget/agents/<name>.json`.
Each agent config overrides or extends the global `config.json` and carries its
own memory database and approval rules.

### Config structure

```json
{
  "system_prompt": "You are a concise research assistant.",
  "inherit_system_prompt": true,
  "tools_disabled": ["shell"],
  "approval": { "rules": [...] },
  "backend": "openrouter",
  "model": "anthropic/claude-haiku-4-5"
}
```

`inherit_system_prompt: true` appends the agent's prompt to the global system
prompt rather than replacing it. All other keys follow the same semantics as
`config.json` and override the global value for the duration of the session.

### Memory scoping

Each agent gets its own SQLite database at
`~/.local/share/nugget/memory/<agent-name>.db`. The default (no agent config)
continues to use `memory.db` at the top level. Agents do not share memory by
default; if cross-agent recall is needed, the user pins memories explicitly or
the agent is given the default DB path.

A `nugget --agent <name>` flag (and equivalent web UI picker) activates the
config for the session. The active agent name is recorded in the session file
so resuming a session restores the same config.

### Relationship to skills

Skills (see below) are transient — they activate for a single invocation and
return control. Agent configs are persistent across a whole session. Skills can
reference an agent config to inherit its prompt and tool set, making them the
lightweight activation path for a named agent.

---

## Subagents & skills

### Skill support
Named, reusable prompt-and-tool bundles invoked by name (`/skill-name`). A skill
can inline its own prompt fragment and tool list, or reference an agent config
by name to inherit its full settings. Stored in `~/.config/nugget/skills/`.
This is the building block for giving subagents scoped identities.

### Subagent framework
Let the model spawn sub-sessions with their own tool sets, system prompts, and
message histories, then return a result to the parent session. Requires skill
support to define agent roles cleanly. Implementation: a `spawn_agent` tool whose
`execute()` creates a new `Session`, calls `Backend.run()`, and returns the final
text.

---

## Memory & retrieval
- [ ] Semantic search over past sessions and memory (vector index on SQLite)

---

## Bench
- [ ] System-prompt variant sweeping — run the full case matrix against multiple
  `.j2` prompt variants and compare pass rates in the DB
- [ ] `--repeat` flakiness report — query DB for cases with mixed pass/fail
  across repeats and surface them as a stability table
