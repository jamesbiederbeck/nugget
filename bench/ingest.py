import csv
import hashlib
import sqlite3
import sys
from pathlib import Path

import db as bench_db


def constraint_hash(constraint_type: str, constraint_value: str, target: str) -> str:
    raw = f"{constraint_type}:{constraint_value}:{target}"
    return hashlib.sha256(raw.encode()).hexdigest()


def ingest_cases(conn: sqlite3.Connection, tsv_path: Path) -> dict[str, list[tuple[str, int]]]:
    """
    Idempotent: upserts user_prompts and test_cases from the TSV.

    Returns {prompt_id: [(test_case_name, test_case_id), ...]} for the runner.
    Warns to stderr if a test_case row appears to have been edited in place
    (constraint_hash mismatch). In that case the existing id is reused and
    historical test_result rows remain associated with the old constraint.
    """
    with open(tsv_path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    prompt_to_cases: dict[str, list[tuple[str, int]]] = {}

    for row in rows:
        case_name      = row["id"]
        prompt_id      = row["prompt_id"]
        prompt_text    = row["prompt"]
        constraint_type  = row["constraint_type"]
        constraint_value = row["constraint_value"] or None  # empty string → NULL
        target         = row["target"]
        notes          = row.get("notes") or None

        bench_db.upsert_user_prompt(conn, prompt_text)

        ch = constraint_hash(constraint_type, constraint_value or "", target)

        existing = conn.execute(
            "SELECT id, constraint_hash FROM test_case WHERE name = ?", (case_name,)
        ).fetchone()

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO test_case(name, constraint_type, constraint_value, constraint_hash, target, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case_name, constraint_type, constraint_value, ch, target, notes),
            )
            conn.commit()
            test_case_id = cur.lastrowid
        else:
            if existing["constraint_hash"] != ch:
                print(
                    f"WARNING: test_case '{case_name}' was edited in place "
                    f"(constraint_hash mismatch). Historical results are now ambiguous. "
                    f"Create a new test_case name instead of editing in place.",
                    file=sys.stderr,
                )
            test_case_id = existing["id"]

        prompt_to_cases.setdefault(prompt_id, []).append((case_name, test_case_id))

    return prompt_to_cases
