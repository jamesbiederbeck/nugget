# Nugget — backlog

Tickets are sorted by priority within each section. Effort: S = ≤4h, M = half day, L = 1–2 days, XL = 3+ days. Priority: P0 (must-do for next release), P1 (strongly desired), P2 (next release), P3 (nice-to-have).

The "Roadmap #" column references items in `ROADMAP.md` at repo root.

---

## v0.3 — Routing & backends · SHIPPED 2026-04 (v0.3.0)

NUG-001, NUG-002, NUG-003, NUG-010 all merged. NUG-005 (Jinja template sink)
deferred to a later release. Released as v0.3.0.

Additionally shipped (not originally ticketed, landed alongside the v0.3 line):

- **`grep_search` tool** — `subprocess` ripgrep wrapper, `shell=False`,
  `APPROVAL = "allow"`. Source: `src/nugget/tools/grep_search.py`. Tests in
  `tests/tools/test_grep_search.py`.
- **`http_fetch` tool** — `requests`-based URL fetcher. Callable approval:
  GET/HEAD = `allow`, all other methods = `ask`. Source:
  `src/nugget/tools/http_fetch.py`.
- **`jq` tool** — JMESPath query over JSON strings or `$var`-bound objects.
  `APPROVAL = "allow"`. Source: `src/nugget/tools/jq.py`.
- **`tasks` tool** — Persistent SQLite task list, mirroring `memory.py`.
  Callable approval: `delete` = `ask`, all other operations = `allow`. Source:
  `src/nugget/tools/tasks.py`. DB at `~/.local/share/nugget/tasks.db`.

Test count: **298 passing**. `tool_docs/TOOL_SPEC.md` still needs entries for
the four new tools — see NUG-019 below.

---

### NUG-001 · Implement `render_output` dispatch · P0 · M · feature · DONE
**Roadmap #:** 1

Today `src/nugget/tools/render_output.py:33` raises `NotImplementedError`. The system prompt and bench cases (`bench/cases/render_output.tsv`) already direct the model to use it.

**Acceptance criteria:**
- `render_output` looks up `tool_name` in the tool registry, calls its `execute()`, and routes the result through the existing per-call sink machinery in `_route_tool_result()`.
- `output` arg is optional; absent means `display`.
- Sink validation reuses `_validate_sink()` (same allowed forms: `display`, `display:<jmespath>`, `file:<path>`, `$var`, `$var.<jmespath>`).
- Error stubs match the existing routing error shape: `{"status": "error", "reason": "..."}`.
- Approval is checked for the *wrapped* tool, not for `render_output` itself (keep `APPROVAL = "allow"` on render_output, defer to the inner tool's gate).
- `bench/cases/render_output.tsv` runs end-to-end (no `--mock-tools`) and at least matches the pass rate it currently shows in mock mode.
- Unit tests in `tests/tools/test_render_output.py` covering: display sink, file sink (with file-sink approval), `$var` sink + later substitution, unknown wrapped tool, approval-denied wrapped tool, missing required arg.

**Files likely touched:** `src/nugget/tools/render_output.py`, `src/nugget/backends/textgen.py` (may need to expose `_route_tool_result` or refactor so render_output can call it), new `tests/tools/test_render_output.py`.

**Open question:** does `render_output` execute the wrapped tool inside the harness's tool loop (so per-call output routing on the wrapped tool's result) or does it call `tool_registry.execute()` directly and then route? The latter is simpler; the former lets the wrapped tool emit its own bindings. Recommend the latter; document the limitation.

---

### NUG-002 · Promote `Backend` Protocol to ABC · P1 · S · chore · DONE
**Roadmap #:** 2

Small refactor. The `@runtime_checkable` Protocol in `src/nugget/backends/__init__.py` has no enforced typed signature.

**Acceptance criteria:**
- `Backend` becomes an `abc.ABC` (or kept as a Protocol but with full typed signature; pick one).
- `run()` signature matches what `TextgenBackend` actually returns: `tuple[str, str | None, list[dict], str | None]`.
- `make_backend()` return type annotation is the ABC (or the Protocol), not bare `Backend`.
- Type-check pass with `mypy` or `pyright` against `src/nugget/backends/` (whichever is easiest to add as a dev-extra).
- All existing tests still pass.
- Document the contract one place (in the ABC docstring) and reference it from `CONTRIBUTING.md`.

**Files likely touched:** `src/nugget/backends/__init__.py`, `src/nugget/backends/textgen.py` (decorator only), `CONTRIBUTING.md`.

---

### NUG-003 · OpenRouter backend · P1 · M · feature · DONE
**Roadmap #:** 3

A backend that targets OpenRouter's `/v1/chat/completions` endpoint, enabling any OpenRouter-hosted model without a local inference server.

**Acceptance criteria:**
- New module `src/nugget/backends/openrouter.py` implementing the `Backend` ABC.
- Config keys: `"backend": "openrouter"`, `"openrouter_api_key"` (or env `OPENROUTER_API_KEY`), `"openrouter_model"` (e.g. `"anthropic/claude-haiku-4-5"`).
- `make_backend()` recognises `"openrouter"`.
- Tool calling: uses OpenAI-style native `tools` + `tool_calls` fields (not Gemma's text-embedded format). The tool loop runs at the chat-completions level: model returns `tool_calls`, harness executes, appends `role: tool` messages, recurses up to 16 times.
- Streaming: SSE deltas → `on_token`. Tool-call assembly across deltas (OpenAI streams tool-call args incrementally — handle the partial-JSON merge).
- Output routing (`output` meta-arg) works identically to `textgen`: same `_route_tool_result` semantics, same sink syntax. Either lift the routing logic to a shared module or import it from `textgen`.
- Thinking: OpenRouter exposes `reasoning_content` for some models — capture and surface via `on_thinking` if present.
- Tests: `tests/backends/test_openrouter.py` with `pytest-mock` mocking `requests`. Cover: simple completion, tool call → result → final text, multi-tool loop, sink routing pass-through, error handling (401, 429, network).
- `README.md` and `tool_docs/TOOL_SPEC.md` updated with the new backend table row.

**Files likely touched:** new `src/nugget/backends/openrouter.py`, `src/nugget/backends/__init__.py`, `src/nugget/config.py` (DEFAULTS for new keys), new `tests/backends/test_openrouter.py`, `README.md`, `tool_docs/TOOL_SPEC.md`.

**Out of scope:** image/multimodal inputs, OpenRouter's free-tier rate-limit handling beyond surfacing the error message.

---

### NUG-005 · Jinja template sink · P2 · M · feature
**Roadmap #:** 11

Adds an `output: "template"` sink. The model binds tool outputs to named variables, then writes its final response as a Jinja2 template that references them. The harness renders the template before display/save.

**Acceptance criteria:**
- New sink value `"template"` (or `"render"` — pick one) recognised by `_validate_sink()`.
- When the assistant turn ends with at least one binding active and `finish_reason=="stop"`, the harness treats the final text as a Jinja2 template, renders it with bindings as context, and substitutes the rendered string before `on_token` (or before saving for non-streaming).
- StrictUndefined: missing variable references raise; the model gets a clear error stub for the next turn.
- Bench case in `bench/cases/sinks.tsv`: target `tool_call[0].args.output`, constraint `regex` `^template$` for at least one prompt of the form "fetch X and tell me its title".
- Unit test in `tests/backends/test_textgen.py` covering: template render with one binding, template render with `{{ x.field }}` access, missing-variable error, no-binding turn renders as plain text.

**Files likely touched:** `src/nugget/backends/textgen.py` (`_validate_sink`, render step at end of `run()`), `src/nugget/templates/system.j2` (document the new sink), `bench/cases/sinks.tsv`, `tests/backends/test_textgen.py`, `tool_docs/TOOL_SPEC.md` (Output Routing table).

**Depends on:** NUG-001 — the `render_output` dispatch path is the natural integration point for binding-only tool calls that the model wants to template over.

---

### NUG-010 · Doc-drift cleanup · P1 · S · docs · DONE
**Roadmap #:** —

Three known mismatches between docs and code.

**Acceptance criteria:**
- `tool_docs/TOOL_SPEC.md` header `Version: 0.1.0` updated to match `pyproject.toml` (currently `0.2.1`). Decide whether to drop the version line entirely (since pyproject is authoritative) or keep it and add a CI check.
- `CONTRIBUTING.md` "Adding a backend" section: `Backend.run()` signature corrected from `(text, thinking, tool_exchanges)` to `(text, thinking, tool_exchanges, finish_reason)`.
- `tool_docs/TOOL_SPEC.md` "Writing a Custom Backend" example signature corrected (same fix).
- `README.md` tools table extended to include `wallabag`, `notify`, and `render_output` (or explicitly note that some tools require env config and are not enabled by default).
- `tool_docs/TOOL_SPEC.md` "Built-in Tools" section gains `wallabag` and `notify` entries with their schemas, env vars, and approval gates.

**Files likely touched:** `tool_docs/TOOL_SPEC.md`, `CONTRIBUTING.md`, `README.md`.

---

## v0.4 — Subagent MVP

The headline new feature requested for v0.4. Specification:
`tool_docs/SUBAGENT_SPEC.md`. The MVP is intentionally scoped to a single
self-contained tool (`spawn_agent`) and does **not** depend on agent configs
(NUG-006 etc.) or skills shipping first.

### NUG-015 · `spawn_agent` tool — subagent MVP · P0 · L · feature
**Roadmap #:** 14
**Spec:** `tool_docs/SUBAGENT_SPEC.md`

Implement the subagent primitive described in the spec: a built-in tool that
spawns a child Nugget session with a focused system prompt, an explicit
context payload (inline or via `$var` bindings), and a tool allowlist; runs
the child via the parent's `Backend.run()`; returns a result dict that flows
through the existing output-routing machinery.

**Acceptance criteria:**
- New `src/nugget/tools/spawn_agent.py` matching the SCHEMA in the spec,
  including `task`, `context`, `context_vars`, `system_prompt`, `tools`,
  `max_turns`, `return_thinking` arguments. Default `APPROVAL = "ask"`.
- New helper module `src/nugget/subagent.py` containing system-prompt
  assembly, context-rendering rules (inline string verbatim, dict→`json.dumps
  indent=2`, other→`repr`), the 32 KB byte-cap-with-sentinel truncation
  behaviour, and a `contextvars.ContextVar` recursion-depth counter (not
  `threading.local` — nugget-server reuses threads across requests).
- `context_vars` are resolved against the current turn's `bindings` dict
  (the same one `_routing.py` exposes for sink/`$var` handling). Unbound
  names → tool returns `{"error": "$<name> not bound"}` without spawning.
- The child shares the parent's `Backend` instance (per spec §8.1); a fresh
  `Session` is constructed in-memory.
- Tool allowlist defaults to **empty** (pure-reasoning subagent). When
  non-empty, the child's tool registry is filtered to those names *before*
  approval evaluation. Approval rules from `config.json` apply unchanged
  inside the child.
- Recursion depth capped at `subagent.max_depth` (default 2); depth limit
  exceeded → `{"_denied": true, "reason": "subagent depth limit exceeded"}`.
- Per-call subagent transcripts persisted to
  `~/.local/share/nugget/sessions/<parent_id>/subagents/<call_id>.json`. Not
  surfaced by `Session.list_sessions()`. Add `Session.load_subagents(parent_id)`
  helper.
- `Config.DEFAULTS` gains the `subagent` block from spec §6.
- Result dict from `execute()` is routable: default inline; `output:
  "display"` shows just the `answer`; `output: "$x"` binds the whole dict;
  `output: "display:answer"` JMESPath-extracts.
- Web server emits `subagent_call` and `subagent_done` SSE events (spec §3d).
  Inner-stream events suppressed in v0 (`subagent.stream_inner: false`
  default).
- Unit tests in `tests/tools/test_spawn_agent.py` covering: pure-reasoning
  spawn (no tools), spawn with tool allowlist + tool exchange, recursion
  depth cap, unbound `context_var`, oversized context truncation, persistence
  to per-call JSON file, output routing pass-through (`$var`, `display`,
  `display:answer`).
- Config merge: absent `subagent` block in user `config.json` is filled from
  `Config.DEFAULTS` on load (existing merge pattern — no special handling
  needed).
- Persistence: `~/.local/share/nugget/sessions/<parent_id>/subagents/` is a
  subdirectory; `Session.list_sessions()` globs top-level `*.json` only and
  is unaffected.

**Files likely touched:** new `src/nugget/tools/spawn_agent.py`, new
`src/nugget/subagent.py`, `src/nugget/config.py`, `src/nugget/session.py`,
`src/nugget/server.py` (SSE events + types), `src/nugget/backends/_routing.py`
(only if context-var resolution needs harness coupling), `tool_docs/TOOL_SPEC.md`
(new tool entry), `tool_docs/SUBAGENT_SPEC.md` (decisions captured), new
`tests/tools/test_spawn_agent.py`, new `tests/test_subagent.py`.

**Out of scope:** parallel sibling spawning, skill-bundle integration
(`skill: <name>` arg semantics — defer until skills exist), inner-token
streaming.

**Estimate:** 1–2 days. The recursion guard, context-binding resolution, and
per-call persistence each have a couple of edge cases worth isolating.

---

### NUG-016 · Subagent bench tests · P1 · M · test
**Roadmap #:** 14
**Spec:** `tool_docs/SUBAGENT_SPEC.md`
**Depends on:** NUG-015

Once `spawn_agent` lands, exercise it end-to-end through the bench harness so
regressions in subagent behaviour show up in the same compliance dashboard as
the rest of the prompt-following work.

**Acceptance criteria:**
- New `bench/cases/subagent.tsv` with at least the following case families:
  - **distillation:** parent receives a large mocked tool payload, binds it
    to `$matches`, calls `spawn_agent` with `context_vars=["matches"]`, and
    the bench asserts `tool_call[N].name == "spawn_agent"` and that
    `tool_call[N].args.context_vars` contains `"matches"`.
  - **tool allowlist respected:** bench prompt instructs the parent to spawn
    a subagent with `tools=["calculator"]`. Constraint: the recorded child
    tool exchange list contains only `calculator` calls (or none).
  - **depth cap honoured:** crafted system prompt encourages a deep recursion;
    bench asserts the harness denies past `max_depth` and the parent recovers
    (no traceback, finish_reason in {`stop`, `tool_calls`}).
  - **output routing pass-through:** parent uses `output: "$child"` and a
    follow-up tool call references `$child.answer`. Assert the substitution
    happened.
- Integration tests in `tests/test_subagent_e2e.py` (separate from unit tests)
  drive the full parent→child→answer loop using `pytest-mock` to stub the
  upstream completions endpoint with canned responses (no live model
  required for CI). Cover: happy-path single-shot, child uses one tool,
  child hits its `max_turns` cap, child's `_denied` propagates back.
- A bench fixture mock-tool (`mock_grep`) producing a deterministic large
  payload is added under `bench/fixtures/` so distillation cases are
  reproducible without the real `grep_search` tool's environment dependence.
- Bench DB schema is unchanged; results land in the existing `case_runs`
  table tagged with the new case IDs.
- `bench/erd.md` and `bench/README.md` updated with a one-paragraph note that
  subagent cases are present and how their constraints differ (they assert
  on nested `tool_call.args.context_vars` and on child-side tool sequences,
  which existing bench cases do not).
- `uv run python bench/run.py --filter subagent --repeat 3` passes
  end-to-end against the mock upstream; pass rate ≥ 80%.

**Files likely touched:** new `bench/cases/subagent.tsv`, new
`bench/fixtures/mock_grep.py` (or extend an existing fixtures module), new
`tests/test_subagent_e2e.py`, `bench/run.py` (only if a new constraint type
is needed for nested-arg assertions), `bench/erd.md`, `bench/README.md`.

**Out of scope:** running cases against a live OpenRouter or
text-generation-webui backend in CI. Mock-mode is sufficient for v0.4.

**Estimate:** Half a day to a full day, contingent on whether the bench
constraint engine already supports nested-arg path assertions
(`tool_call[0].args.context_vars[0]`). If not, an extension to `bench/run.py`
is part of this ticket.

---

### NUG-017 · Tool docs catch-up for new tools · P1 · S · docs
**Roadmap #:** —

Four new tools shipped alongside v0.3 (`grep_search`, `http_fetch`, `jq`,
`tasks`) but `tool_docs/TOOL_SPEC.md` and `README.md` still list only the
original eight. Bring the docs back into agreement with the source.

**Acceptance criteria:**
- `tool_docs/TOOL_SPEC.md` "Built-in Tools" gains entries for `grep_search`,
  `http_fetch`, `jq`, and `tasks`, each with: schema, example
  input/output, approval-gate description (callable gates spelled out), and
  any environment / disk-state side effects (`tasks` writes
  `~/.local/share/nugget/tasks.db`).
- `README.md` tools table includes the four new tools (one line each).
- `tool_docs/TOOL_SPEC.md` Table of Contents updated.
- The "Approval Rules" → "Tool gate in a module" example mentions the
  callable form used by `http_fetch` and `tasks` as a pattern.
- `tool_docs/TOOL_SPEC.md` SSE Output Events table gains `subagent_call` and
  `subagent_done` entries (fields per spec §3d).

**Files likely touched:** `tool_docs/TOOL_SPEC.md`, `README.md`.

**Estimate:** 1–2 hours.

---

## v0.5 — Config profiles

The headline new feature for v0.5. Design notes: `planning/profiles.md`.

Lets users define named configuration overlays in `config.json` and activate
one via a single CLI flag (`--profile <name>`). Profiles are also reusable as
subagent personas — either explicitly via `spawn_agent`'s `profile` arg, or
via a default declared in the `subagent` block. No new files, no
registration; profile bodies live entirely in `config.json`.

### NUG-018 · Profile resolution in `Config` · P0 · M · feature
**Roadmap #:** —
**Design:** `planning/profiles.md`

Teach `Config` about a new top-level `profiles` key and a profile-selection
step in its load pipeline. This is the foundation every other ticket in the
v0.5 line builds on.

**Acceptance criteria:**
- `Config.__init__` accepts a new optional `profile: str | None` argument.
  When set, the named profile is looked up in the loaded `profiles` block
  and its keys are merged on top of the base config, before the
  `overrides` dict is applied.
- Resolution order, later layers winning: `DEFAULTS` → `config.json` base →
  selected profile → `overrides` (CLI flags). Matches `planning/profiles.md`.
- Nested objects (`approval`, `subagent`) are **whole-block replacement**,
  not deep merge — if a profile sets `approval`, that block fully replaces
  the base `approval`.
- The `profiles` key is **stripped** from the resolved `_data` dict so it
  never reaches runtime consumers; it remains accessible via a new
  `Config.list_profiles() -> list[str]` helper for error messages and
  introspection.
- An unknown profile name raises a new `UnknownProfileError` exception
  carrying the requested name and the list of available names. The CLI
  formats this as a hard error: `unknown profile 'foo'. Available: bar, baz`.
- `Config.DEFAULTS` gains an empty `"profiles": {}` entry so the schema is
  documented even on first-run configs.
- `Config` exposes `Config.active_profile: str | None` (the name selected at
  construction time, or `None`).
- Tests in `tests/test_config.py` covering: no-profile load (no behaviour
  change), profile that overrides scalar keys, profile that fully replaces
  `approval`, profile that fully replaces `subagent`, unknown profile name
  raises, `profiles` key absent from resolved `_data`,
  `list_profiles()` ordering deterministic.

**Files likely touched:** `src/nugget/config.py`, `tests/test_config.py`.

**Out of scope:** CLI plumbing (NUG-019), tool-list keys (NUG-020),
subagent integration (NUG-021), docs (NUG-022).

**Estimate:** Half a day. Merge logic is small; the test matrix is the bulk
of the work.

---

### NUG-019 · `--profile` CLI flag (nugget + nugget-server) · P0 · S · feature
**Roadmap #:** —
**Design:** `planning/profiles.md`
**Depends on:** NUG-018

Wire the new `Config(profile=...)` argument into both entry points.

**Acceptance criteria:**
- `nugget --profile <name> [MESSAGE]` selects a profile for the run. Both
  invocations of `Config(...)` in `src/nugget/__main__.py` (the initial
  `ensure_default()` followed by the `Config(overrides)` rebuild) thread
  the same `profile` value.
- `nugget-server --profile <name>` selects a profile for the server's
  default `Config` used to construct the backend and resolve approvals.
- An unknown profile name exits non-zero before any backend connection is
  attempted, with the error message defined in NUG-018.
- `nugget --list-profiles` prints the names from
  `Config.list_profiles()` one per line and exits 0. Empty list prints
  nothing and exits 0.
- The active profile name is shown in the CLI session header (when
  attached to a TTY) — one extra line: `profile: <name>`. Hidden when no
  profile is active.
- Tests in `tests/test_main.py` (or extend the existing CLI tests) covering:
  `--profile` argument parsing, unknown-name exit, `--list-profiles` output.
- `tests/test_server.py` (existing or new) covering `--profile` plumbing
  through to the resolved `Config` used by the server.

**Files likely touched:** `src/nugget/__main__.py`, `src/nugget/server.py`,
`tests/test_main.py`, `tests/test_server.py`.

**Out of scope:** persisting last-used profile across sessions; per-session
profile overrides at runtime via a `/profile` slash command (could be a
follow-up, not in v0.5).

**Estimate:** 2–3 hours.

---

### NUG-020 · `include_tools` / `exclude_tools` config keys · P1 · S · feature
**Roadmap #:** —
**Design:** `planning/profiles.md`
**Depends on:** NUG-018

Today the tool allowlist/denylist exists only as CLI flags
(`--include-tools` / `--exclude-tools`). Profiles need the same expressive
power as static config keys.

**Acceptance criteria:**
- Two new top-level config keys recognised by `Config.DEFAULTS`:
  `"include_tools": null` and `"exclude_tools": null` (both `null` by
  default — no filtering).
- Validation: `include_tools` and `exclude_tools` cannot both be set
  simultaneously (whether in base config, profile, or via CLI). A combined
  setting raises a clear error at config-resolution time.
- Resolution precedence (CLI flags still win): if `args.include_tools` or
  `args.exclude_tools` are passed, they fully replace any config-level
  values. Otherwise the resolved `Config` values feed
  `tool_registry.schemas(include=..., exclude=...)`.
- `src/nugget/__main__.py` and `src/nugget/server.py` both consult the
  resolved `Config` values when no explicit CLI flags are supplied.
- `tool_registry.schemas()` semantics are unchanged — this ticket only
  changes the call sites.
- Tests covering: profile sets `include_tools`, profile sets
  `exclude_tools`, conflict error, CLI flag overrides config, base config
  (no profile) honours the keys.

**Files likely touched:** `src/nugget/config.py`, `src/nugget/__main__.py`,
`src/nugget/server.py`, `tests/test_config.py`, `tests/test_main.py`.

**Out of scope:** introducing wildcard or glob matching for tool names.

**Estimate:** 3–4 hours.

---

### NUG-021 · Subagent profile integration · P1 · M · feature
**Roadmap #:** —
**Design:** `planning/profiles.md`
**Depends on:** NUG-018, NUG-020

`spawn_agent` becomes profile-aware. The child resolves its config from
`DEFAULTS → config.json base → profile (explicit arg, else
subagent.default_profile, else no overlay)`. The parent's active profile
does **not** bleed into the child — profile resolution for the child is
independent.

**Acceptance criteria:**
- `spawn_agent` SCHEMA gains an optional `profile` arg (string). Description:
  "Name of a config profile to apply to the child session. Falls back to
  `subagent.default_profile`. Unknown name → hard error."
- `Config.DEFAULTS["subagent"]` gains `"default_profile": null`.
- In `tools/spawn_agent.py:execute()`, the child config is built by calling
  `Config(profile=resolved_name)` where `resolved_name` is, in order:
  the explicit `profile` arg, else `subagent.default_profile`, else `None`.
- Child config resolution starts from `DEFAULTS + config.json base`, NOT
  from the parent's resolved config. The parent's active profile is
  ignored. (This requires the child to load `config.json` fresh; the
  parent's `Config` instance is available but only consulted for the
  `subagent` block to read `default_profile` — capture this read up front
  in a small helper to keep the code obvious.)
- An unknown profile name (in the arg or in `subagent.default_profile`)
  returns `{"error": "unknown profile '<name>'. Available: ..."}` without
  spawning. The recursion-depth guard runs *before* profile resolution so
  depth-limit errors take precedence.
- The child's tool allowlist resolution honours the child profile's
  `include_tools` / `exclude_tools` if the explicit `tools` arg to
  `spawn_agent` is absent. If both the explicit `tools` arg and a profile
  `include_tools`/`exclude_tools` are present, the explicit `tools` arg
  wins (matches CLI precedence in NUG-020).
- The per-call subagent transcript JSON gains a `"profile": <name|null>`
  field so post-hoc inspection can tell which profile ran.
- Tests in `tests/tools/test_spawn_agent.py` covering: explicit `profile`
  arg, fallback to `subagent.default_profile`, unknown profile (both
  paths) returns error dict, parent active profile does NOT propagate to
  child, child profile's `include_tools` honoured when no `tools` arg.

**Files likely touched:** `src/nugget/tools/spawn_agent.py`,
`src/nugget/subagent.py` (only if helper extraction makes sense),
`src/nugget/config.py` (DEFAULTS update),
`tests/tools/test_spawn_agent.py`.

**Out of scope:** profile changes mid-session; nested-profile inheritance
across multiple spawn levels; surfacing the active child profile in
`subagent_call` SSE events (could fall out of NUG-022 docs review).

**Estimate:** Half a day. The extra wiring is small; the "parent profile
doesn't bleed" semantics need a focused test.

---

### NUG-022 · Profile docs and changelog · P1 · S · docs
**Roadmap #:** —
**Design:** `planning/profiles.md`
**Depends on:** NUG-018, NUG-019, NUG-020, NUG-021

Bring `tool_docs/CONFIG.md`, `README.md`, `tool_docs/TOOL_SPEC.md`, and
`CHANGELOG.md` (or release notes in PR body if no changelog file yet) up
to date with the new keys, flags, and `spawn_agent` arg.

**Acceptance criteria:**
- `tool_docs/CONFIG.md` JSON Schema block extends with: `profiles`,
  `include_tools`, `exclude_tools`, `subagent.default_profile`.
- `tool_docs/CONFIG.md` gains a new "Profiles" section with: a worked
  example mirroring `planning/profiles.md`, the merge semantics (whole-
  block replacement for nested objects), and the
  `--profile` / `--list-profiles` CLI usage.
- `README.md` "Configuration" or top-level usage section gains a 4–6 line
  example: define one profile, run `nugget --profile <name>`.
- `tool_docs/TOOL_SPEC.md` `spawn_agent` entry documents the new `profile`
  arg and links to `tool_docs/CONFIG.md` Profiles section.
- `CHANGELOG.md` (create if missing) gets a `## v0.5.0` section listing
  NUG-018..022.
- `pyproject.toml` version bumped to `0.5.0` as part of this ticket's PR
  (the release commit lands here).
- `ROADMAP.md` gains a "Done" entry for v0.5 — Config profiles.

**Files likely touched:** `tool_docs/CONFIG.md`, `README.md`,
`tool_docs/TOOL_SPEC.md`, `CHANGELOG.md`, `pyproject.toml`, `ROADMAP.md`.

**Estimate:** 2–3 hours.

---

## v0.6 — Web UI parity

### NUG-004 · Tool approvals in web UI · P1 · L · feature
**Roadmap #:** 7

Today `_web_approval_config()` (`server.py:64`) silently downgrades all `ask` rules to `allow` because there's no TTY. This means the user has no way to gate `shell` calls in web mode.

**Acceptance criteria:**
- New SSE event type `tool_approval_request` with `name`, `args`, `request_id` fields.
- New endpoint `POST /api/sessions/{session_id}/approve` accepting `{request_id, approved: bool}`.
- Backend thread blocks on a `concurrent.futures.Future` keyed by `request_id` until the response arrives or a timeout (default 60s, configurable) elapses; on timeout, deny.
- Frontend renders a modal on `tool_approval_request` showing tool name and args; user clicks Approve/Deny → POSTs to `/approve`.
- `_web_approval_config()` no longer mutates `ask` to `allow` when this code path is wired; it only does the downgrade if no client is registered for the session (single-user fallback).
- Multiple concurrent approval requests within one turn are queued, not interleaved.
- Tests: `tests/test_server.py` (new file) covering happy path approve, deny, timeout, and that the `tool_executor` returns the right `_denied` shape on timeout/deny.

**Files likely touched:** `src/nugget/server.py`, `src/nugget/web/app.js`, `src/nugget/web/index.html` (modal markup), `src/nugget/web/style.css`, new `tests/test_server.py`.

**Open question:** how to associate an approval request with a specific connected client when multiple browsers have the same session open? Suggest: route approvals via the SSE response and accept the *first* `/approve` POST for a `request_id`.

---

### NUG-007 · Status bar (CLI + web) · P2 · L · feature
**Roadmap #:** 8

A persistent status line in both CLI (`rich.live`) and web (footer bar). Fields: session ID, session title (when present), backend name, session token total, thinking-token total, tokens/sec.

**Acceptance criteria:**
- CLI: `rich` added as a hard dependency. `rich.live.Live` wraps the prompt loop. Status bar updates after each turn without disturbing the streamed response.
- Web: a footer `<div id="status-bar">` populated from new SSE event `status` (emitted at end of each turn) carrying the same fields.
- Backend (`textgen.py`) reports per-call usage: prompt tokens, completion tokens, thinking tokens, elapsed seconds. text-generation-webui's `/v1/completions` returns a `usage` block in non-streaming mode; for streaming, sum from the final chunk's `usage` if present (else estimate from char count).
- `Session` gets a `title: str | None` field (default `None`); status bar reads it. NUG-006 will populate it.
- Status bar is hideable via `--no-status` CLI flag and a config key `show_status_bar: true`.
- Tests: backend usage parsing covered; status-bar rendering smoke-tested with a captured Console.

**Files likely touched:** `src/nugget/__main__.py`, new `src/nugget/status.py`, `src/nugget/backends/textgen.py`, `src/nugget/server.py`, `src/nugget/web/index.html`, `src/nugget/web/app.js`, `src/nugget/web/style.css`, `src/nugget/session.py`, `pyproject.toml`.

**Depends on:** none strictly, but NUG-006 (titles) ships the missing data point.

---

### NUG-008 · Streaming thinking blocks in web UI · P2 · S · feature
**Roadmap #:** 9

The server already emits `thinking` SSE events (`server.py:146`). The frontend doesn't render them.

**Acceptance criteria:**
- `app.js` handles the `thinking` event type and renders content into a collapsed-by-default `<details>` element above the assistant message.
- Toggle on the existing `view-toggles` row (`thinking` button at `index.html:27`) shows/hides thinking blocks (already wired for layout — needs JS).
- Thinking text accumulates across multiple `thinking` events for the same turn.
- Visual treatment matches CLI: dim text, distinct from assistant content.
- Manual test plan documented in PR (no Selenium; this is UI).

**Files likely touched:** `src/nugget/web/app.js`, `src/nugget/web/style.css`.

---

### NUG-009 · Tool toggles in web UI · P2 · M · feature
**Roadmap #:** 10

Per-tool enable/disable controls. Requires a `tools.disabled` config key first (currently doesn't exist anywhere).

**Acceptance criteria:**
- `Config.DEFAULTS` gains `"tools": {"disabled": []}` (or flat `"tools_disabled": []` — pick the nested form for future-proofing).
- `tool_registry.schemas()` (or its callers) honour the disabled list when no explicit `include`/`exclude` arg is passed.
- CLI: `tool_registry.schemas()` call in `__main__.py` already supports include/exclude — wire it to fall back to `cfg.get("tools", {}).get("disabled", [])` when neither flag is provided.
- Server: `server.py:134` updated to pass the same exclude list.
- Web frontend: a sidebar tools panel listing all tools with a toggle each. Toggles persist to the server via new `GET/PUT /api/config/tools` endpoints. Endpoint reads/writes only the `tools.disabled` key, not the whole config.
- Schema for the API documented in `tool_docs/TOOL_SPEC.md`.
- Tests: `tests/test_config.py` extended; new `tests/test_server.py` (or add to it) covering the GET/PUT roundtrip.

**Files likely touched:** `src/nugget/config.py`, `src/nugget/__main__.py`, `src/nugget/server.py`, `src/nugget/web/app.js`, `src/nugget/web/index.html`, `src/nugget/web/style.css`, `src/nugget/tools/__init__.py` (maybe), `tests/test_config.py`, `tests/test_server.py`.

---

### NUG-011 · Align session-list response with TOOL_SPEC.md · P3 · S · chore
**Roadmap #:** —

`Session.list_sessions()` returns `id/updated_at/turns/preview`. `tool_docs/TOOL_SPEC.md:188` documents `id/created_at/updated_at`. Frontend uses the implementation. Pick one and align the other.

**Acceptance criteria:**
- Decide: extend the Session helper to also include `created_at`, or update the docs to match the helper, or both.
- All four tools that read this output (CLI list, web sidebar, server endpoint, docs) agree on shape.
- Test in `tests/test_session.py` asserting the documented fields are present.

**Files likely touched:** `src/nugget/session.py`, `tool_docs/TOOL_SPEC.md`, `tests/test_session.py`.

---

## v0.7 — Session intelligence

### NUG-006 · Session-title computation · P2 · L · feature
**Roadmap #:** 5 (and the minimum-viable subset of #4)

Auto-compute a ≤5-word topic title for each session on the first user message. Stored in the session JSON as `"title"`. Displayed in `--list-sessions`, the web sidebar, and the status bar.

**Acceptance criteria:**
- Hook scaffolding minimum viable: an `on_message` event fires only on `message_index == 0`, runs a configured shell command (or an internal Python callable), receives the message text on stdin/as arg, and writes the result back into `session.title`.
- Built-in default: when no `on_message` hook is configured but `auto_title: true` (new config key, default `true`), a lightweight backend call with a fixed prompt produces the title in a daemon thread.
- The title call uses the same backend with `max_tokens=20` and a separate fast system prompt; failure is non-blocking.
- Once set, `session.title` is included in `/api/sessions` and `Session.list_sessions()`.
- Web sidebar shows title (falls back to first-user-message preview).
- CLI `--list-sessions` shows title in a new column.
- Tests: `tests/test_session.py` extension covering serialise/deserialise of `title`; `tests/backends/test_textgen.py` for the title-call helper (mocked).

**Files likely touched:** `src/nugget/session.py`, `src/nugget/__main__.py`, `src/nugget/server.py`, new `src/nugget/hooks.py` (minimal — only `on_message` for now), `src/nugget/config.py`, `tests/test_session.py`, web frontend.

**Out of scope:** the rest of the hooks framework (`pre_tool`, `post_tool`, `on_file_change`, `on_git`, etc.). NUG-006 ships *only* what's needed for titles.

---

### NUG-014 · Semantic search over memory and sessions · P3 · XL · feature
**Roadmap #:** 15

Vector index over `memory.db` rows and session message bodies. Surfaced as a new `recall_semantic` tool and CLI flag.

**Acceptance criteria:**
- Embeddings: prefer using the upstream backend's `/v1/embeddings` (text-generation-webui supports it). Configurable model name; default `all-MiniLM-L6-v2` (matches the small footprint).
- Storage: `sqlite-vec` extension if available, else FAISS-on-disk (`~/.local/share/nugget/vec_index/`). Indexed on first use; incremental updates on memory.store and on session save.
- New `memory(operation="search_semantic", query, top_k)` operation OR a new tool `recall` (whichever fits the registry better — discuss in PR).
- CLI command `/search <query>` does a semantic search across both memory and sessions, prints ranked results.
- Tests with deterministic fake embeddings (a `monkeypatch` over the embed call returning fixed vectors).

**Files likely touched:** `src/nugget/tools/memory.py` or new `src/nugget/tools/semantic.py`, `src/nugget/session.py` (hook into `save()`), new `src/nugget/embeddings.py`, `src/nugget/commands.py`, new `tests/test_semantic.py`, `pyproject.toml` (new optional extra `[semantic]`).

---

## Bench enhancements (parallel track)

### NUG-012 · Bench: prompt-variant sweeping · P3 · M · feature
**Roadmap #:** 16

Run the case matrix against multiple `.j2` prompt variants and compare pass rates per case in the bench DB.

**Acceptance criteria:**
- `bench/run.py --system-prompt <path>` flag accepts a Jinja2 template path; rendered template replaces the default `system.j2` for that run.
- Multi-variant invocation: `--system-prompt a.j2 b.j2 c.j2` runs each variant and tags results with the prompt hash.
- New report command (`bench/run.py --compare-prompts`) emits a markdown table: rows = case IDs, columns = prompts, cells = pass count over total.
- Cell colour-codes (or asterisks): red for ≤50%, yellow for 50–80%, green for >80%.
- `bench/erd.md` updated.

**Files likely touched:** `bench/run.py`, `bench/db.py`, `bench/erd.md`, possibly new `bench/prompts/` directory with variant `.j2` files committed as examples.

---

### NUG-013 · Bench: flakiness report · P3 · S · feature
**Roadmap #:** 17

Query the bench DB for cases with mixed pass/fail across `--repeat` runs and surface as a stability table.

**Acceptance criteria:**
- New flag `bench/run.py --stability-report` (no run, just report).
- Markdown output: case ID, total runs, pass count, fail count, pass rate, "stable"/"flaky"/"broken" label.
- Default cutoff: <80% and >20% pass rate = flaky; ≥80% = stable; ≤20% = broken. Configurable via `--flaky-threshold`.
- Optional `--since <timestamp>` to scope to recent runs.

**Files likely touched:** `bench/run.py`, `bench/db.py`.

---

## Design-pending (not ticketed yet)

These items are in `ROADMAP.md` but should not be turned into tickets until each has at least a one-page design note in `tool_docs/`:

- **#4 — Hooks framework (full)** — beyond the on-message hook needed for NUG-006
- **#6 — MCP support**
- **#12 — Agent configs**
- **#13 — Skill support**
- **#14 — Subagent framework**

See `roadmap.md` for the rationale and what each design note needs to cover.
