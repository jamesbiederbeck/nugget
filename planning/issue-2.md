# Issue 2 — `/clear` destructively truncates the current session instead of starting a new one

**Status:** open
**Surface:** `src/nugget/commands.py` (`/clear` handler, lines 53–56)
**Type:** defect / data loss

## Problem

`/clear` is documented as "clear message history (keeps session file)." What it
actually does is mutate `session.messages` in-place and immediately call
`session.save()`, which overwrites the existing session JSON with an empty
message list. The previous conversation is permanently destroyed with no
recovery path.

The expected behavior is to allocate a fresh session (new UUID, empty history)
and make it the active session, leaving the original file intact. This makes
`/clear` non-destructive: the user can always `/session <old-id>` to resume
the previous conversation.

```python
# current — destructive
elif cmd == "/clear":
    session.messages.clear()
    session.save()           # overwrites existing file with []
```

## Root cause

The implementation conflates "start fresh" with "erase history." `Session.new()`
already exists and does exactly what is needed, but `/clear` never calls it.
The `session_cell` indirection — introduced specifically so the active session
can be swapped at runtime — is unused here even though it is used correctly by
`/session`.

## Proposed fix

Replace the in-place truncation with a new session allocation, mirroring how
`/session <ID>` swaps the active session:

```python
elif cmd == "/clear":
    ctx.session_cell[0] = Session.new(ctx.sessions_path)
    display.print_session_header(ctx.session_cell[0].id)
    display.print_dim("New session started.")
```

Key points:
- The old session file is left untouched on disk.
- `Session.new()` is not saved until the first `run_turn` call (same lifecycle
  as a fresh startup), so an empty-history file is never written for a `/clear`
  the user immediately follows with `/exit`.
- The help string in `_HELP` should be updated to match:
  `"/clear             start a new session (old session is preserved)"`

## Acceptance criteria

- After `/clear`, `session_cell[0].id` is a different UUID than it was before.
- The previous session file still exists on disk with its original messages.
- The session header line is printed (same as startup / `/session <id>`).
- No empty-history file is written for a `/clear` followed immediately by
  `/exit` without sending any message.
- `/sessions` lists both the old and new sessions.

## Out of scope

- Confirmation prompt — not needed because the old session is preserved.
- Auto-naming or titling the old session before clearing.

## Effort

XS (< 1 h). Four-line change plus a help-string update and a test.

## Suggested ticket ID

NUG-016 when promoted into `backlog.md`.
