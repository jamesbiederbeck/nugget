import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path.home() / ".local" / "share" / "nugget" / "tasks.db"


def APPROVAL(args: dict) -> str:
    return "ask" if args.get("operation") == "delete" else "allow"


SCHEMA = {
    "type": "function",
    "function": {
        "name": "tasks",
        "description": (
            "Persistent task list across conversations. "
            "Operations: "
            "'add' creates a new task; "
            "'list' returns tasks (optionally filtered by tag or status); "
            "'complete' marks a task done; "
            "'update' changes a task's text or tag; "
            "'delete' permanently removes a task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of: 'add', 'list', 'complete', 'update', 'delete'",
                },
                "text": {
                    "type": "string",
                    "description": "Task description (required for add; optional for update)",
                },
                "id": {
                    "type": "integer",
                    "description": "Task id (required for complete, update, delete)",
                },
                "tag": {
                    "type": "string",
                    "description": "Project/group label for filtering (optional)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter for list: 'open' (default), 'done', or 'all'",
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
        CREATE TABLE IF NOT EXISTS tasks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text       TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'open',
            tag        TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _row(r: tuple) -> dict:
    return {"id": r[0], "text": r[1], "status": r[2], "tag": r[3], "created_at": r[4]}


def execute(args: dict) -> dict:
    op = args.get("operation", "").strip().lower()

    if op == "add":
        text = args.get("text", "").strip()
        if not text:
            return {"error": "add requires text"}
        tag = args.get("tag")
        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks(text, status, tag, created_at) VALUES(?,?,?,?)",
                (text, "open", tag, now),
            )
        return {"id": cur.lastrowid, "text": text, "tag": tag, "created_at": now}

    if op == "list":
        status_filter = args.get("status", "open").lower()
        tag_filter = args.get("tag")
        sql = "SELECT id, text, status, tag, created_at FROM tasks"
        params: list = []
        conditions = []
        if status_filter != "all":
            conditions.append("status=?")
            params.append(status_filter)
        if tag_filter:
            conditions.append("tag=?")
            params.append(tag_filter)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id"
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {"tasks": [_row(r) for r in rows]}

    if op == "complete":
        task_id = args.get("id")
        if task_id is None:
            return {"error": "complete requires id"}
        with _connect() as conn:
            cur = conn.execute("UPDATE tasks SET status='done' WHERE id=?", (task_id,))
        if cur.rowcount == 0:
            return {"error": f"no task with id {task_id}"}
        return {"id": task_id, "ok": True, "status": "done"}

    if op == "update":
        task_id = args.get("id")
        if task_id is None:
            return {"error": "update requires id"}
        sets, params = [], []
        if "text" in args:
            sets.append("text=?")
            params.append(args["text"])
        if "tag" in args:
            sets.append("tag=?")
            params.append(args["tag"])
        if not sets:
            return {"error": "update requires at least one of: text, tag"}
        params.append(task_id)
        with _connect() as conn:
            cur = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
        if cur.rowcount == 0:
            return {"error": f"no task with id {task_id}"}
        return {"id": task_id, "ok": True}

    if op == "delete":
        task_id = args.get("id")
        if task_id is None:
            return {"error": "delete requires id"}
        with _connect() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        if cur.rowcount == 0:
            return {"error": f"no task with id {task_id}"}
        return {"id": task_id, "deleted": True}

    return {"error": f"unknown operation: {op!r}. Use add, list, complete, update, or delete"}
