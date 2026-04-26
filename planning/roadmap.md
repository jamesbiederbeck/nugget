# Nugget — strategic roadmap (planning view)

This is the planning-side companion to `ROADMAP.md` at the repo root.
`ROADMAP.md` enumerates *items*; this file frames them into *releases* and
flags which ones aren't ready to be ticketed yet.

## Themes

Three things distinguish Nugget from "another local-LLM CLI":

1. **Output routing.** The model decides where its tool results go (display, file, variable). This is the architectural bet. Items #1 and #11 round it out.
2. **Pluggable backends.** Local-first, but not locked to text-generation-webui. Items #2 and #3 prove the abstraction.
3. **Bench-driven prompt engineering.** The model's compliance with output routing is measured, not hoped for. Items #16 and #17 build the toolkit; the existing bench already runs.

A fourth theme is emerging but isn't ready to ship: **session/agent context** — hooks, status bar, agent configs, MCP. These all want to land but each needs design alignment first.

---

## Release framing

### v0.3 — "Routing & backends complete"

**Theme:** Finish the output-routing story; prove the backend abstraction with a real second backend.

**Tickets:** NUG-001, NUG-002, NUG-003, NUG-005, NUG-010

**Why this slice:**
- NUG-001 (`render_output` dispatch) is a stub that the model is already being told to use. It is the single biggest user-facing hole. Without it, `bench/cases/render_output.tsv` measures intent only.
- NUG-002 + NUG-003 turn the `Backend` Protocol into a tested ABC and ship a second backend (OpenRouter), validating the abstraction.
- NUG-005 (Jinja template sink) is the natural next step after NUG-001 — together they make output routing feature-complete.
- NUG-010 (doc drift) is cheap; bundling it with a release that touches backends keeps `CONTRIBUTING.md` accurate while contributors are looking at it.

**Out of scope for v0.3:** any web-UI work, status bar, hooks, MCP, agent configs. Those are richer designs that should not be rushed.

**Definition of done:**
- `nugget --backend openrouter` works against a real OpenRouter API key.
- `render_output(tool_name, tool_args, output=...)` works for `display`, `display:<jmespath>`, `file:<path>`, `$var`, and template sinks.
- All bench cases in `render_output.tsv` evaluate end-to-end (not just intent).
- `CONTRIBUTING.md` and `tool_docs/TOOL_SPEC.md` reflect the actual `Backend.run()` 4-tuple signature.

### v0.4 — "Web UI parity"

**Theme:** Bring the web frontend up to CLI feature parity and add the long-promised live observability.

**Tickets:** NUG-004, NUG-007, NUG-008, NUG-009, NUG-011

**Why this slice:**
- The web server already emits `thinking`, `tool_call`, `tool_result` SSE events. Most of NUG-008 is frontend-only.
- NUG-004 (web tool approvals) closes the awkward `ask`-becomes-`allow` downgrade.
- NUG-007 (status bar) is the first visible answer to "how do I know what's happening?" in both CLI and web — the same data (session ID, title, token counts) ends up in two surfaces.
- NUG-009 (web tool toggles) requires NUG-011 to land first (the `tools.disabled` config key, plus making the server actually filter).

**Out of scope for v0.4:** subagents, agent configs, MCP, hooks. Still in design.

### v0.5 — "Session intelligence"

**Theme:** Make sessions retrievable, searchable, and titled.

**Tickets:** NUG-006, NUG-014

NUG-006 (session-title computation) needs *enough* hooks plumbing to fire `on_message` once per session, but does not require the full hooks framework. It's a coherent slice. NUG-014 (semantic search) gives the user a real reason to want titles in the first place.

### v0.6+ — "Extensibility" (design pending)

These ROADMAP items need design rounds before any ticket:

- **#4 — Hooks framework** (full): `on_session_start/end`, `on_message`, `on_response`, `pre_tool`, `post_tool`, `on_file_change`, `on_git`. Big surface; the per-event payload schemas, async vs sync, blocking semantics, and `inotify` fallback all want design before implementation.
- **#6 — MCP support**: stdio + HTTP/SSE servers, namespaced tool routing, lifecycle. Wants a design doc that covers connection management, error recovery, and how MCP tools interact with the existing approval system.
- **#12 — Agent configs**: persistent named configs with their own memory DBs. Question to answer: does an agent inherit pinned memories from the global DB or not?
- **#13 — Skill support**: depends on #12.
- **#14 — Subagent framework**: depends on #13. The `spawn_agent` tool is the easy part; thread/process model and result aggregation is the hard part.

These should not be turned into tickets until each has at least a one-page design note in `tool_docs/`.

---

## Bench enhancements (parallel track)

Bench items can ship at any time — they don't block any release. NUG-012 and NUG-013 are good "any contributor with a free afternoon" tickets.

---

## What we deliberately are not building

Captured here so it doesn't keep coming up in PR review:

- **A "full-featured chat client".** README is explicit: "It's not trying to be a full-featured chat client or knowledge management system."
- **Multi-user / hosted nugget.** The web server is local-first. No auth, no rate limiting, no per-user data.
- **A custom prompt format.** We ride on text-generation-webui / OpenAI-compatible APIs.
- **Inference.** No bundled model server; nugget always proxies to one.

---

## Risks to flag

- **Single-developer cadence.** Recent commits show steady momentum but the bus factor is one. Anything that requires multi-PR coordination (e.g. hooks framework) compounds that risk. Ship small.
- **Model-specific assumptions.** `TextgenBackend` is tightly coupled to Gemma 4 special tokens. The OpenRouter backend (NUG-003) will need a different prompt strategy entirely. Don't try to share too much.
- **Bench depends on a reachable backend.** If `--mock-tools` isn't sufficient for a future test it'll silently degrade. Worth keeping an eye on bench reliability as it scales.
