"""
Persistent memory backed by SQLite at ~/.local/share/nugget/memory.db.
Operations: store, recall, search, list, delete
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_MEMORY_LINK_RE = re.compile(r"memory://([^\s,;)\"']+)")

_DB_PATH = Path.home() / ".local" / "share" / "nugget" / "memory.db"


def APPROVAL(args: dict) -> str:
    return "ask" if args.get("operation") == "delete" else "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory",
        "description": (
            "Persistent key-value memory across conversations. "
            "Operations: "
            "'store' saves a value under a key; "
            "'recall' retrieves a value by exact key; "
            "'search' finds memories whose key or value contains a substring; "
            "'list' returns all stored keys; "
            "'delete' removes a key. "
            "Link related memories using memory:// URIs in stored values "
            "(e.g., 'see memory://user-name'). Links are auto-resolved when recalling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of: 'store', 'recall', 'search', 'list', 'delete'",
                },
                "key": {
                    "type": "string",
                    "description": "Memory key (required for store, recall, delete)",
                },
                "value": {
                    "type": "string",
                    "description": "Value to store (required for store). May include memory:// URIs to link to related keys.",
                },
                "query": {
                    "type": "string",
                    "description": "Substring to search for (required for search)",
                },
                "pin": {
                    "type": "boolean",
                    "description": "If true, mark this memory as pinned so it always appears in the system prompt. If false, unpin it. Omit to leave pin status unchanged.",
                },
            },
            "required": ["operation"],
        },
    },
}


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            pinned     INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory)")}
    if "pinned" not in cols:
        conn.execute("ALTER TABLE memory ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def get_pinned() -> list[dict]:
    """Return all pinned memories; used to inject into the system prompt."""
    if not _DB_PATH.exists():
        return []
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM memory WHERE pinned=1 ORDER BY key"
            ).fetchall()
        return [{"key": r[0], "value": r[1]} for r in rows]
    except Exception:
        return []


def _follow_links(value: str) -> list[dict]:
    """Fetch memories referenced by memory:// URIs found in value."""
    keys = _MEMORY_LINK_RE.findall(value)
    if not keys or not _DB_PATH.exists():
        return []
    results = []
    try:
        with _connect() as conn:
            for k in dict.fromkeys(keys):  # deduplicate, preserve order
                row = conn.execute(
                    "SELECT key, value, pinned FROM memory WHERE key=?", (k,)
                ).fetchone()
                if row:
                    results.append({"key": row[0], "value": row[1], "pinned": bool(row[2])})
    except Exception:
        pass
    return results


def execute(args: dict) -> dict:
    op = args.get("operation", "").strip().lower()

    if op == "store":
        key = args.get("key", "").strip()
        value = args.get("value")
        if not key:
            return {"error": "store requires a key"}
        if value is None:
            return {"error": "store requires a value"}
        now = datetime.now(timezone.utc).isoformat()
        pin_arg = args.get("pin")
        with _connect() as conn:
            if pin_arg is not None:
                pin_val = 1 if pin_arg else 0
                conn.execute(
                    "INSERT INTO memory(key, value, pinned, updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, pinned=excluded.pinned, updated_at=excluded.updated_at",
                    (key, str(value), pin_val, now),
                )
            else:
                conn.execute(
                    "INSERT INTO memory(key, value, pinned, updated_at) VALUES(?,?,0,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, str(value), now),
                )
        result = {"stored": key}
        if pin_arg is not None:
            result["pinned"] = bool(pin_arg)
        return result

    if op == "recall":
        key = args.get("key", "").strip()
        if not key:
            return {"error": "recall requires a key"}
        with _connect() as conn:
            row = conn.execute(
                "SELECT value, updated_at, pinned FROM memory WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                pattern = f"%{key}%"
                rows = conn.execute(
                    "SELECT key, value, updated_at, pinned FROM memory "
                    "WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                    (pattern, pattern),
                ).fetchall()
                if not rows:
                    return {"error": f"no memory found for key: {key!r}"}
                return {
                    "note": "exact key not found, returning fuzzy matches",
                    "results": [{"key": r[0], "value": r[1], "updated_at": r[2], "pinned": bool(r[3])} for r in rows],
                }
        result = {"key": key, "value": row[0], "updated_at": row[1], "pinned": bool(row[2])}
        links = _follow_links(row[0])
        if links:
            result["links"] = links
        return result

    if op == "search":
        query = args.get("query", "").strip()
        if not query:
            return {"error": "search requires a query"}
        pattern = f"%{query}%"
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at, pinned FROM memory "
                "WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                (pattern, pattern),
            ).fetchall()
        results_list = []
        for r in rows:
            entry = {"key": r[0], "value": r[1], "updated_at": r[2], "pinned": bool(r[3])}
            links = _follow_links(r[1])
            if links:
                entry["links"] = links
            results_list.append(entry)
        return {"query": query, "results": results_list}

    if op == "list":
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key, updated_at, pinned FROM memory ORDER BY pinned DESC, updated_at DESC"
            ).fetchall()
        return {"keys": [{"key": r[0], "updated_at": r[1], "pinned": bool(r[2])} for r in rows]}

    if op == "delete":
        key = args.get("key", "").strip()
        if not key:
            return {"error": "delete requires a key"}
        with _connect() as conn:
            cur = conn.execute("DELETE FROM memory WHERE key=?", (key,))
        if cur.rowcount == 0:
            return {"error": f"no memory found for key: {key!r}"}
        return {"deleted": key}

    return {"error": f"unknown operation: {op!r}. Use store, recall, search, list, or delete"}
