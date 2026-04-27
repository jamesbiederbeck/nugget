# Nugget — next sprint

**Window:** ~2026-05-10 → ~2026-05-24 (two weeks)
**Target release:** v0.4 (`Web UI parity`)
**Working branch convention:** `develop` first → PR to `staging` → PR to `main` (per `CLAUDE.md`).
**Previous sprint:** see [`sprint-v0.3.md`](sprint-v0.3.md) for the v0.3 doc (NUG-001, 002, 003, 010).

This file picks the four highest-priority tickets from `backlog.md` that are
ready to start once v0.3 merges, and adds enough scaffolding (file pointers,
first-step hints, smoke-test recipes) that a contributor can open the file,
read down once, and start typing.

The tickets are ordered to minimise blocking. NUG-008 is the smallest and
can land independently while everything else is in flight. NUG-011 is a tiny
chore that unlocks a clean API surface before the bigger tickets touch the
session endpoint. NUG-009 needs its config key before the UI can toggle tools.
NUG-004 is the keystone for v0.4 and should be the last to open review — it
spans backend, SSE, and frontend.

---

## Sprint goal

Bring the web frontend up to CLI feature parity: thinking blocks visible,
tools toggleable, and tool approvals round-tripping instead of silently
promoting `ask` to `allow`.

**Definition of done for the sprint:**
- Thinking content emitted by the model appears in the web UI as a
  collapsible `<details>` block above the assistant message.
- The web sidebar includes a tool-toggles panel; toggling a tool persists
  to config and the next request honours it.
- `POST /api/sessions/{id}/chat` no longer silently promotes `ask` approval
  rules to `allow`; instead it emits a `tool_approval_request` SSE event
  and waits for the client to POST `/approve`.
- `Session.list_sessions()` shape agrees with `TOOL_SPEC.md` (and both are
  tested).
- All existing tests still pass; net test count grows by ≥ 10 (NUG-004
  approve/deny/timeout matrix; NUG-009 config roundtrip; NUG-011 list
  shape assertion).
- `pyproject.toml` bumped to `0.4.0` on `main`; release pipeline produces
  `ghcr.io/<owner>/nugget:0.4.0` and `:latest`.

---

## Pick order

| Order | Ticket  | Why now |
|-------|---------|---------|
| 1     | NUG-008 | Smallest ticket. Server already emits `thinking` SSE events — this is pure frontend. Easy win on day one. |
| 2     | NUG-011 | Two-file chore. Cleans the session-list API shape before NUG-004 adds an approval endpoint that touches the same server file. |
| 3     | NUG-009 | Medium. The `tools.disabled` config key is entirely self-contained; the web sidebar depends on it. Start after NUG-011 is in review. |
| 4     | NUG-004 | Largest ticket. Spans backend thread, SSE protocol, and frontend modal. Land last so the SSE event vocabulary from NUG-008 is already settled. |

NUG-007 (status bar, CLI + web) is also v0.4 but is sized L and has a soft
dependency on NUG-006 (session titles) for the title field in the status bar.
Pull it into the sprint if NUG-004 lands early; otherwise it leads the next
sprint.

NUG-015 (filebrowser multi-path `cat`) is a self-contained "any contributor
with a free afternoon" ticket — pick it up in parallel with anything above.

---

## NUG-008 · Streaming thinking blocks in web UI · P2 · S

### One-line goal
Render `thinking` SSE events that the server already emits into a
collapsible block above the assistant message in the web frontend.

### Where the work happens
- **Edit:** `src/nugget/web/app.js` — handle the `thinking` event type,
  accumulate text across events for the same turn, insert into the DOM.
- **Edit:** `src/nugget/web/style.css` — visual treatment matching CLI:
  dim text, visually distinct from assistant content.

### Pre-flight
Read `src/nugget/server.py` lines 140–160 to confirm the SSE event shape
(`event: thinking\ndata: {"content": "..."}`) and which field carries the
text. Then read `src/nugget/web/app.js` to find where `token` events are
handled — that's your template for the `thinking` case.

### First step
1. In `app.js`, add a `thinking` case to the SSE event switch (or `if`
   chain). On the first `thinking` event for a turn, create a `<details>`
   element with a `<summary>Thinking</summary>` and a `<pre>` for the
   content; append it before the assistant message `<div>`.
2. On subsequent `thinking` events in the same turn, append to the `<pre>`
   (accumulate — don't replace).
3. The existing "thinking" toggle button at `index.html:27` already has a
   CSS class wired for show/hide. Verify the toggle JS works with the new
   `<details>` element (or wire it up if it isn't).
4. Style: `opacity: 0.55`, monospace font, `border-left: 2px solid
   var(--accent)` — match the CLI's dim-text treatment without clashing
   with the existing assistant-message style.

### Acceptance criteria (copy from `backlog.md#NUG-008`)
- `app.js` handles the `thinking` event type and renders content into a
  collapsed-by-default `<details>` element above the assistant message.
- Toggle on the existing `view-toggles` row (`thinking` button at
  `index.html:27`) shows/hides thinking blocks.
- Thinking text accumulates across multiple `thinking` events for the same
  turn (no flash/replace).
- Visual treatment matches CLI: dim, distinct from assistant content.
- Manual test plan documented in PR (no Selenium).

### Smoke test
Start `nugget-server`, open `http://localhost:8000`, send a prompt to a
model with thinking enabled. Confirm:
```
- The "Thinking" toggle in the toolbar toggles visibility of the block.
- The block appears collapsed by default.
- Content accumulates correctly (no truncation, no duplication).
```

### Estimate
Two to three hours. All the data is already flowing — this is a DOM-wiring
exercise.

---

## NUG-011 · Align session-list response with TOOL_SPEC.md · P3 · S

### One-line goal
`Session.list_sessions()` and `TOOL_SPEC.md` disagree on the shape of
`/api/sessions`. Decide on one canonical shape and align everything to it.

### Where the work happens
- **Edit:** `src/nugget/session.py` — `list_sessions()` return value.
- **Edit:** `tool_docs/TOOL_SPEC.md` — `/api/sessions` response table.
- **Edit:** `tests/test_session.py` — assert the documented fields.

### First step
Read `tool_docs/TOOL_SPEC.md` lines 188–196 (documents `id/created_at/
updated_at`) and `src/nugget/session.py` `list_sessions()` (returns
`id/updated_at/turns/preview`). Then read `src/nugget/web/app.js` — the
frontend uses `s.turns` and `s.preview`, so the implementation shape is
what's actually used. **Recommendation:** extend `list_sessions()` to also
return `created_at` (read the file `mtime` on creation, or store it in the
JSON header — see session `__init__`), and update TOOL_SPEC to document
all four fields. That way neither the frontend nor the spec loses data.

### Acceptance criteria (copy from `backlog.md#NUG-011`)
- Decide: extend `list_sessions()` to include `created_at`, or update docs
  to match the implementation. Either is fine; pick one.
- All four consumers (CLI list, web sidebar, server endpoint, docs) agree
  on the final shape.
- `tests/test_session.py` has at least one assertion that all documented
  fields are present in a `list_sessions()` result.

### Smoke test
```bash
uv run pytest tests/test_session.py -v
grep -n "created_at\|updated_at\|turns\|preview" tool_docs/TOOL_SPEC.md src/nugget/session.py
```
All grep hits should be consistent.

### Estimate
One to two hours including the test.

---

## NUG-009 · Tool toggles in web UI · P2 · M

### One-line goal
Let users enable/disable individual tools from the web sidebar; toggles
persist to config and are honoured on every subsequent request.

### Where the work happens
- **Edit:** `src/nugget/config.py` — add `"tools": {"disabled": []}` to
  `DEFAULTS`.
- **Edit:** `src/nugget/__main__.py` — fall back to `cfg.get("tools",
  {}).get("disabled", [])` when `--exclude-tools` is not given.
- **Edit:** `src/nugget/server.py` — pass the `disabled` list to
  `tool_registry.schemas()` at line 134; add `GET /api/config/tools` and
  `PUT /api/config/tools` endpoints.
- **Edit:** `src/nugget/web/app.js`, `src/nugget/web/index.html`,
  `src/nugget/web/style.css` — sidebar tools panel.
- **Edit:** `tool_docs/TOOL_SPEC.md` — new API endpoint documentation.
- **Edit/Add:** `tests/test_config.py`, `tests/test_server.py` — GET/PUT
  roundtrip.

### First step
Start with the config key: add `"tools": {"disabled": []}` to `DEFAULTS`
in `config.py`, update `test_config.py` to assert it's present, run the
suite. That's one green commit with no behaviour change. Then wire the CLI
and server to read it before touching the frontend.

### Acceptance criteria (copy from `backlog.md#NUG-009`)
- `Config.DEFAULTS` gains `"tools": {"disabled": []}`.
- `tool_registry.schemas()` call in `__main__.py` passes `exclude` derived
  from the config key when no `--exclude-tools` flag is given.
- `server.py` line 134 updated to pass the same exclude list.
- New `GET /api/config/tools` returns `{"disabled": [...]}`.
- New `PUT /api/config/tools` with body `{"disabled": [...]}` writes *only*
  the `tools.disabled` key and returns the updated value.
- Web sidebar tools panel lists all tools; each has a toggle; toggling
  POSTs to PUT and takes effect on the next request.
- Schema documented in `tool_docs/TOOL_SPEC.md`.
- Tests cover config roundtrip and GET/PUT endpoints.

### Open question to settle in PR
Does `GET /api/config/tools` return the *static* schema list plus a
`disabled` overlay, or does the server expose two separate endpoints
(`/api/tools` for schemas, `/api/config/tools` for the disabled list)?
**Recommendation:** separate endpoints — keeps the config endpoint
write-safe and narrow.

### Smoke test
```bash
uv run pytest tests/test_config.py tests/test_server.py -v
# Then manually:
curl http://localhost:8000/api/config/tools          # {"disabled": []}
curl -X PUT http://localhost:8000/api/config/tools \
  -H "Content-Type: application/json" \
  -d '{"disabled": ["shell"]}'                       # {"disabled": ["shell"]}
# Start a chat — confirm "shell" is not offered to the model.
```

### Estimate
Half a day. The frontend toggle UI is the variable — budget two hours for
the sidebar panel alone.

---

## NUG-004 · Tool approvals in web UI · P1 · L

### One-line goal
Close the `ask`-becomes-`allow` silent downgrade in web mode: instead,
emit a `tool_approval_request` SSE event and wait for the client to POST
`/approve` before continuing.

### Where the work happens
- **Edit:** `src/nugget/server.py` — new SSE event type, new
  `/approve` endpoint, `Future`-based blocking in the tool executor,
  timeout handling, removal of the silent downgrade in
  `_web_approval_config()`.
- **Edit:** `src/nugget/web/app.js` — handle `tool_approval_request` event,
  render modal, POST to `/approve`.
- **Edit:** `src/nugget/web/index.html` — modal markup.
- **Edit:** `src/nugget/web/style.css` — modal styles.
- **Add/Edit:** `tests/test_server.py` — happy-path approve, deny, timeout.

### Pre-flight
Read `src/nugget/server.py` in full, focusing on:
- `_web_approval_config()` (line ~64) — the current silent downgrade.
- `_web_tool_executor()` — the callable passed to `backend.run()`.
- The SSE streaming loop — where events are emitted and how the generator
  yields.

### First step
1. Add a module-level `_approval_futures: dict[str, Future]` dict to
   `server.py` (keyed by `request_id`).
2. Add `POST /api/sessions/{session_id}/approve` that looks up
   `request_id` from the body and resolves the future.
3. In `_web_tool_executor()`, when the resolved approval is `"ask"`:
   - Generate a UUID `request_id`.
   - Emit `tool_approval_request` SSE event with `name`, `args`,
     `request_id`.
   - Store a new `Future` in `_approval_futures[request_id]`.
   - Block (with a 60-second timeout) on `future.result()`.
   - If the future resolves `approved=True`, proceed; if `False` or
     timeout, return the `_denied` shape.
4. Remove (or gate) the `ask`→`allow` mutation in `_web_approval_config()`.
5. Add the frontend modal and POST only after the backend is green.

### Acceptance criteria (copy from `backlog.md#NUG-004`)
- New SSE event type `tool_approval_request` with `name`, `args`,
  `request_id` fields.
- New endpoint `POST /api/sessions/{id}/approve` accepting
  `{request_id, approved: bool}`.
- Backend thread blocks on a `concurrent.futures.Future` keyed by
  `request_id` until resolved or 60s timeout; on timeout, deny.
- Frontend renders a modal on `tool_approval_request` with tool name and
  args; Approve/Deny buttons POST to `/approve`.
- `_web_approval_config()` no longer mutates `ask` to `allow` when a
  client is connected; only applies the downgrade as a fallback for
  disconnected sessions.
- Multiple concurrent approval requests within one turn are queued, not
  interleaved.
- Tests (in `tests/test_server.py`): approve happy path, deny path, timeout
  path, and that `_web_tool_executor` returns the correct `_denied` shape
  on deny/timeout.

### Open question to settle in PR
How to route approval to the correct client when multiple browser tabs have
the same session open? **Recommendation:** accept the first `/approve` POST
that arrives for a given `request_id` (first-writer wins). Document this in
a comment next to the `_approval_futures` dict.

### Smoke test
```bash
uv run pytest tests/test_server.py -v
# Then manually:
# 1. Set config: approval rule "ask" for "shell".
# 2. Start nugget-server, open the web UI.
# 3. Send: "run `echo hello` using the shell tool".
# 4. Confirm the approval modal appears.
# 5. Click Approve — confirm the response includes "hello".
# 6. Repeat and click Deny — confirm the response notes the denial.
```

### Estimate
One full day. The Future-based SSE hold is the novel part — budget half the
day for that and the timeout handling. The frontend modal is a further two
to three hours.

---

## What is NOT in this sprint

- **NUG-005 (Jinja template sink):** Gated on NUG-001 landing in v0.3.
  Once NUG-001 has had a sprint of real use, promote NUG-005 as the v0.4
  follow-up item or lead the next sprint.
- **NUG-007 (Status bar):** v0.4 candidate but sized L with a soft
  dependency on NUG-006 (session titles) for the title field. Pull in if
  NUG-004 lands with time to spare; otherwise leads the next sprint.
- **NUG-006, 014:** v0.5. Need design-doc rounds first.
- **NUG-012, 013 (bench):** Parallel track. Good "any contributor with a
  free afternoon" tickets — don't block on them.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| `Future`-based blocking in the SSE generator thread hangs connections | Set `timeout=60` strictly; log and deny on timeout so the conversation recovers rather than hanging. Add a test that exercises the timeout path. |
| Multiple browser tabs racing on the same `request_id` | First-writer-wins policy (documented in code). Consider emitting a `tool_approval_resolved` event so other tabs can dismiss their stale modal. |
| NUG-009's `PUT /api/config/tools` races with concurrent requests writing to config file | Add a `threading.Lock()` around the config write path in `Config`. The current class is not thread-safe. |
| NUG-008 accumulates thinking text in the wrong turn if the user sends a second message quickly | Track the active turn by turn boundary (`done` event resets the accumulator). Test by sending two messages back-to-back in mock mode. |
| Sprint slips past 2026-05-24 | NUG-008 + NUG-011 alone are a respectable v0.4 patch. NUG-009 and NUG-004 can slip to v0.4.1 without breaking the web-parity theme. |

---

## Definition of "ready to ship"

Before opening the v0.4 release PR (`staging` → `main`):

- [ ] All four sprint tickets merged into `develop` and forwarded to `staging`.
- [ ] `pyproject.toml` version bumped to `0.4.0`.
- [ ] `ROADMAP.md` "Done" section updated with v0.4 items.
- [ ] Manual web-UI smoke test: thinking visible, tool toggle effective,
      approval modal round-trips for both approve and deny.
- [ ] `CHANGELOG` (or release notes drafted in PR body) lists the four
      tickets and the bumped version.
