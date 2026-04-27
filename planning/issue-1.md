# Issue 1 — `filebrowser cat` does not support multiple paths in one call

**Status:** open
**Surface:** `src/nugget/tools/filebrowser.py` (`cat` operation, lines 59–71)
**Type:** tool ergonomics / model-friction

## Problem

`filebrowser`'s `cat` op takes a single `path: string`. To read N files the
model must issue N separate tool calls, each round-tripping through the
harness's tool loop. This shows up as:

- **Slow multi-file reads.** Reading three files = three loop iterations =
  three full prompt re-assembles and three completion calls. With a local
  model this is dominant cost.
- **Tool-loop budget pressure.** `TextgenBackend.run()` caps the loop at
  16 iterations. A few multi-file reads can exhaust that budget before
  the model gets to the actual task.
- **Apparent flakiness.** When the model fails to fan out the calls
  cleanly (e.g. drops to a single-file read of an aggregate path, or
  asks the user to re-issue), it looks like the tool itself is broken
  even though every individual call succeeded. The original field note
  recorded this as "filebrowser tool reading failed on previous attempts,
  requiring explicit file pathing" — that was the symptom, not the cause.

## Proposed fix

Accept either a single string or a list of strings for `path` on the `cat`
op. Return a dict keyed by path → `{content, size}` (or `{error}`),
preserving the existing single-path response shape when a string is passed.

## Acceptance criteria

- `cat` with `path: "a.txt"` returns the existing
  `{path, content, size}` shape (back-compat).
- `cat` with `path: ["a.txt", "b.txt"]` returns
  `{results: {"a.txt": {content, size}, "b.txt": {content, size}}}` with
  per-file errors slotted under their key as `{"error": "..."}`.
- Schema's `path` description updated to document both forms.
- Total response capped at a configurable byte budget (default 256 KiB)
  with truncation marked per-file; prevents one accidental 50 MB read
  from blowing the context window.
- Tests in `tests/tools/test_filebrowser.py` covering: single-string back-
  compat, list of two existing files, list with one missing file, list
  exceeding byte budget.

## Out of scope

- Glob expansion (`*.py`). Adds approval-surface complexity; revisit if
  asked.
- Streaming or chunked reads.

## Effort

S (≤4 h). This is a candidate "good first ticket" — well-scoped, no
cross-cutting changes.

## Suggested ticket ID

NUG-015 when promoted into `backlog.md`. Not yet on the v0.3 sprint —
file under "any contributor with a free afternoon" alongside NUG-012 and
NUG-013.
