"""
Persistent memory backed by SQLite at ~/.local/share/gemma/memory.db.
Operations: store, recall, search, list, delete
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path.home() / ".local" / "share" / "gemma" / "memory.db"

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
            "'delete' removes a key."
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
                    "description": "Value to store (required for store)",
                },
                "query": {
                    "type": "string",
                    "description": "Substring to search for (required for search)",
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
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


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
        with _connect() as conn:
            conn.execute(
                "INSERT INTO memory(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, str(value), now),
            )
        return {"stored": key}

    if op == "recall":
        key = args.get("key", "").strip()
        if not key:
            return {"error": "recall requires a key"}
        with _connect() as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM memory WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                # Fuzzy fallback: search key and value
                pattern = f"%{key}%"
                rows = conn.execute(
                    "SELECT key, value, updated_at FROM memory "
                    "WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                    (pattern, pattern),
                ).fetchall()
                if not rows:
                    return {"error": f"no memory found for key: {key!r}"}
                return {
                    "note": "exact key not found, returning fuzzy matches",
                    "results": [{"key": r[0], "value": r[1], "updated_at": r[2]} for r in rows],
                }
        return {"key": key, "value": row[0], "updated_at": row[1]}

    if op == "search":
        query = args.get("query", "").strip()
        if not query:
            return {"error": "search requires a query"}
        pattern = f"%{query}%"
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at FROM memory "
                "WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC",
                (pattern, pattern),
            ).fetchall()
        return {
            "query": query,
            "results": [{"key": r[0], "value": r[1], "updated_at": r[2]} for r in rows],
        }

    if op == "list":
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key, updated_at FROM memory ORDER BY updated_at DESC"
            ).fetchall()
        return {"keys": [{"key": r[0], "updated_at": r[1]} for r in rows]}

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
