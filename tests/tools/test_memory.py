import sqlite3
import pytest
from nugget.tools.memory import execute, get_pinned, _connect, _DB_PATH


def test_store_and_recall(tmp_memory_db):
    execute({"operation": "store", "key": "color", "value": "blue"})
    result = execute({"operation": "recall", "key": "color"})
    assert result["value"] == "blue"
    assert result["key"] == "color"


def test_store_overwrites(tmp_memory_db):
    execute({"operation": "store", "key": "x", "value": "first"})
    execute({"operation": "store", "key": "x", "value": "second"})
    result = execute({"operation": "recall", "key": "x"})
    assert result["value"] == "second"


def test_recall_missing_key(tmp_memory_db):
    result = execute({"operation": "recall", "key": "nonexistent_xyz"})
    assert "error" in result


def test_recall_fuzzy_fallback(tmp_memory_db):
    execute({"operation": "store", "key": "my_name", "value": "Victor"})
    result = execute({"operation": "recall", "key": "name"})
    assert "results" in result or result.get("value") == "Victor"


def test_search(tmp_memory_db):
    execute({"operation": "store", "key": "project", "value": "nugget cli"})
    execute({"operation": "store", "key": "other", "value": "something else"})
    result = execute({"operation": "search", "query": "nugget"})
    assert result["query"] == "nugget"
    keys = [r["key"] for r in result["results"]]
    assert "project" in keys
    assert "other" not in keys


def test_list(tmp_memory_db):
    execute({"operation": "store", "key": "a", "value": "1"})
    execute({"operation": "store", "key": "b", "value": "2"})
    result = execute({"operation": "list"})
    keys = [r["key"] for r in result["keys"]]
    assert "a" in keys
    assert "b" in keys


def test_delete(tmp_memory_db):
    execute({"operation": "store", "key": "temp", "value": "gone"})
    result = execute({"operation": "delete", "key": "temp"})
    assert result["deleted"] == "temp"
    recall = execute({"operation": "recall", "key": "temp"})
    assert "error" in recall


def test_delete_missing(tmp_memory_db):
    result = execute({"operation": "delete", "key": "no_such_key"})
    assert "error" in result


def test_unknown_operation(tmp_memory_db):
    result = execute({"operation": "explode"})
    assert "error" in result


def test_store_requires_key(tmp_memory_db):
    result = execute({"operation": "store", "value": "oops"})
    assert "error" in result


def test_store_requires_value(tmp_memory_db):
    result = execute({"operation": "store", "key": "k"})
    assert "error" in result


# ── Pin feature ───────────────────────────────────────────────────────────────

def test_pin_on_store(tmp_memory_db):
    execute({"operation": "store", "key": "pinned_key", "value": "pinned_val", "pin": True})
    result = execute({"operation": "recall", "key": "pinned_key"})
    assert result["pinned"] is True


def test_unpin(tmp_memory_db):
    execute({"operation": "store", "key": "pk", "value": "pv", "pin": True})
    execute({"operation": "store", "key": "pk", "value": "pv", "pin": False})
    result = execute({"operation": "recall", "key": "pk"})
    assert result["pinned"] is False


def test_get_pinned_empty(tmp_memory_db):
    execute({"operation": "store", "key": "unpinned", "value": "x"})
    assert get_pinned() == []


def test_get_pinned_returns_pinned(tmp_memory_db):
    execute({"operation": "store", "key": "name", "value": "Victor", "pin": True})
    execute({"operation": "store", "key": "other", "value": "nope"})
    pinned = get_pinned()
    assert len(pinned) == 1
    assert pinned[0]["key"] == "name"
    assert pinned[0]["value"] == "Victor"


def test_list_shows_pin_status(tmp_memory_db):
    execute({"operation": "store", "key": "p", "value": "v", "pin": True})
    execute({"operation": "store", "key": "u", "value": "w"})
    result = execute({"operation": "list"})
    by_key = {r["key"]: r for r in result["keys"]}
    assert by_key["p"]["pinned"] is True
    assert by_key["u"]["pinned"] is False


# ── Cross-linking ─────────────────────────────────────────────────────────────

def test_recall_resolves_link(tmp_memory_db):
    execute({"operation": "store", "key": "user-name", "value": "Victor"})
    execute({"operation": "store", "key": "user-editor", "value": "Neovim — see memory://user-name"})
    result = execute({"operation": "recall", "key": "user-editor"})
    assert "links" in result
    assert result["links"][0]["key"] == "user-name"
    assert result["links"][0]["value"] == "Victor"


def test_recall_link_depth_zero(tmp_memory_db):
    execute({"operation": "store", "key": "a", "value": "val — memory://b"})
    execute({"operation": "store", "key": "b", "value": "linked"})
    result = execute({"operation": "recall", "key": "a", "link_depth": 0})
    assert "links" not in result


def test_recall_link_depth_recursive(tmp_memory_db):
    execute({"operation": "store", "key": "c1", "value": "root — memory://c2"})
    execute({"operation": "store", "key": "c2", "value": "mid — memory://c3"})
    execute({"operation": "store", "key": "c3", "value": "leaf"})
    result = execute({"operation": "recall", "key": "c1", "link_depth": 2})
    assert result["links"][0]["key"] == "c2"
    assert result["links"][0]["links"][0]["key"] == "c3"


def test_recall_link_cycle_safe(tmp_memory_db):
    execute({"operation": "store", "key": "x", "value": "see memory://y"})
    execute({"operation": "store", "key": "y", "value": "see memory://x"})
    result = execute({"operation": "recall", "key": "x", "link_depth": 3})
    # Should not blow up; x links to y, y would link back to x but x is visited
    assert result["links"][0]["key"] == "y"
    assert "links" not in result["links"][0]


def test_search_resolves_links(tmp_memory_db):
    execute({"operation": "store", "key": "proj", "value": "nugget — memory://user-name"})
    execute({"operation": "store", "key": "user-name", "value": "Victor"})
    result = execute({"operation": "search", "query": "nugget"})
    proj = next(r for r in result["results"] if r["key"] == "proj")
    assert proj["links"][0]["key"] == "user-name"


def test_search_link_depth_zero(tmp_memory_db):
    execute({"operation": "store", "key": "k", "value": "val — memory://other"})
    execute({"operation": "store", "key": "other", "value": "linked"})
    result = execute({"operation": "search", "query": "val", "link_depth": 0})
    assert "links" not in result["results"][0]


# ── Schema migration ──────────────────────────────────────────────────────────

def test_schema_migration_adds_pinned_column(tmp_memory_db):
    # Create a DB with the old schema (no pinned column)
    conn = sqlite3.connect(tmp_memory_db)
    conn.execute("""
        CREATE TABLE memory (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("INSERT INTO memory(key, value, updated_at) VALUES('k','v','2024-01-01')")
    conn.commit()
    conn.close()

    # _connect() should migrate it
    with _connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memory)")}
    assert "pinned" in cols

    # Existing row should still be readable
    result = execute({"operation": "recall", "key": "k"})
    assert result["value"] == "v"
