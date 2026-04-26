# Nugget — codebase audit

**Date:** 2026-04-26
**Branch:** `main`
**Version (pyproject.toml):** 0.2.1
**Tests:** 213 passing (`uv run pytest`, 0.73s)

## Scope

Files inspected: `src/nugget/**`, `tests/**`, `bench/**`, `tool_docs/**`,
`.github/workflows/**`, `Dockerfile`, `docker-compose.yml`, `ROADMAP.md`,
`README.md`, `CONTRIBUTING.md`, `CLAUDE.md`. No private state assumed —
everything below is verifiable from the repo.

---

## What's built and working

### CLI (`nugget`)
- `__main__.py` — full argparse surface (one-shot, interactive, `--session`, `--include/exclude-tools`, `--list-tools`, `--list-sessions`, `--thinking[-effort]`, `--verbose`, debug, `--version`)
- `commands.py` — interactive `/help /exit /clear /rewind /prompt /sessions /session /tools /memory /verbose /thinking`
- `display.py` — ANSI-coloured printing, readline-safe `\001/\002` prompt wrapping
- Streaming: `_complete_streaming` handles token + thinking + tool-call lookahead via 20-char buffer

### Web server (`nugget-server`)
- FastAPI app with five endpoints (`GET/POST /api/sessions`, `GET/DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/chat`)
- SSE event types: `token`, `thinking`, `tool_call`, `tool_result`, `tool_denied`, `done`, `error`
- Static frontend served from `src/nugget/web/` (sidebar, sessions list, view-toggles, message area)
- `ask` actions silently downgraded to `allow` in web mode (no TTY)

### Backend
- `Backend` Protocol (`@runtime_checkable`) — `run()` returns `(text, thinking, tool_exchanges, finish_reason)`
- `TextgenBackend` — sole implementation; talks to text-generation-webui `/v1/completions`, formats Gemma 4 special tokens, parses tool calls out of completion text, loops up to 16 times
- Output routing fully wired: `display`, `display:<jmespath>`, `file:<path>`, `$var` bindings (turn-scoped), `$var.<jmespath>` substitution
- File-sink approval system parallel to tool approval — `subtree`/`exact`/`existing`/`any` rules, `strictest` vs `first` conflict resolution

### Tools (auto-discovered in `src/nugget/tools/`)
| Tool | APPROVAL | Tested | Notes |
|------|----------|--------|-------|
| `calculator` | (default allow) | yes | safe AST evaluator |
| `get_datetime` | (default allow) | yes | IANA timezones |
| `shell` | `ask` | yes | subprocess with timeout |
| `filebrowser` | (default allow) | yes | `cwd`/`ls`/`cat` |
| `memory` | dynamic (`ask` on delete) | yes (23 tests) | SQLite, pinning, `memory://` link resolution up to depth 3 |
| `wallabag` | `allow` | no | OAuth via env vars; `list/search/post/get` |
| `notify` (gotify) | `allow` | no | env-var-driven |
| `render_output` | `allow` | no | **STUB — raises `NotImplementedError`** |

### Persistence
- Sessions: JSON at `~/.local/share/nugget/sessions/{id}.json` — full `messages` list with thinking + `tool_calls` per assistant turn
- Memory: SQLite at `~/.local/share/nugget/memory.db` — `key/value/pinned/updated_at`; pinned rows injected into every system prompt
- Config: `~/.config/nugget/config.json`, `Config.ensure_default()` materialises on first run
- Readline history: `~/.local/share/nugget/history`

### Bench (`bench/run.py`)
- TSV-defined cases (`bench/cases/render_output.tsv`, `sinks.tsv`) ingested into SQLite (`bench.db`)
- Constraints: `regex` / `absent` against dot-paths into `tool_call[N]`
- `--mock-tools` for fast intent-only checks; `--repeat` for stability runs; `--filter` for case selection
- ERD documented in `bench/erd.md`

### CI / release
- `.github/workflows/test.yml` — pytest matrix on Python 3.11 and 3.12, runs on push to `develop/staging/main` plus PRs and manual dispatch
- `.github/workflows/release.yml` — runs on push to `main` and `staging`; tests gate Docker build; on `main` creates `v<version>` tag (if new) and pushes to GHCR (`<owner>/nugget:<version>`, `:latest`, plus `:<sha>`); on `staging` pushes `:staging` and `:<sha>`
- `Dockerfile` — `python:3.11-slim`, ENTRYPOINT `python -m nugget`
- `docker-compose.yml` — runs the web server with mounted config + data volumes
- `.github/PULL_REQUEST_TEMPLATE.md` — What/Why/Test plan/Checklist (tests + version-bump reminder)

### Documentation
- `README.md` — usage, tools table, config defaults, branching badges
- `CONTRIBUTING.md` — setup, branching strategy, test commands, tool/backend authoring, release process
- `tool_docs/TOOL_SPEC.md` — exhaustive backend/server/tool reference (~990 lines)
- `tool_docs/_bash_tool_template.py`, `tool_docs/ping_host.py` — example tool authoring artefacts
- `blog/output-routing-experiment.md` — narrative writeup of bench results (76.9% → improved via prompt iteration)
- `bench/erd.md` — bench DB schema doc

---

## What's stubbed or missing

### Code-level

1. **`render_output.execute()` raises `NotImplementedError`.** `src/nugget/tools/render_output.py:33`. Bench cases (`bench/cases/render_output.tsv`) and the system-prompt `## Tool output routing` section already direct the model to use it. Today the model can call it; execution always errors. **This is the single most user-visible gap.**

2. **`tools.disabled` config key does not exist.** `ROADMAP.md` item #10 says "Per-tool enable/disable controls in the web interface, mirroring the config-level `tools.disabled` list." `src/nugget/config.py:DEFAULTS` has no such key. The web server hard-codes `tool_registry.schemas()` (no filter) at `server.py:134`. The CLI has `--include/exclude-tools` but no equivalent persistent config field. Either ROADMAP is forward-looking or the feature is half-wired.

3. **`SessionList` API response shape inconsistency.** `Session.list_sessions()` returns `id/updated_at/turns/preview`. `tool_docs/TOOL_SPEC.md` line 188-196 documents the `/api/sessions` response as `id/created_at/updated_at` (no `turns`/`preview`, includes `created_at` which the helper doesn't return). The frontend (`web/app.js`) reads `s.turns` and `s.preview` — so the implementation is right and the docs are wrong, but it's worth pinning down.

4. **No backend other than `textgen`.** The Protocol exists; nothing else implements it. Roadmap item #2 (Protocol → ABC) and #3 (OpenRouter) are the natural follow-ups.

5. **Subprocess in `shell` tool uses `text=True` without explicit encoding.** Outputs from non-UTF-8 commands could raise `UnicodeDecodeError` and crash the request. Low priority; only bites in edge cases.

6. **`wallabag._TOKEN_CACHE_FILE = "/tmp/.wallabag_token"`** is world-readable. If a multi-user box runs nugget the token is exposed. Not a v0.3 blocker but worth flagging.

### Test coverage gaps

7. **No tests for `render_output`, `wallabag`, `notify` (gotify) tools.** All three are auto-loaded, exposed to the model, and untested. `wallabag` and `notify` need network — mock with `pytest-mock`. `render_output` has no tests because there's nothing to test until NUG-001 ships.

8. **No tests for `display.py`, `commands.py`.** Pure UX code, but the readline `\001/\002` wrapping (`display.py:69`) is exactly the kind of thing that broke once already (commits `bb4857f` + `8ef518d`). One regression test would prevent the next breakage.

9. **No tests for `server.py`.** No end-to-end SSE chat-flow test, no approval-downgrade test, no test that `_web_tool_executor` denies correctly. The web mode is shipping in Docker but has zero coverage.

10. **No tests for the bench harness itself.** `bench/run.py` and `bench/ingest.py` aren't on the critical path for users, but they back the prompt-engineering work and have no safety net.

### Documentation drift

11. **`tool_docs/TOOL_SPEC.md` header says "Version: 0.1.0".** Repo is at 0.2.1.

12. **`CONTRIBUTING.md` documents the Backend `run()` signature as a 3-tuple `(text, thinking, tool_exchanges)`.** Actual signature returns a 4-tuple including `finish_reason`. This is load-bearing for anyone writing a new backend (which is exactly what we're about to ask people to do — see NUG-003). `tool_docs/TOOL_SPEC.md` "Writing a Custom Backend" section has the same drift.

13. **README's tools table omits `wallabag`, `notify` (gotify), and `render_output`.** Users discover them only by running `nugget --list-tools`.

14. **`tool_docs/TOOL_SPEC.md` does not document `wallabag` or `notify`.** Same gap.

### CI / release plumbing

15. **No `concurrency:` block in either workflow.** Two pushes to the same branch in quick succession both run to completion. Cheap to add (`group: ${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: true`) — saves CI minutes.

16. **Release workflow runs only `pytest`, no lint/format step.** No `ruff`/`black`/`mypy` configured anywhere. Style is enforced by individual reviewer taste only.

17. **`docker-setup.sh` is `+x` and runnable but undocumented in CONTRIBUTING.md.** Only mentioned implicitly via `docker/README.md`.

### Architecture observations (not bugs, just things to know)

- The 16-iteration tool loop in `TextgenBackend.run()` is a hard cap with no surfacing of "we hit the limit" to the user. Currently if the model loops forever it just stops mid-conversation.
- `Config` does first-write of `~/.config/nugget/config.json` at import time of the CLI but not the server (server uses `Config.ensure_default()` lazily on first request — fine).
- The `_LOOKAHEAD = 20` constant in `_complete_streaming` is the magic number that gates whether output is treated as text vs special-token. Worth a comment about why 20 (longest special prefix is `<|channel>thought` at 17 chars).
- `tools/__init__.py:execute()` swallows all tool exceptions into `{"error": str(e)}`. Good for robustness; bad for debugging — there's no way to get a traceback through the harness.

---

## Notable strengths

- **Test coverage where it matters most.** 947 lines of `tests/backends/test_textgen.py` covering the full output-routing matrix — that's where bugs would be most expensive.
- **Clean tool plug-in model.** `tools/__init__.py` auto-discovers from `pkgutil.iter_modules` with a stable `SCHEMA + execute(args)` contract. Adding `wallabag` / `notify` required zero registry changes.
- **Approval system is composable.** Three resolution layers (config rules → tool gate → default), with separate parallel handling for file-sink paths. Test suite (`test_approval.py`, 329 lines) covers the matrix thoroughly.
- **Bench is a real product, not just a script.** Schema-versioned SQLite, idempotent ingest, ERD doc, mock mode for fast iteration.
- **Branching/release pipeline is genuinely shipped.** Per-branch Docker tags, version-tagged releases, PR template — this is uncommon in solo-dev projects at v0.2.

---

## Quick scoreboard for v0.3

| Roadmap # | Item | Status |
|-----------|------|--------|
| 1 | `render_output` dispatch | **stub — must implement** |
| 2 | Backend ABC | small refactor |
| 3 | OpenRouter backend | net-new but well-scoped |
| 7 | Tool approvals in web UI | needs SSE round-trip + `/approve` endpoint |
| 8 | Status bar | CLI side needs `rich` |
| 9 | Streaming thinking blocks | server already emits the events; frontend gap |
| 10 | Tool toggles in web UI | needs `tools.disabled` config key first |
| 11 | Jinja template sink | gated on #1 |

A coherent v0.3 would ship 1, 2, 3, plus the doc-drift cleanup. See
[roadmap.md](roadmap.md) for the framing.
