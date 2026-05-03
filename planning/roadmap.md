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

### v0.3 — "Routing & backends complete" — SHIPPED

Released as **0.3.0**. NUG-001, NUG-002, NUG-003, NUG-010 merged. NUG-005
(Jinja template sink) deferred. Four bonus tools landed alongside the release
(`grep_search`, `http_fetch`, `jq`, `tasks`) — see NUG-017 for their docs
catch-up.

**Original framing (kept for context):**

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

### v0.4 — "Subagent MVP"

**Theme:** Ship the subagent primitive — child sessions seeded with parent
tool output, returning a distilled answer. Single biggest user-facing capability
gain; unblocks pipelines like `grep → distill → answer` without bloating the
parent's context window.

**Tickets:** NUG-015, NUG-016, NUG-017

**Spec:** `tool_docs/SUBAGENT_SPEC.md` (covers semantics, API surface,
approval gating, persistence, open questions).

**Why this slice:**
- The subagent feature is the headline user request for the next release. It
  is *the* feature contributors will be asked about.
- Re-scoping ROADMAP item #14 to NOT depend on agent configs (#12) and skills
  (#13) means we can deliver value without a multi-feature dependency stack.
- NUG-016 (bench tests) ships in the same release because subagent behaviour
  is exactly the kind of model-compliance-against-prompt question the bench
  was built for. Without bench coverage, regressions are silent.
- NUG-017 (tool docs catch-up) is small and bundles cleanly here so v0.4 ships
  with `TOOL_SPEC.md` accurate.

**Out of scope for v0.4:** web UI work, status bar, hooks, MCP, agent
configs, skills, parallel subagents, inner-stream events.

**Definition of done:**
- `spawn_agent` tool callable from any backend; child runs with explicit
  context, allowlisted tools, capped recursion depth.
- `bench/cases/subagent.tsv` runs end-to-end in mock mode at ≥80% pass rate.
- The eight open questions in `tool_docs/SUBAGENT_SPEC.md` §8 are resolved
  and captured in the spec.
- `tool_docs/TOOL_SPEC.md` documents the four bonus v0.3 tools plus
  `spawn_agent`.

### v0.5 — "Web UI parity"

**Theme:** Bring the web frontend up to CLI feature parity and add the long-promised live observability.

**Tickets:** NUG-004, NUG-007, NUG-008, NUG-009, NUG-011

**Why this slice:**
- The web server already emits `thinking`, `tool_call`, `tool_result` SSE events. Most of NUG-008 is frontend-only.
- NUG-004 (web tool approvals) closes the awkward `ask`-becomes-`allow` downgrade.
- NUG-007 (status bar) is the first visible answer to "how do I know what's happening?" in both CLI and web — the same data (session ID, title, token counts) ends up in two surfaces.
- NUG-009 (web tool toggles) requires NUG-011 to land first (the `tools.disabled` config key, plus making the server actually filter).

**Out of scope for v0.4:** subagents, agent configs, MCP, hooks. Still in design.

### v0.6 — "Session intelligence"

**Theme:** Make sessions retrievable, searchable, and titled.

**Tickets:** NUG-006, NUG-014

NUG-006 (session-title computation) needs *enough* hooks plumbing to fire `on_message` once per session, but does not require the full hooks framework. It's a coherent slice. NUG-014 (semantic search) gives the user a real reason to want titles in the first place.

### v0.7+ — "Extensibility" (design pending)

These ROADMAP items need design rounds before any ticket:

- **#4 — Hooks framework** (full): `on_session_start/end`, `on_message`, `on_response`, `pre_tool`, `post_tool`, `on_file_change`, `on_git`. Big surface; the per-event payload schemas, async vs sync, blocking semantics, and `inotify` fallback all want design before implementation.
- **#6 — MCP support**: stdio + HTTP/SSE servers, namespaced tool routing, lifecycle. Wants a design doc that covers connection management, error recovery, and how MCP tools interact with the existing approval system.
- **#12 — Agent configs**: persistent named configs with their own memory DBs. Question to answer: does an agent inherit pinned memories from the global DB or not?
- **#13 — Skill support**: depends on #12.
- **#14 — Subagent framework**: ~~depends on #13~~ — re-scoped 2026-04-29.
  MVP ticketed as **NUG-015** for v0.4 against `tool_docs/SUBAGENT_SPEC.md`.
  Skill-bundle integration (`skill: <name>` arg in `spawn_agent`) remains
  design-pending behind #13.

These should not be turned into tickets until each has at least a one-page design note in `tool_docs/`.

- **#18 — Structured generation for tool calls**: grammar-constrained decoding
  at the token level; logit-bias or llama.cpp grammar masks hallucinated arg keys
  out of the vocabulary during tool call generation. Motivated by logprob findings
  in `planning/issue-3.md` — `return_thinking` samples at 87% confidence,
  unreachable by temperature tuning. Requires a probe to confirm `text-generation-webui`
  exposes `logit_bias` or `grammar` params. Design note needed before ticketing.

- **#19 — Forced thinking injection + keyword triggers**: two mechanisms —
  (a) keyword-triggered reasoning prefixes injected at the harness level on
  pattern-matched user messages (deterministic, no model change), and (b) a
  forced mid-generation stop-and-think step before tool arg close. Preliminary
  logprob probes in `planning/forced_thinking_probe.md` show this can shift
  `output` from 12% to dominant probability. Complementary to #18.
  See `planning/issue-3.md` for the failure cases that motivate this.

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
