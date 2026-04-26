# Nugget — planning/

Generated: 2026-04-26. Anchors against `ROADMAP.md` at the repo root and adds
ticket-level detail (acceptance criteria, effort, file pointers) that the
roadmap omits.

`ROADMAP.md` remains authoritative for *what* ships and in what order. The
files here exist so a contributor can pick up an item and start typing in
under five minutes.

## Index

| File | Purpose |
|------|---------|
| [audit.md](audit.md) | Snapshot of the codebase: what's built, what's tested, what's drifted from docs, what's stubbed |
| [roadmap.md](roadmap.md) | Strategic shaping — themes, v0.3 / v0.4 release framing, design-pending items |
| [backlog.md](backlog.md) | Prioritised tickets (NUG-001…NUG-014) with acceptance criteria, effort, P-priority, labels |
| [next-sprint.md](next-sprint.md) | The 4 highest-priority tickets, fully scoped for immediate pickup |

## How the IDs map to ROADMAP.md

| Ticket | Roadmap item | Title |
|--------|--------------|-------|
| NUG-001 | #1 | `render_output` dispatch implementation |
| NUG-002 | #2 | Backend Protocol → ABC |
| NUG-003 | #3 | OpenRouter backend |
| NUG-004 | #7 | Tool approvals in web UI (SSE round-trip) |
| NUG-005 | #11 | Jinja template sink |
| NUG-006 | #5 + #4 | Session-title computation (and the minimal hook scaffolding it needs) |
| NUG-007 | #8 | Status bar — CLI + web |
| NUG-008 | #9 | Streaming thinking blocks in web UI |
| NUG-009 | #10 | Tool toggles in web UI (also requires a missing `tools.disabled` config key) |
| NUG-010 | — | Doc-drift cleanup (TOOL_SPEC version, CONTRIBUTING backend signature) |
| NUG-011 | — | List `mtime`/`updated_at` consistency in `Session.list_sessions` API output |
| NUG-012 | #16 | Bench: prompt-variant sweeping |
| NUG-013 | #17 | Bench: flakiness report |
| NUG-014 | #15 | Semantic search over memory + sessions |

Items #4 (full hooks framework), #6 (MCP), #12–14 (agent configs / skills /
subagents) are not ticketed yet — they need a design-doc round before they
can be sliced into actionable work. See [roadmap.md](roadmap.md) for the
"design pending" list.
