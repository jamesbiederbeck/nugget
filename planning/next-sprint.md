# Nugget — next sprint

**Window:** 2026-05-04 → ~2026-05-18 (two weeks)
**Target release:** v0.5 (`Config profiles`)
**Working branch convention:** `develop` first → PR to `staging` → PR to `main` (per `CLAUDE.md`).

The previous sprint (v0.4 — Subagent MVP) shipped v0.4.0 on 2026-05-01 with
NUG-015/016/017 and the bonus `wolfram` tool merged. This sprint pivots to
the headline new feature requested for v0.5: **config profiles**. Design
notes live in `planning/profiles.md`; the implementation slices below
follow that doc.

---

## Sprint goal

Ship named configuration overlays that users can activate via a single CLI
flag (`nugget --profile code-agent`). Profiles are also reusable as
subagent personas — either explicitly via `spawn_agent`'s new `profile`
arg, or via `subagent.default_profile`. Everything lives in
`config.json`; no new files, no registration step.

**Definition of done for the sprint:**
- `nugget --profile <name>` and `nugget-server --profile <name>` select a
  profile end-to-end.
- `nugget --list-profiles` lists configured profile names.
- Unknown profile names are a hard error with a helpful message listing
  available names.
- Profiles support all top-level config keys plus the new
  `include_tools` / `exclude_tools` keys.
- `spawn_agent(profile=...)` runs a child with that profile; if absent,
  falls back to `subagent.default_profile`. Parent's active profile does
  **not** bleed into the child.
- `tool_docs/CONFIG.md`, `README.md`, `tool_docs/TOOL_SPEC.md`, and
  `CHANGELOG.md` are updated.
- `pyproject.toml` bumped to `0.5.0` on `main`; release pipeline ships
  `ghcr.io/<owner>/nugget:0.5.0` and `:latest`.
- All current tests still pass; net test count grows by ≥ 15 (NUG-018
  config matrix + NUG-021 spawn_agent integration).

---

## Pick order

| Order | Ticket  | Why now |
|-------|---------|---------|
| 1     | NUG-018 | Foundation: profile resolution inside `Config`. Every other ticket in the line consumes this API. |
| 2     | NUG-019 | Wires the new `Config(profile=...)` argument into both entry points. Independent of NUG-020/021 — can ship as soon as NUG-018 lands. |
| 3     | NUG-020 | Adds the `include_tools` / `exclude_tools` config keys so profiles can scope tools. Independent of NUG-019 but small enough to land in the same window. |
| 4     | NUG-021 | Subagent integration: `spawn_agent(profile=...)` and `subagent.default_profile`. Depends on both NUG-018 and NUG-020 (the child needs to read profile-level tool keys). |
| 5     | NUG-022 | Docs catch-up + version bump. Bundle in the v0.5 release commit. |

NUG-019 and NUG-020 can land in either order or in parallel once NUG-018
is merged.

---

## NUG-018 · Profile resolution in `Config` · P0 · M

### One-line goal
Teach `Config` about a `profiles` block and a profile-selection step.

### Where the work happens
- **Edit:** `src/nugget/config.py` — add `profile` arg to `__init__`,
  add `list_profiles()`, add `active_profile` attribute, add
  `UnknownProfileError`, strip `profiles` from resolved `_data`.
- **Edit:** `tests/test_config.py` — extend with the test matrix in the
  ticket's acceptance criteria.

### Required reading before starting
1. `planning/profiles.md` — full design.
2. `src/nugget/config.py` — current 102-line `Config` class. The merge
   logic today is `dict.update()`-based; the profile layer slots in
   between the file load and the overrides.

### First step
1. Add `profile: str | None = None` to `Config.__init__`. Accept it,
   store as `self._active_profile`, but don't act on it yet.
2. After the `config.json` load, look up `profiles.get(profile)` and
   `dict.update()` the base data with it. Whole-block replacement for
   nested keys is what `dict.update` already does — write a test for
   `approval` to lock that in.
3. Strip `"profiles"` from `self._data` after resolution.
4. Add `UnknownProfileError` and the `list_profiles()` helper.

### Acceptance criteria
See `backlog.md#NUG-018`. Eight criteria; the load-bearing ones are
whole-block replacement for nested objects, the strip-`profiles`-from-
runtime-data invariant, and the unknown-name error carrying available
names for the CLI to format.

### Smoke test
```bash
uv run pytest tests/test_config.py -v
```

### Estimate
Half a day. Most of the work is the test matrix.

---

## NUG-019 · `--profile` CLI flag · P0 · S

### One-line goal
Plumb `Config(profile=...)` into both `nugget` and `nugget-server`.

### Where the work happens
- **Edit:** `src/nugget/__main__.py` — add `--profile` and
  `--list-profiles` flags, thread through to **both** `Config(...)` calls
  (initial `ensure_default()` and the `Config(overrides)` rebuild after
  CLI parsing).
- **Edit:** `src/nugget/server.py` — add `--profile` flag and pass
  through to the `Config` instance the server holds.
- **Edit:** `src/nugget/display.py` — extend session header to show
  active profile name when set.
- **Edit:** `tests/test_main.py`, `tests/test_server.py`.

### Pre-flight
- Land NUG-018 first.

### First step
Add `--profile` / `--list-profiles` to `make_parser()`. Implement
`--list-profiles` early-exit (mirror `--list-tools`). Then thread the
value through both `Config(...)` constructions.

### Acceptance criteria
See `backlog.md#NUG-019`.

### Smoke test
```bash
uv run pytest tests/test_main.py tests/test_server.py -v
nugget --list-profiles
nugget --profile pure-chat "say hi"   # expects unknown-profile error if not configured
```

### Estimate
2–3 hours.

---

## NUG-020 · `include_tools` / `exclude_tools` config keys · P1 · S

### One-line goal
Mirror the existing `--include-tools` / `--exclude-tools` CLI flags as
config keys so profiles can scope tools.

### Where the work happens
- **Edit:** `src/nugget/config.py` — `DEFAULTS` gains both keys
  (`null` default), conflict validation runs at config-resolution time.
- **Edit:** `src/nugget/__main__.py` — fall back to config values when
  the corresponding CLI flag is absent.
- **Edit:** `src/nugget/server.py` — same fallback in the server's
  schema-selection path.
- **Edit:** `tests/test_config.py`, `tests/test_main.py`.

### Pre-flight
- Land NUG-018 first (so a profile can set these keys and have them
  override the base).

### First step
Add the two keys to `DEFAULTS`. Add a small `_validate_tool_filters()`
helper in `Config` and call it after profile merge. Then update both
call sites of `tool_registry.schemas(...)` to consult `cfg` when CLI
args are unset.

### Acceptance criteria
See `backlog.md#NUG-020`.

### Smoke test
```bash
uv run pytest tests/test_config.py tests/test_main.py -v
```

### Estimate
3–4 hours.

---

## NUG-021 · Subagent profile integration · P1 · M

### One-line goal
Make `spawn_agent` profile-aware, with `subagent.default_profile` as a
fallback. Parent's active profile must NOT bleed into the child.

### Where the work happens
- **Edit:** `src/nugget/tools/spawn_agent.py` — add `profile` to SCHEMA,
  resolve child profile name (arg → `subagent.default_profile` → none),
  build child config via `Config(profile=resolved_name)` from the
  filesystem (NOT from the parent's resolved `Config`), feed
  profile-level `include_tools` / `exclude_tools` into child schema
  selection when explicit `tools` arg is absent.
- **Edit:** `src/nugget/config.py` — `DEFAULTS["subagent"]["default_profile"]`
  added as `null`.
- **Edit:** `src/nugget/subagent.py` — only if a small helper makes the
  resolution code clearer; otherwise leave alone.
- **Edit:** `tests/tools/test_spawn_agent.py`.

### Pre-flight
- Land NUG-018 (need `Config(profile=...)`).
- Land NUG-020 (so child can honour profile-level tool filters).

### First step
1. Decide and document: child profile resolution is independent of
   parent profile. The parent's `Config` instance is consulted only for
   the `subagent.default_profile` fallback.
2. Add `profile` to SCHEMA. In `execute()`, after the depth check but
   before any heavy work, resolve the profile name. Construct child
   config; on `UnknownProfileError`, return `{"error": "unknown profile
   '<name>'. Available: ..."}`.
3. Update child tool selection: when the explicit `tools` arg is None,
   honour the child config's `include_tools` / `exclude_tools` (if set).
4. Persist `"profile": <name|null>` to the per-call transcript JSON.

### Acceptance criteria
See `backlog.md#NUG-021`.

### Smoke test
```bash
uv run pytest tests/tools/test_spawn_agent.py -v
```

### Estimate
Half a day.

---

## NUG-022 · Profile docs and changelog · P1 · S

### One-line goal
Update `tool_docs/CONFIG.md`, `README.md`, `tool_docs/TOOL_SPEC.md`,
`CHANGELOG.md`, `pyproject.toml`, `ROADMAP.md`. Bundle in the v0.5
release commit.

### Where the work happens
- **Edit:** `tool_docs/CONFIG.md` — JSON Schema additions + new
  "Profiles" section.
- **Edit:** `README.md` — short usage example.
- **Edit:** `tool_docs/TOOL_SPEC.md` — `spawn_agent` profile arg.
- **Edit:** `CHANGELOG.md` — create if missing.
- **Edit:** `pyproject.toml` — version → `0.5.0`.
- **Edit:** `ROADMAP.md` — Done entry for v0.5.

### First step
Open `tool_docs/CONFIG.md`, drop the new keys into the JSON Schema,
write the Profiles section using the worked example from
`planning/profiles.md`. Then sync the rest.

### Acceptance criteria
See `backlog.md#NUG-022`.

### Smoke test
```bash
grep -E "include_tools|exclude_tools|profiles|default_profile" tool_docs/CONFIG.md
grep -E "--profile" README.md
```

### Estimate
2–3 hours.

---

## What is NOT in this sprint

- **NUG-005 (Jinja template sink):** still on the bench. Pull in v0.5.1
  if there's contributor bandwidth, otherwise v0.6.
- **NUG-004, 007, 008, 009, 011 (web UI parity):** v0.6. Don't bleed
  scope.
- **NUG-006, 014 (session intelligence):** v0.7. Each needs a design
  round first.
- **Per-session profile switching at runtime** (e.g. a `/profile` slash
  command): out of scope for v0.5; consider for a follow-up release if
  there's demand.
- **Profile inheritance** (one profile extending another): out of scope
  for v0.5. The whole-block replacement rule is intentional and keeps
  resolution legible.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Whole-block replacement for `approval` / `subagent` surprises users who expect deep merge | Document the rule prominently in `tool_docs/CONFIG.md` Profiles section. Test it explicitly in NUG-018. |
| Child config resolution unintentionally inherits parent's active profile | Lock down with a focused test in NUG-021: parent runs with `--profile A`, child explicitly omits `profile` arg, assert child does NOT see profile A's overrides. |
| `include_tools` / `exclude_tools` collision with the existing CLI flags creates ambiguity | NUG-020 acceptance criteria pin the precedence order: CLI > resolved config. Tested both ways. |
| Sprint slips past 2026-05-18 | NUG-018+019 alone is a respectable v0.5.0 (CLI profiles working, no subagent integration). NUG-021 can move to v0.5.1 if needed. NUG-022 should not slip — it's the release commit. |

---

## Definition of "ready to ship"

Before opening the v0.5 release PR (`staging` → `main`):

- [ ] NUG-018, NUG-019, NUG-020, NUG-021, NUG-022 merged into `develop`
      and forwarded to `staging`.
- [ ] `pyproject.toml` version bumped to `0.5.0`.
- [ ] `ROADMAP.md` "Done" section updated; v0.5 — Config profiles
      marked complete.
- [ ] `CHANGELOG.md` v0.5.0 entry lists the five tickets.
- [ ] `tool_docs/CONFIG.md` Profiles section reviewed against
      `planning/profiles.md` for drift.
- [ ] Manual smoke test: define `pure-chat` and `code-agent` profiles in
      `~/.config/nugget/config.json`, confirm `nugget --profile
      pure-chat` and `nugget --profile code-agent` both run end-to-end
      with the expected tool/approval surface.
- [ ] Manual smoke test: `nugget-server --profile pure-chat` boots and
      serves a request with the profile's overrides applied.
