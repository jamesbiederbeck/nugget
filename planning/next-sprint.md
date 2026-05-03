# Nugget — next sprint

**Window:** 2026-04-29 → ~2026-05-13 (two weeks)
**Target release:** v0.4 (`Subagent MVP`)
**Working branch convention:** `develop` first → PR to `staging` → PR to `main` (per `CLAUDE.md`).

The previous sprint (v0.3 — Routing & backends) shipped on 2026-04-26 with
NUG-001/002/003/010 merged and four bonus tools landing alongside (`grep_search`,
`http_fetch`, `jq`, `tasks`; 298 tests passing). This sprint pivots to the
headline new feature requested for v0.4: **subagents**.

---

## Sprint goal

Ship a working subagent primitive: a `spawn_agent` tool that lets the model
delegate a focused sub-task to a child Nugget session, seeded with
parent-supplied context (typically a large tool result bound to a `$var`),
with a constrained tool allowlist, and a result that flows back through the
existing output-routing machinery. Bench coverage lands in the same release
so subagent behaviour is measured, not hoped for.

**Definition of done for the sprint:**
- `spawn_agent` callable end-to-end: parent → child → result → parent.
- All eight open questions in `tool_docs/SUBAGENT_SPEC.md` §8 resolved and
  captured in the spec.
- `bench/cases/subagent.tsv` passes ≥80% in mock mode.
- `tool_docs/TOOL_SPEC.md` updated with `spawn_agent` plus the four v0.3
  bonus tools (`grep_search`, `http_fetch`, `jq`, `tasks`).
- `pyproject.toml` bumped to `0.4.0` on `main`; release pipeline ships
  `ghcr.io/<owner>/nugget:0.4.0` and `:latest`.
- All current 298 tests still pass; net test count grows by ≥ 20
  (NUG-015 unit + NUG-016 e2e/integration).

---

## Pick order

| Order | Ticket  | Why now |
|-------|---------|---------|
| 1     | NUG-015 | The whole point of v0.4. Spec is in `tool_docs/SUBAGENT_SPEC.md`; implementation should land before bench cases that depend on it. |
| 2     | NUG-016 | Lock subagent behaviour into the bench so future regressions are visible. Best done in the same release as NUG-015 because the API and edge cases are freshest in mind. |
| 3     | NUG-017 | Pure docs. Bundle in the v0.4 release commit so `TOOL_SPEC.md` ships consistent with the source for both v0.3 bonus tools AND `spawn_agent`. |

---

## NUG-015 · `spawn_agent` tool — subagent MVP · P0 · L

### One-line goal
Let the model spawn a child Nugget session with a focused system prompt,
explicit context, and a constrained tool allowlist; return a result dict
that routes through the existing sink machinery.

### Where the work happens
- **Add:** `src/nugget/tools/spawn_agent.py`
- **Add:** `src/nugget/subagent.py` (helper module: prompt assembly, context
  rendering, recursion-depth thread-local)
- **Edit:** `src/nugget/config.py` — `Config.DEFAULTS` gains the `subagent`
  block from spec §6
- **Edit:** `src/nugget/session.py` — add `Session.load_subagents(parent_id)`,
  add per-call subagent JSON persistence helper
- **Edit:** `src/nugget/server.py` — emit `subagent_call` and `subagent_done`
  SSE events
- **Possibly edit:** `src/nugget/backends/_routing.py` — only if context-var
  resolution wants the same `bindings` lookup the sink machinery already does
- **Edit:** `tool_docs/TOOL_SPEC.md` — new tool entry
- **Edit:** `tool_docs/SUBAGENT_SPEC.md` — fill in §8 decisions
- **Add:** `tests/tools/test_spawn_agent.py`, `tests/test_subagent.py`

### Required reading before starting
1. `tool_docs/SUBAGENT_SPEC.md` — full spec, especially §3 (API), §4 (return
   propagation), §5 (approval), §8 (open questions you must resolve).
2. `src/nugget/backends/_routing.py` — the `bindings` dict and sink-validation
   helpers you'll reuse.
3. `src/nugget/tools/render_output.py` — the existing precedent for
   "tool that calls other tools".

### First step
1. Read the spec end-to-end. Decide whether to resolve `context_vars` in the
   tool's `execute()` (means the tool needs harness access — currently tools
   are pure) or in the harness layer before `execute()` is called (cleaner;
   add a `_resolve_subagent_args` step in the routing helpers).
2. Choose backend reuse strategy: spec recommends sharing the parent's
   `Backend` instance; revisit if there is hidden mutable state.
3. Stub `tools/spawn_agent.py` with the SCHEMA. Stand up
   `src/nugget/subagent.py` with just the system-prompt assembly. Get one
   end-to-end test passing (pure-reasoning child, no tools, mocked backend).
4. Layer in: tool allowlist, approval pipeline reuse, recursion-depth guard,
   per-call persistence, web SSE events, output-routing pass-through.

### Acceptance criteria (copy from `backlog.md#NUG-015`)
See backlog. Eleven acceptance criteria; the load-bearing ones are
allowlist-before-approval, depth cap, per-call persistence path, and result
flowing through `output:` sinks unchanged.

### Smoke test
```bash
uv run pytest tests/tools/test_spawn_agent.py tests/test_subagent.py -v
nugget "search this repo for 'TODO' with grep_search and bind the result to \$todos. Then spawn_agent with task='which file has the most TODOs?' and context_vars=['todos']."
```

The web smoke test (verify `subagent_call` / `subagent_done` events appear in
the SSE stream) requires an open browser tab on `nugget-server`; leave it as
a manual step in the PR description.

### Decisions captured in spec §8 (all resolved — no design round needed)
1. Backend reuse — reuse parent instance.
2. Cost accounting — separate `subagent_tokens` field + rolled into parent total.
3. Streaming inner events — none in v0; only `subagent_call`/`subagent_done`.
4. Memory sharing — child gets memory only if in `tools` allowlist.
5. Pinned memories — not injected into child.
6. Context overflow — truncate + sentinel line.
7. Concurrency — sequential only (MVP).
8. Skill arg — `skill` field in SCHEMA, ignored in v0.4.

### Estimate
1.5–2 days. The recursion guard and per-call persistence are each ~2–3
hours; output-routing pass-through wants a careful test pass.

---

## NUG-016 · Subagent bench tests · P1 · M

### One-line goal
Lock subagent behaviour into the bench so model-side regressions surface
through the existing pass-rate dashboard, not as field bug reports.

### Where the work happens
- **Add:** `bench/cases/subagent.tsv`
- **Add:** `bench/fixtures/mock_grep.py` (deterministic large payload for
  distillation cases)
- **Add:** `tests/test_subagent_e2e.py`
- **Edit:** `bench/run.py` only if a constraint type for nested-arg paths
  (`tool_call[0].args.context_vars[0]`) doesn't already exist
- **Edit:** `bench/erd.md`, `bench/README.md`

### Pre-flight
1. Confirm `bench/run.py` constraint engine supports paths into nested
   tool-call args. If not, this ticket grows by half a day.
2. Land NUG-015 first (this ticket targets its API).

### First step
Wire one bench case — a distillation case with a mocked tool payload — and
get it passing in mock mode. Use it as the template for the rest.

### Acceptance criteria
See `backlog.md#NUG-016`. The four case families (distillation, allowlist,
depth-cap, output-routing) are required.

### Smoke test
```bash
uv run python bench/run.py --filter subagent --repeat 3
uv run pytest tests/test_subagent_e2e.py -v
```

### Estimate
Half a day to one full day. Bench-engine extension (if needed) is the swing
factor.

---

## NUG-017 · Tool docs catch-up · P1 · S

### One-line goal
`tool_docs/TOOL_SPEC.md` and `README.md` still list the original eight
tools. Add `grep_search`, `http_fetch`, `jq`, `tasks` (shipped with v0.3)
plus `spawn_agent` (this sprint).

### Where the work happens
- **Edit:** `tool_docs/TOOL_SPEC.md` (Built-in Tools, ToC)
- **Edit:** `README.md` (tools table)

### First step
Open `tool_docs/TOOL_SPEC.md`, jump to "Built-in Tools" section, drop in five
new entries following the existing format. Update the ToC. Then sync the
README tools table.

### Acceptance criteria
See `backlog.md#NUG-017`.

### Smoke test
```bash
grep -c "^### " tool_docs/TOOL_SPEC.md   # should be at least +5 vs before
grep -E "grep_search|http_fetch|jq|tasks|spawn_agent" README.md
```

### Estimate
1–2 hours. Bundle in the v0.4 release commit.

---

## What is NOT in this sprint

- **NUG-005 (Jinja template sink):** still on the bench. Pull in v0.4.1 if
  there's contributor bandwidth, otherwise v0.5.
- **NUG-004, 007, 008, 009, 011 (web UI parity):** v0.5. Don't bleed scope.
- **NUG-006, 014 (session intelligence):** v0.6. Each needs a design round
  first.
- **Skills (#13), agent configs (#12):** still design-pending. NUG-015 is
  explicitly designed not to depend on either.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Spec §8 open questions snowball during implementation | Pre-commit to recommended answers in the spec (already drafted). Treat changes from those as part of the PR description, not new design rounds. |
| Recursion depth bookkeeping interacts badly with thread-pool reuse in `nugget-server` | Use `contextvars.ContextVar` (decided; spec §5c updated). Test with two concurrent web sessions both spawning subagents. |
| Bench engine doesn't support nested-arg path constraints, expanding NUG-016 scope | If this surfaces, drop the depth-cap and allowlist cases to assertions inside `tests/test_subagent_e2e.py` and keep the bench case minimal. |
| Sprint slips past 2026-05-13 | NUG-015 alone is a respectable v0.4. NUG-016 can move to v0.4.1 if needed; NUG-017 should not slip (it's an hour). |

---

## Definition of "ready to ship"

Before opening the v0.4 release PR (`staging` → `main`):

- [ ] NUG-015, NUG-016, NUG-017 merged into `develop` and forwarded to `staging`.
- [ ] `pyproject.toml` version bumped to `0.4.0`.
- [ ] `ROADMAP.md` "Done" section updated; #14 row marked complete (or
      flagged "MVP complete; full skill integration deferred").
- [ ] `tool_docs/SUBAGENT_SPEC.md` §8 filled in with implementation
      decisions.
- [ ] `bench/run.py --filter subagent` passes ≥80% in mock mode.
- [ ] `nugget-server` smoke-tested with at least one subagent call producing
      `subagent_call` and `subagent_done` SSE events visible in the browser
      devtools.
- [ ] `CHANGELOG` (or release notes drafted in PR body) lists the three
      tickets and the bumped version.
