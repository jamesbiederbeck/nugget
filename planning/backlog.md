# Nugget — backlog

Tickets are sorted by priority within each section. Effort: S = ≤4h, M = half day, L = 1–2 days, XL = 3+ days. Priority: P0 (must-do for next release), P1 (strongly desired), P2 (next release), P3 (nice-to-have).

The "Roadmap #" column references items in `ROADMAP.md` at repo root.

---

## v0.3 — Routing & backends

### NUG-001 · Implement `render_output` dispatch · P0 · M · feature
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

### NUG-002 · Promote `Backend` Protocol to ABC · P1 · S · chore
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

### NUG-003 · OpenRouter backend · P1 · M · feature
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

### NUG-010 · Doc-drift cleanup · P1 · S · docs
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

## v0.4 — Web UI parity

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

## v0.5 — Session intelligence

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
