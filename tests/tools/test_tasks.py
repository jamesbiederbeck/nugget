import pytest
from nugget.tools.tasks import execute, APPROVAL


# ── APPROVAL gate ─────────────────────────────────────────────────────────────

def test_approval_delete():
    assert APPROVAL({"operation": "delete"}) == "ask"

def test_approval_add():
    assert APPROVAL({"operation": "add"}) == "allow"

def test_approval_list():
    assert APPROVAL({"operation": "list"}) == "allow"

def test_approval_complete():
    assert APPROVAL({"operation": "complete"}) == "allow"


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_returns_id(tmp_tasks_db):
    result = execute({"operation": "add", "text": "write tests"})
    assert "id" in result
    assert result["text"] == "write tests"
    assert result["tag"] is None


def test_add_with_tag(tmp_tasks_db):
    result = execute({"operation": "add", "text": "fix bug", "tag": "nugget"})
    assert result["tag"] == "nugget"


def test_add_ids_increment(tmp_tasks_db):
    r1 = execute({"operation": "add", "text": "first"})
    r2 = execute({"operation": "add", "text": "second"})
    assert r2["id"] == r1["id"] + 1


def test_add_missing_text(tmp_tasks_db):
    result = execute({"operation": "add"})
    assert "error" in result


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_returns_open_by_default(tmp_tasks_db):
    execute({"operation": "add", "text": "open task"})
    result = execute({"operation": "list"})
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["status"] == "open"


def test_list_all(tmp_tasks_db):
    r = execute({"operation": "add", "text": "t"})
    execute({"operation": "complete", "id": r["id"]})
    execute({"operation": "add", "text": "t2"})
    result = execute({"operation": "list", "status": "all"})
    assert len(result["tasks"]) == 2


def test_list_done(tmp_tasks_db):
    r = execute({"operation": "add", "text": "done task"})
    execute({"operation": "complete", "id": r["id"]})
    execute({"operation": "add", "text": "open task"})
    result = execute({"operation": "list", "status": "done"})
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["status"] == "done"


def test_list_filter_by_tag(tmp_tasks_db):
    execute({"operation": "add", "text": "a", "tag": "frontend"})
    execute({"operation": "add", "text": "b", "tag": "backend"})
    result = execute({"operation": "list", "tag": "frontend"})
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["tag"] == "frontend"


def test_list_empty(tmp_tasks_db):
    result = execute({"operation": "list"})
    assert result["tasks"] == []


# ── complete ──────────────────────────────────────────────────────────────────

def test_complete(tmp_tasks_db):
    r = execute({"operation": "add", "text": "finish me"})
    result = execute({"operation": "complete", "id": r["id"]})
    assert result["ok"] is True
    assert result["status"] == "done"
    listed = execute({"operation": "list", "status": "done"})
    assert any(t["id"] == r["id"] for t in listed["tasks"])


def test_complete_missing_id(tmp_tasks_db):
    result = execute({"operation": "complete"})
    assert "error" in result


def test_complete_nonexistent_id(tmp_tasks_db):
    result = execute({"operation": "complete", "id": 9999})
    assert "error" in result


# ── update ────────────────────────────────────────────────────────────────────

def test_update_text(tmp_tasks_db):
    r = execute({"operation": "add", "text": "old text"})
    execute({"operation": "update", "id": r["id"], "text": "new text"})
    tasks = execute({"operation": "list"})["tasks"]
    assert tasks[0]["text"] == "new text"


def test_update_tag(tmp_tasks_db):
    r = execute({"operation": "add", "text": "task", "tag": "alpha"})
    execute({"operation": "update", "id": r["id"], "tag": "beta"})
    tasks = execute({"operation": "list"})["tasks"]
    assert tasks[0]["tag"] == "beta"


def test_update_missing_id(tmp_tasks_db):
    result = execute({"operation": "update", "text": "x"})
    assert "error" in result


def test_update_no_fields(tmp_tasks_db):
    r = execute({"operation": "add", "text": "task"})
    result = execute({"operation": "update", "id": r["id"]})
    assert "error" in result


def test_update_nonexistent_id(tmp_tasks_db):
    result = execute({"operation": "update", "id": 9999, "text": "x"})
    assert "error" in result


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete(tmp_tasks_db):
    r = execute({"operation": "add", "text": "remove me"})
    result = execute({"operation": "delete", "id": r["id"]})
    assert result["deleted"] is True
    listed = execute({"operation": "list", "status": "all"})
    assert not any(t["id"] == r["id"] for t in listed["tasks"])


def test_delete_missing_id(tmp_tasks_db):
    result = execute({"operation": "delete"})
    assert "error" in result


def test_delete_nonexistent_id(tmp_tasks_db):
    result = execute({"operation": "delete", "id": 9999})
    assert "error" in result


# ── unknown op ────────────────────────────────────────────────────────────────

def test_unknown_operation(tmp_tasks_db):
    result = execute({"operation": "frobble"})
    assert "error" in result
