import hashlib
import sqlite3
from pathlib import Path

_SCHEMA = Path(__file__).parent / "schema.sql"


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA.read_text())


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def upsert_system_prompt(conn: sqlite3.Connection, text: str) -> int:
    h = sha256(text)
    conn.execute("INSERT OR IGNORE INTO system_prompt(hash, text) VALUES (?, ?)", (h, text))
    conn.commit()
    return conn.execute("SELECT id FROM system_prompt WHERE hash = ?", (h,)).fetchone()[0]


def upsert_user_prompt(conn: sqlite3.Connection, text: str) -> int:
    h = sha256(text)
    conn.execute("INSERT OR IGNORE INTO user_prompt(hash, text) VALUES (?, ?)", (h, text))
    conn.commit()
    return conn.execute("SELECT id FROM user_prompt WHERE hash = ?", (h,)).fetchone()[0]


def upsert_model(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO model(name) VALUES (?)", (name,))
    conn.commit()
    return conn.execute("SELECT id FROM model WHERE name = ? COLLATE NOCASE", (name,)).fetchone()[0]


def insert_run(conn: sqlite3.Connection, name: str | None, notes: str | None) -> int:
    cur = conn.execute("INSERT INTO run(name, notes) VALUES (?, ?)", (name, notes))
    conn.commit()
    return cur.lastrowid


def insert_response(
    conn: sqlite3.Connection,
    *,
    hash: str,
    text: str,
    thinking: str | None,
    tool_calls_json: str | None,
    stop_strings_json: str | None,
    finish_reason: str | None,
    temperature: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None,
    model_id: int,
    system_prompt_id: int,
    user_prompt_id: int,
    run_id: int | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO response(
            hash, text, thinking, tool_calls, stop_strings, finish_reason,
            temperature, prompt_tokens, completion_tokens, latency_ms,
            model_id, system_prompt_id, user_prompt_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hash, text, thinking, tool_calls_json, stop_strings_json, finish_reason,
            temperature, prompt_tokens, completion_tokens, latency_ms,
            model_id, system_prompt_id, user_prompt_id, run_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_test_result(
    conn: sqlite3.Connection,
    *,
    passed: int,
    extracted_value: str | None,
    system_prompt_id: int,
    user_prompt_id: int,
    response_id: int,
    test_case_id: int,
    run_id: int | None,
) -> None:
    conn.execute(
        """
        INSERT INTO test_result(
            passed, extracted_value,
            system_prompt_id, user_prompt_id,
            response_id, test_case_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (passed, extracted_value, system_prompt_id, user_prompt_id,
         response_id, test_case_id, run_id),
    )
    conn.commit()
