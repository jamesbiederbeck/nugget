# Nugget — Subagent Specification

> **Status:** Draft (v0)
> **Owner:** Product
> **Targets:** v0.4 (subagent MVP), v0.5 (full skill/agent integration)
> **Related:** ROADMAP.md items #12 (agent configs), #13 (skills), #14 (subagent framework); planning/backlog.md NUG-015 (this spec); NUG-016 (bench tests)

---

## 1. What "subagent" means in Nugget

A **subagent** is a *child Nugget session* spawned synchronously by the parent
session in order to delegate a focused sub-task. It is **not**:

- a separate OS process or container
- a remote/cloud agent
- a long-lived background worker
- a different model API integration

A subagent is the same `Session` + `Backend.run()` machinery the parent uses,
invoked *recursively* with a constrained context: a fresh message history, a
custom system prompt seeded with parent-supplied context blobs, and an
optionally-narrower tool set.

The parent receives back a single dict containing the child's final assistant
text (and optionally its thinking trace and tool exchanges).

### Why this primitive

Three concrete user patterns motivate it:

1. **Distillation.** `grep_search` returns 200 matches. Pipe them into a
   subagent whose only job is "given these matches, identify the three files
   most likely to contain the bug." Parent gets a 30-token answer instead of a
   30 KB tool result.
2. **Context isolation.** Subagent runs without the parent's chat history, so
   irrelevant earlier turns don't pollute its reasoning. Parent's context window
   stays small.
3. **Role specialisation.** Parent is a generalist; subagent has a tight system
   prompt ("you are a code reviewer; output only a JSON list of issues").
   Combines naturally with skills (#13) and agent configs (#12) once those
   exist.

---

## 2. How tool output gets injected into the child's system prompt

The parent calls a new `spawn_agent` tool. The tool's arguments include a
`context` field (and/or variable references via the existing `$var` binding
system). The harness builds the child's system prompt as:

```
<base system prompt — either inherited from parent config, or a skill prompt>

## Provided context

### <key 1>
<rendered value 1>

### <key 2>
<rendered value 2>
...

## Task

<task string from spawn_agent args>
```

### Two ways context is supplied

**(a) Inline literal (small payloads):**

```json
{
  "tool": "spawn_agent",
  "args": {
    "task": "Identify which file is most likely to contain the bug.",
    "context": {
      "matches": "src/foo.py:42: ...\nsrc/bar.py:71: ..."
    }
  }
}
```

**(b) From bound variables (large payloads, the primary use case):**

```json
// turn 1
{ "tool": "grep_search", "args": { "pattern": "...", "output": "$matches" } }

// turn 2
{
  "tool": "spawn_agent",
  "args": {
    "task": "Identify which file is most likely to contain the bug.",
    "context_vars": ["matches"]
  }
}
```

`context_vars` is resolved by the harness against the current turn's binding
table (the same `bindings` dict the per-call sink machinery already manages).
Each named binding becomes a `### <name>` block inside the child's system
prompt. The parent model never has to inline the raw payload into context.

### Rendering rules

- Strings → inserted verbatim.
- Dicts/lists → JSON-encoded with `indent=2`.
- Anything else → `repr()`.
- Total context size is capped (default 32 KB, configurable as
  `subagent.max_context_bytes`); over-cap context is truncated with a sentinel
  line `... [truncated, N bytes omitted]`.

---

## 3. API surface

### 3a. The `spawn_agent` tool (primary surface)

A new built-in tool, auto-discovered like any other.

```python
SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": (
            "Spawn a focused sub-session to handle a delegated task. "
            "The child session runs with a custom system prompt, the provided "
            "context, and a tool allowlist. Returns the child's final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What the subagent should accomplish, in plain English."
                },
                "context": {
                    "type": "object",
                    "description": "Inline named context blobs to inject into the child's system prompt."
                },
                "context_vars": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Names of turn-bound variables ($var) to inject into the child's context."
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional custom system prompt for the child. Defaults to a focused-assistant template."
                },
                "tools": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Allowlist of tool names available to the child. Default: empty (no tools — pure reasoning)."
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Tool-loop iteration cap for the child (default 4, max 16)."
                },
                "return_thinking": {
                    "type": "boolean",
                    "description": "If true, include the child's chain-of-thought in the result. Default false."
                },
                "skill": {
                    "type": "string",
                    "description": "Reserved. Skill-bundle integration — accepted but ignored in v0.4."
                }
            },
            "required": ["task"]
        }
    }
}
```

**Output shape:**

```json
{
  "answer": "<child's final assistant text>",
  "thinking": "<optional, only when return_thinking=true>",
  "tool_calls": 2,
  "finish_reason": "stop",
  "truncated_context": false
}
```

**Approval gate:** see Section 5.

### 3b. Backend method (internal plumbing)

`Backend.run()` is *not* changed. The `spawn_agent` tool's `execute()`
constructs a fresh in-memory `Session`, builds the system prompt, and calls
`backend.run(...)` directly using the parent's resolved backend instance. The
backend is reused by reference (no new instance per subagent), but each call is
otherwise independent.

A small new helper module `src/nugget/subagent.py` houses the assembly and
recursion-depth bookkeeping so `tools/spawn_agent.py` stays thin.

### 3c. CLI flag — none in MVP

No new CLI flag is added. Subagents are a model-driven primitive. Once skills
(#13) ship, `nugget --skill <name>` will be the user-facing entry point that
pre-loads a skill into a subagent-style context for a top-level session.

### 3d. Web-server surface

The web server gets one new SSE event type:

| `type`           | Additional fields                                            | Description                                  |
|------------------|--------------------------------------------------------------|----------------------------------------------|
| `subagent_call`  | `task: string`, `tool_count: int`, `parent_depth: int`       | A subagent invocation has begun              |
| `subagent_done`  | `answer: string`, `tool_calls: int`, `finish_reason: string` | Subagent returned                            |

Subagent-internal token / tool_call / thinking events are **not** streamed by
default in v0 (would visually conflate with parent stream). A future
`subagent.stream_inner: true` config can opt in. Note this when implementing.

---

## 4. How the child's response propagates back to the parent

The `spawn_agent` tool's `execute()` returns a dict (see 3a output shape). This
dict flows through the **same** output-routing machinery as any other tool
call:

- Default (no `output` arg) — full result inlined into the parent's tool-loop
  context as a `<|tool_response>` payload, exactly like `grep_search`'s result.
- `output: "display"` — the child's `answer` string is shown to the user; the
  parent model sees only the standard stub.
- `output: "$child_answer"` — the whole result dict bound for later use; the
  parent can reference `$child_answer.answer` in a subsequent tool call.
- `output: "file:<path>"` — written to disk under existing file-sink rules.
- `output: "display:answer"` — JMESPath-extracted display.

The child's `tool_exchanges` are **not** appended to the parent session's
message history. They are persisted in a separate per-subagent JSON file at
`~/.local/share/nugget/sessions/<parent_id>/subagents/<call_id>.json` so the
trace is recoverable for debugging without bloating the parent transcript.

---

## 5. Approval gating considerations

Subagents introduce three new approval surfaces. Each has a default and is
overridable via `config.approval.rules`.

### 5a. Spawning a subagent at all

`spawn_agent` itself has `APPROVAL = "ask"` by default. Reasoning: a subagent
can recursively cost tokens and exercise tools. Users should opt in.
Power-users can drop a config rule:

```json
{ "tool": "spawn_agent", "action": "allow" }
```

### 5b. Tools the child may use

`spawn_agent` accepts a `tools` allowlist. The child's tool registry is
filtered to that list **before** any approval check happens. Empty list (the
default) means the child has no tools — pure reasoning over the provided
context.

A child tool call still goes through the normal approval pipeline. The same
config rules apply. This means: if the parent has an explicit
`{ "tool": "shell", "action": "ask" }` rule, the child also gets `ask` for
`shell` calls — and the prompt fires with a `[subagent depth=N]` prefix in CLI
mode, web mode emits `tool_approval_request` with a `subagent: true` flag.

### 5c. Recursion depth

A subagent may itself call `spawn_agent`. The harness tracks recursion depth in
a `contextvars.ContextVar` (not `threading.local` — `nugget-server` reuses
threads across requests, so thread-locals would leak depth across sessions).
Defaults:

- `subagent.max_depth: 2` (parent → child → grandchild OK; great-grandchild
  denied).
- Exceeding the cap returns `{"_denied": true, "reason": "subagent depth limit
  exceeded"}` to the calling subagent without spawning.

### 5d. Web mode

`ask` for `spawn_agent` in web mode degrades to `allow` per the existing
convention until NUG-004 (tool approvals in web UI) lands; once that ships,
`spawn_agent` participates in the same modal flow.

---

## 6. Configuration

New `subagent` block in `config.json`:

```json
{
  "subagent": {
    "max_depth": 2,
    "max_context_bytes": 32768,
    "max_turns_default": 4,
    "max_turns_cap": 16,
    "stream_inner": false,
    "default_system_prompt": "You are a focused subagent. Read the provided context and return a concise answer to the task. Do not ask follow-up questions."
  }
}
```

All keys are optional; defaults baked into `Config.DEFAULTS`.

---

## 7. Persistence

- Parent session JSON is unchanged in shape. The `tool_call` for `spawn_agent`
  is persisted like any other.
- Each subagent invocation is persisted to
  `~/.local/share/nugget/sessions/<parent_id>/subagents/<call_id>.json`,
  containing the full child message list, tool exchanges, and timing data.
- `Session.list_sessions()` does **not** list subagent files. They are surfaced
  on demand by `Session.load_subagents(parent_id)` (new helper).

---

## 8. Decisions

1. **Backend reuse.** **Decision: reuse the parent's `Backend` instance.**
   Simpler; keeps stateful auth in place. A fresh instance would require
   re-reading config and re-authenticating with no benefit in the MVP.

2. **Cost accounting.** **Decision: both** — a `subagent_tokens` field in the
   per-call JSON, plus the child's usage rolled into the parent session total.
   Needed for NUG-007 (status bar) to show accurate session-wide token counts.

3. **Streaming inner events.** **Decision: no summarised stream in v0.** Only
   `subagent_call` and `subagent_done` SSE events are emitted. Inner token /
   tool_call / thinking events are suppressed. Revisit in v0.5 if users ask
   for a "subagent: working…" indicator.

4. **Sharing memory.** **Decision: child gets the memory tool only if `memory`
   is in the `tools` allowlist.** No special isolation. Once agent configs
   (#12) land they can scope the DB per-agent-config.

5. **Pinned memories.** **Decision: not injected into the child.** The child
   gets only the explicitly-provided `context` / `context_vars`. Pinned
   memories are a parent-session concern.

6. **Failure mode when context exceeds cap.** **Decision: truncate + sentinel
   line** (`... [truncated, N bytes omitted]`). The model can decide what to
   do with partial information; rejection would make large-payload distillation
   impossible.

7. **Concurrency.** **Decision: sequential only (MVP).** Backend `run()` is
   single-threaded per session. Parallel sibling spawning is a post-MVP
   optimisation.

8. **Skill integration.** **Decision: add `skill` as an optional, ignored
   field now** so that adding skill semantics later is non-breaking. See SCHEMA
   in §3a. The field is accepted but has no effect in v0.4.

---

## 9. Dependencies and sequencing

This spec **does not** depend on NUG-012 (agent configs) or NUG-013 (skills)
shipping first. The MVP is a self-contained `spawn_agent` tool with inline
configuration. Skills and agent configs become *additional ergonomic surfaces*
on top of it.

Suggested implementation order:

1. **NUG-015 — `spawn_agent` MVP.** Tool, helper module, recursion guard,
   config block, parent-side per-call persistence.
2. **NUG-016 — Subagent bench tests.** Integration tests exercising the full
   parent→child→answer round-trip end-to-end.
3. **NUG-017 — Web SSE events** (`subagent_call`, `subagent_done`).
4. **Later:** skill integration, parallel spawning, opt-in inner streaming.

---

## 10. Out of scope

- Multi-process / multi-host subagents.
- Subagent message-history persistence in the parent session JSON.
- Streaming the subagent's inner tokens to the user by default.
- Cross-subagent communication (siblings cannot see each other's context).
- Cost/token budgets enforced at the subagent layer (the existing
  `max_tokens` per `Backend.run()` call already bounds it).
