# Nugget — next sprint

**Window:** 2026-04-26 → ~2026-05-10 (two weeks)
**Target release:** v0.3 (`Routing & backends complete`)
**Working branch convention:** `develop` first → PR to `staging` → PR to `main` (per `CLAUDE.md`).

This file picks the four highest-priority tickets from `backlog.md` that are
ready to start *today* and adds enough scaffolding (file pointers, first-step
hints, smoke-test recipes) that a contributor can open the file, read down
once, and start typing.

The tickets are ordered to minimise blocking. NUG-001 is the keystone for v0.3
and should land first. NUG-002 is a small refactor that NUG-003 wants in place.
NUG-010 is parallelisable with everything and is a good "between PRs" filler.

---

## Sprint goal

Ship v0.3 with output routing actually executing (today it raises
`NotImplementedError`), a second backend proving the abstraction, and
`CONTRIBUTING.md` accurate enough that the next contributor doesn't bounce
off stale signatures.

**Definition of done for the sprint:**
- `nugget` user can call `render_output(...)` from the model and get
  `display`, `display:<jmespath>`, `file:<path>`, and `$var` sinks working.
- `nugget --backend openrouter` runs against a real OpenRouter API key and
  passes the same `bench/cases/render_output.tsv` cases (intent-only OK if
  end-to-end is too slow for CI).
- `pyproject.toml` bumped to `0.3.0` on `main`; release pipeline produces
  `ghcr.io/<owner>/nugget:0.3.0` and `:latest`.
- All existing 213 tests still pass; net test count grows by ≥ 12 (NUG-001
  approval-deny, sink matrix; NUG-003 mock matrix).

---

## Pick order

| Order | Ticket  | Why now |
|-------|---------|---------|
| 1     | NUG-001 | Single biggest user-facing gap. Bench cases already exist; ships value the day it lands. |
| 2     | NUG-002 | Tiny but locks the contract before NUG-003 is written against it. Run while NUG-001 is in review. |
| 3     | NUG-003 | Validates the backend abstraction and unlocks running nugget without a local model server. |
| 4     | NUG-010 | Pure docs. Land any time. Best done last in the sprint so it captures NUG-002's signature change. |

NUG-005 (Jinja template sink) is also in v0.3 but is gated on NUG-001 and is
better picked up at the start of the next sprint, after NUG-001 has had a
week of real use.

---

## NUG-001 · Implement `render_output` dispatch · P0 · M

### One-line goal
Make `render_output(tool_name, tool_args, output=...)` actually call the
wrapped tool and route its result through the existing per-call sink machinery.

### Where the work happens
- **Edit:** `src/nugget/tools/render_output.py` (currently 34 lines, the
  `execute()` body just raises).
- **Edit:** `src/nugget/backends/textgen.py` — `_route_tool_result()` is the
  function the new code needs access to. Either expose it as a module-level
  helper or split the routing logic into `src/nugget/backends/_routing.py`
  and import from both places.
- **Add:** `tests/tools/test_render_output.py`.

### First step
1. Read `src/nugget/backends/textgen.py` end-to-end and locate
   `_route_tool_result`, `_validate_sink`, and the `bindings` dict that gets
   passed through the tool loop.
2. Decide: hoist the routing helpers into `src/nugget/backends/_routing.py`
   (recommended — NUG-003 will want them too) or keep them in `textgen.py`
   and just expose them.
3. Refactor in a separate commit before any behaviour change. Run the test
   suite. It should be green with no logic changes.
4. Wire `render_output.execute()` to take `(tool_name, tool_args, output)`,
   call `tools.execute(tool_name, tool_args)`, then route via the helper.
5. Approval: leave `APPROVAL = "allow"` on `render_output` itself — the
   wrapped tool's gate is consulted inside `tools.execute()` already.

### Acceptance criteria (copy from `backlog.md#NUG-001`)
- `render_output` looks up `tool_name` in the registry, calls its
  `execute()`, and routes the result through the per-call sink machinery.
- `output` arg is optional; absent means `display`.
- Sink validation reuses `_validate_sink()` (allowed forms: `display`,
  `display:<jmespath>`, `file:<path>`, `$var`, `$var.<jmespath>`).
- Error stubs match the existing routing error shape:
  `{"status": "error", "reason": "..."}`.
- Approval is checked for the *wrapped* tool, not for `render_output`.
- `bench/cases/render_output.tsv` runs end-to-end (no `--mock-tools`) and
  matches or beats the current mock-mode pass rate.
- Unit tests cover: display sink, file sink (with file-sink approval), `$var`
  sink + later substitution, unknown wrapped tool, approval-denied wrapped
  tool, missing required arg.

### Smoke test
```bash
uv run pytest tests/tools/test_render_output.py -v
nugget "use render_output to call calculator with expression='2+2' and put the answer in the user-facing display"
uv run python bench/run.py --filter render_output --repeat 3
```

### Open question to settle in PR
Does `render_output` execute the wrapped tool inside the harness's own tool
loop (so the wrapped tool can itself emit `output:` bindings) or does it
call `tools.execute()` directly and then route? **Recommendation:** the
latter (simpler, doesn't allow recursive routing). Document the limitation
in the tool's `description` field.

### Estimate
Half a day if the routing helper hoist is clean. A full day if it surfaces
hidden coupling.

---

## NUG-002 · Promote `Backend` Protocol to ABC · P1 · S

### One-line goal
Lock the `Backend.run()` 4-tuple return into a typed contract so NUG-003
can implement against it without guessing.

### Where the work happens
- **Edit:** `src/nugget/backends/__init__.py` — the `Backend` Protocol.
- **Edit:** `src/nugget/backends/textgen.py` — only the class decorator/base.
- **Edit:** `CONTRIBUTING.md` — "Adding a backend" section.

### First step
Read the current `Backend` Protocol and `make_backend()` in
`src/nugget/backends/__init__.py`. Decide: convert to `abc.ABC` (loses
duck-typing, gains `isinstance()` and runtime enforcement of method
existence) or keep as Protocol but add the full typed signature. Either is
fine; ABC is more conventional for Python projects of this size.

### Acceptance criteria (copy from `backlog.md#NUG-002`)
- `Backend` becomes an `abc.ABC` (or fully-typed Protocol — pick one).
- `run()` signature matches the textgen return: `tuple[str, str | None,
  list[dict], str | None]`.
- `make_backend()` return type annotation is the ABC/Protocol, not bare
  `Backend`.
- Type-check pass with `mypy` or `pyright` against `src/nugget/backends/`.
- All existing tests pass.
- The contract is documented once in the ABC docstring and referenced from
  `CONTRIBUTING.md`.

### Suggested addition for this ticket
Add `mypy` (or `pyright`) as a dev-extra in `pyproject.toml`. Not strictly
required for AC, but the ticket loses half its value without a type
checker actually being run. One line in the dev extras and a one-line
`mypy.ini` is enough.

### Smoke test
```bash
uv run pytest -v
uv run mypy src/nugget/backends/
```

### Estimate
Two to four hours.

---

## NUG-003 · OpenRouter backend · P1 · M

### One-line goal
A second backend that talks to OpenRouter's `/v1/chat/completions` so
nugget runs without a local text-generation-webui instance.

### Where the work happens
- **Add:** `src/nugget/backends/openrouter.py`.
- **Edit:** `src/nugget/backends/__init__.py` — add `"openrouter"` branch in
  `make_backend()`.
- **Edit:** `src/nugget/config.py` — `DEFAULTS` gains `openrouter_api_key`,
  `openrouter_model`.
- **Add:** `tests/backends/test_openrouter.py` — mock `requests` with
  `pytest-mock`.
- **Edit:** `README.md`, `tool_docs/TOOL_SPEC.md` — backends table.

### Pre-flight
1. Get an OpenRouter API key (or a test key) into your shell:
   `export OPENROUTER_API_KEY=sk-or-...`.
2. Skim two pages of OpenRouter docs:
   `https://openrouter.ai/docs#chat-completions` and the streaming /
   tool-use sections. The API is OpenAI-compatible; the surprises are
   around `reasoning_content`, the `HTTP-Referer` header, and the
   tool-call delta-merge format.
3. Read `src/nugget/backends/textgen.py` end-to-end so you know what
   responsibility belongs to the backend vs the harness.

### First step
Write `tests/backends/test_openrouter.py` first, even just with one happy-
path test using `pytest-mock`. The tests will pin down the integration
points (config keys, message format, tool-call shape) and force you to
think about the SSE delta merge before writing the code. Then implement
the backend module to make the test pass.

### Acceptance criteria (copy from `backlog.md#NUG-003`)
- New `src/nugget/backends/openrouter.py` implements the `Backend`
  ABC/Protocol from NUG-002.
- Config keys: `"backend": "openrouter"`, `"openrouter_api_key"` (or env
  `OPENROUTER_API_KEY`), `"openrouter_model"`.
- `make_backend()` recognises `"openrouter"`.
- Tool calling uses native OpenAI `tools` + `tool_calls` fields. Tool loop
  runs at the chat-completions level: model returns `tool_calls`, harness
  executes, appends `role: tool` messages, recurses up to 16 times.
- Streaming: SSE deltas → `on_token`. Tool-call args assembled across
  deltas (OpenAI streams them as a partial-JSON string per tool call;
  merge by `tool_call.index`).
- Output routing (`output` meta-arg) works identically to `textgen`. Reuse
  the helpers hoisted in NUG-001.
- Thinking: capture `reasoning_content` from delta or final message and
  emit via `on_thinking`.
- Tests cover: simple completion, tool call → result → final, multi-tool
  loop, sink routing pass-through, errors (401, 429, network).
- README and TOOL_SPEC tables list the new backend with its config keys.

### Smoke test
```bash
uv run pytest tests/backends/test_openrouter.py -v
nugget --backend openrouter "what's 2+2?  use the calculator tool."
nugget --backend openrouter "fetch a wallabag article and summarise it"  # tool loop
uv run python bench/run.py --filter render_output --backend openrouter
```

### Out of scope
Multimodal input, OpenRouter-specific rate-limit retry logic (surface the
error message and let the user retry).

### Estimate
One full day. The streaming tool-call delta-merge is the time sink —
budget half the day for that alone.

---

## NUG-010 · Doc-drift cleanup · P1 · S

### One-line goal
Three known mismatches between docs and code, all small. Best fixed at the
end of the sprint because NUG-002 will change one of them again.

### Where the work happens
- **Edit:** `tool_docs/TOOL_SPEC.md` — version line, `Backend.run()`
  example signature, "Built-in Tools" section.
- **Edit:** `CONTRIBUTING.md` — "Adding a backend" signature.
- **Edit:** `README.md` — tools table.

### First step
Open `tool_docs/TOOL_SPEC.md` and search for `Version: 0.1.0`,
`(text, thinking, tool_exchanges)`, and the existing tools table. Fix all
three in one pass. Move on to `CONTRIBUTING.md` for the same signature
fix. Then add `wallabag`, `notify`, `render_output` to the README tools
table — one line each, link to its source file.

### Acceptance criteria (copy from `backlog.md#NUG-010`)
- `tool_docs/TOOL_SPEC.md` version line matches `pyproject.toml` (or is
  removed; pyproject is authoritative).
- `CONTRIBUTING.md` "Adding a backend" shows `Backend.run()` returning a
  4-tuple `(text, thinking, tool_exchanges, finish_reason)`.
- `tool_docs/TOOL_SPEC.md` "Writing a Custom Backend" example fixed too.
- README tools table includes `wallabag`, `notify`, `render_output` (or a
  note that some tools require env config and are off by default).
- TOOL_SPEC "Built-in Tools" gains `wallabag` and `notify` entries with
  schemas, env vars, approval gates.

### Smoke test
```bash
grep -n "tool_exchanges" tool_docs/TOOL_SPEC.md CONTRIBUTING.md
grep -n "Version:" tool_docs/TOOL_SPEC.md
grep -n "wallabag\|gotify\|render_output" README.md
```
All three should now agree with the code.

### Estimate
One to two hours. Prefer to bundle in the same PR as the version bump to
0.3.0 so the release commit is self-consistent.

---

## What is NOT in this sprint

- **NUG-005 (Jinja template sink):** v0.3 candidate but blocked on
  NUG-001's routing helper hoist landing. Pull in next sprint.
- **NUG-004, 007, 008, 009, 011 (web UI work):** v0.4. Don't bleed scope.
- **NUG-006, 014:** v0.5. Each needs design ratification first.
- **NUG-012, 013 (bench):** parallel track. Pick up if a contributor wants
  a self-contained afternoon ticket; otherwise leave for v0.4.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| NUG-001 routing-helper hoist surfaces hidden coupling in `textgen.py` | Land the hoist refactor as its own PR before any behaviour change. Run the full test suite between commits. |
| NUG-003's OpenRouter delta-merge bugs are caught only in production | Add a mock-deltas test in `test_openrouter.py` that replays a captured SSE stream of a tool-call response. Capture from a real call and commit the fixture. |
| Sprint slips past 2026-05-10 | NUG-001 and NUG-002 alone ship a respectable v0.3. NUG-003 can be deferred to v0.3.1 if needed without breaking the release theme. |
| Doc drift re-introduced by NUG-002 | NUG-010 is sequenced last for this reason. |

---

## Definition of "ready to ship"

Before opening the v0.3 release PR (`staging` → `main`):

- [ ] All four tickets above merged into `develop` and forwarded to `staging`.
- [ ] `pyproject.toml` version bumped to `0.3.0`.
- [ ] `ROADMAP.md` "Done" section updated.
- [ ] `bench/run.py --filter render_output` passes end-to-end (not mock).
- [ ] `nugget --backend openrouter` smoke-tested with at least one tool-call
      and one non-tool-call prompt.
- [ ] `CHANGELOG` (or release notes drafted in PR body) lists the four
      tickets and the bumped version.
