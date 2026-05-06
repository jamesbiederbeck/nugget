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
- [x] Branching strategy — develop → staging → main with per-branch CI and Docker
- [x] `render_output` dispatch (NUG-001) — routing helpers hoisted to `_routing.py`
- [x] `Backend` ABC (NUG-002)
- [x] OpenRouter backend (NUG-003)
- [x] Doc-drift cleanup, v0.3.0 release (NUG-010)
- [x] `grep_search` tool (ripgrep wrapper, allow-by-default)
- [x] `http_fetch` tool (GET/HEAD allow, mutating methods ask)
- [x] `jq` tool (JMESPath query over JSON / `$var` payloads)
- [x] `tasks` tool (SQLite task list, delete asks)

## Backlog

Items ordered by priority. "Requires" lists hard blockers (✓ = already done).
"Unblocks" lists items that cannot start until this one is complete.

| # | Item | Requires | Unblocks |
|---|------|----------|---------|
| 1 | ~~`render_output` dispatch~~ ✓ | output routing ✓, shell ✓ | Jinja sink, bench updates |
| 2 | ~~Backend ABC~~ ✓ | `Backend` Protocol ✓ | OpenRouter backend |
| 3 | ~~OpenRouter backend~~ ✓ | Backend ABC (#2) | — |
| 4 | Hooks framework | session ✓, tool system ✓ | Session title, git/file hooks |
| 5 | Session title computation | hooks (#4), backend ✓ | Status bar title field |
| 6 | MCP support | tool system ✓, Backend Protocol ✓ | External tool ecosystem |
| 7 | ~~Tool approvals in web UI~~ ✓ | approval system ✓, SSE ✓ | — |
| 8 | Status bar — CLI + web | session title (#5) | Streaming thinking display |
| 9 | Streaming thinking blocks | SSE ✓; status bar (#8) for CLI | — |
| 10 | Tool toggles in web UI | web server ✓ | — |
| 11 | Jinja template sink | `render_output` (#1) ✓, `$var` binding ✓ | — |
| 12 | Agent configs | config ✓, memory ✓, approval ✓ | Skill support, subagents |
| 13 | Skill support | agent configs (#12) | Subagent framework |
| 14 | **Subagent framework (`spawn_agent`)** — see `tool_docs/SUBAGENT_SPEC.md` | session ✓, backends ✓; agent configs (#12) and skills (#13) **NOT required for MVP** | Skill-based subagents |
| 15 | Semantic search | memory.db ✓ | — |
| 16 | Bench: prompt-variant sweeping | bench ✓ | — |
| 17 | Bench: flakiness report | bench ✓ | — |
| 18 | Structured generation for tool calls | textgen backend ✓ | Eliminates hallucinated args (#19 complementary) |
| 19 | Forced thinking injection + keyword triggers | system prompt ✓, bench ✓ | Structured generation (#18 complementary) |
| 20 | ~~`render_output`-nested web approvals~~ ✓ | tool approvals in web UI (#7) ✓ | — |

**Note:** Item #14 has been re-scoped. The `tool_docs/SUBAGENT_SPEC.md` MVP is
self-contained and does NOT block on agent configs (#12) or skills (#13);
those become additional ergonomic surfaces layered on top once they ship.

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

## MCP (Model Context Protocol)

Connect Nugget to external MCP servers so their tools are available to the model
alongside built-in tools. MCP servers expose a standard tool-discovery and
tool-call interface over stdio or HTTP/SSE.

### Config

```json
"mcp_servers": [
  {
    "name": "filesystem",
    "type": "stdio",
    "command": "npx -y @modelcontextprotocol/server-filesystem /home/user/docs"
  },
  {
    "name": "brave-search",
    "type": "http",
    "url": "http://localhost:3001/sse",
    "headers": { "Authorization": "Bearer $BRAVE_API_KEY" }
  }
]
```

### Implementation

- On startup, spawn each `stdio` server as a subprocess and perform the MCP
  `initialize` + `tools/list` handshake.
- Merge returned tool schemas into the tool registry under namespaced names
  (`mcp__<server>__<tool>`). The model sees them alongside built-in tools with no
  special handling needed.
- Route `mcp__*` tool calls to the appropriate server via `tools/call`; return
  the result through the existing tool executor / output sink pipeline.
- Apply the same approval rules as built-in tools; `pre_tool` hooks fire for MCP
  tools using the full namespaced name as the matcher target.
- HTTP/SSE servers are connected lazily on first tool call.

---

## Hooks

User-defined shell commands that execute at specific points in the session
lifecycle. Defined in `config.json` under `"hooks"` (or in an agent config for
per-agent hooks). All hooks receive a JSON payload on stdin and return optional
JSON on stdout; exit code controls whether the hook blocks or modifies behaviour.

### Protocol

```
stdin  → JSON event payload (see event schemas below)
stdout → optional JSON response (additionalContext, decision, etc.)
exit 0 → success; stdout JSON is parsed and applied
exit 2 → blocking error; stderr message shown, action denied
other  → non-blocking error; first stderr line shown to user
```

All events include `session_id`, `cwd`, and `hook_event` fields.

### Events

| Event | Trigger | Blocking | Notes |
|-------|---------|----------|-------|
| `on_session_start` | Session opens (new or resumed) | No | Inject context via `additionalContext` |
| `on_session_end` | Session saves and exits | No | Observability / cleanup |
| `on_message` | User submits a message | Yes | Can block or inject context; fires before model call |
| `on_response` | Model finishes a turn | No | Full response text available |
| `pre_tool` | Before a tool executes | Yes | Can allow / deny / modify args via `permissionDecision` + `updatedInput` |
| `post_tool` | After a tool succeeds | No | Tool name, args, and result available |
| `on_file_change` | Watched file created / modified / deleted | No | Path and change type; can inject context |
| `on_git` | Git HEAD or index changes | No | Branch, commit hash, staged file list available |

Hooks may be matched to a subset of events using a `matcher` field (tool name
glob for `pre_tool`/`post_tool`, `new`/`resumed` for `on_session_start`, etc.).

### Config format

```json
"hooks": [
  {
    "event": "on_message",
    "command": "~/.config/nugget/hooks/title.sh",
    "async": false
  },
  {
    "event": "pre_tool",
    "matcher": "shell",
    "command": "~/.config/nugget/hooks/shell-guard.sh"
  },
  {
    "event": "on_file_change",
    "watch": ["~/project/src/**/*.py"],
    "command": "~/.config/nugget/hooks/file-ctx.sh",
    "async": true
  },
  {
    "event": "on_git",
    "watch": ".git/HEAD",
    "command": "~/.config/nugget/hooks/git-ctx.sh",
    "async": true
  }
]
```

`on_file_change` and `on_git` run a background watcher thread that polls (or uses
`inotify` where available); changes inject an `additionalContext` message into the
next turn rather than interrupting the current one.

### Built-in: `on_git`

Git context hook fires whenever `.git/HEAD` or `.git/index` changes. The JSON
payload includes `branch`, `commit`, and `staged_files`. Can be used to
automatically surface branch and diff context without any manual `/git status`
invocations.

---

## Sessions

### Session title computation
Implemented as a built-in `on_message` hook that fires on the first user message
(`message_index == 0`). The hook fires a lightweight background completion call
with the message content and an instruction to produce a ≤5-word topic title,
then writes the result back to the session file as `"title"`. Does not block the
main response. Displayed in session lists, the status bar, and the web UI header.

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

---

## Structured generation for tool calls (#18)

Grammar-constrained decoding applied during tool arg generation. The textgen
backend knows the current tool's JSON schema at call time; this information can
be used to restrict the token sampler to only valid arg keys and value types,
making hallucinated keys (e.g. `return_thinking`) physically impossible to emit.

**Motivation:** logprob probes on sessions b3077b8b and d0b46965 (see
`planning/issue-3.md`) show `return_thinking` sampled at 87–94% confidence
when the model decides to add an extra arg to `spawn_agent`. Temperature alone
cannot suppress this; the token distribution must be masked at sampling time.

**Implementation sketch:**

- After the model emits `<|tool_call>call:<name>{`, parse the schema for `<name>`
  from the tool registry.
- Drive a streaming grammar state machine: at each token position within the arg
  dict, compute the set of valid next tokens (key names, value types, delimiters)
  and pass a logit bias mask to the completions endpoint.
- `llama.cpp` / `text-generation-webui` expose `logit_bias` (token-id → additive
  log-prob adjustment); setting non-valid tokens to `-inf` effectively masks them.
- Fallback: if the model emits a stop token before closing the dict, re-prompt
  with the partial args as context and a hard error prefix.

**Unknowns:** whether `text-generation-webui`'s `/v1/completions` endpoint exposes
`logit_bias` or requires grammar strings (llama.cpp `grammar` param). Needs a
probe against the local server before design is locked.

**Complementary to #19.** Structured gen prevents impossible tokens; forced
thinking shifts the distribution toward the correct token before sampling.
Together they address both ends of the compliance gap.

---

## Forced thinking injection + keyword triggers (#19)

Inject a short reasoning prefix into the model turn just before critical decisions,
steering token probabilities without retraining.

**Motivation:** logprob probes (see `planning/issue-3.md`) show that at the
arg-name decision point inside `spawn_agent`, the token `output` has only 12%
probability vs `return_thinking` at 87%. A forced thinking block that names
`output` explicitly is predicted to shift this dramatically — preliminary probes
confirm this (see `planning/forced_thinking_probe.md`).

**Two sub-features:**

### Keyword-triggered context injection

Detect patterns in user messages and prepend a reasoning example to the model's
context before the completion call. The trigger is matched at the harness level
(not by the model), so it is deterministic.

Example triggers and injected thoughts:

| User message pattern | Injected thinking fragment |
|---|---|
| `"route output of .* to .*"` | `"The user wants to pipe tool output. I can do this with render_output or by binding to $var and passing it as an arg. For example: render_output(tool_name='x', tool_args={...}, output='$tmp') then tool_y(input='$tmp')."` |
| `"bind .* to \$\w+"` | `"I need to set output:'$<name>' on the tool call so the result is stored for later use."` |
| `"spawn.*subagent.*bind"` | `"spawn_agent supports output:'$var' to bind the answer into a variable for the next call."` |

Triggers are defined in config as regex → thinking fragment pairs, so users can
add their own without a code change.

### Forced stop + thinking before tool-arg close

At the token level: after the model opens a tool call arg dict and has emitted
the required args, intercept just before `}` and inject a constrained thinking
step: "Have I included all routing args the user asked for?" Then resume sampling.

This is the in-loop equivalent of CoT forcing — it costs one extra completion
round-trip per tool call but can be gated behind a config flag
(`"force_arg_review": true`).

**Relationship to structured gen (#18):** #18 prevents the wrong token; #19
shifts the distribution toward the right one. Both are needed for full compliance.
#19 alone is implementable today against any backend. #18 requires backend
cooperation (`logit_bias` or grammar support).
