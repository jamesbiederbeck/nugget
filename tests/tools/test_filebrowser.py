import pytest
from nugget.tools.filebrowser import execute, APPROVAL


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------

def test_cwd():
    result = execute({"operation": "cwd"})
    assert "cwd" in result
    assert isinstance(result["cwd"], str)


def test_ls_current_dir(tmp_path):
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()
    result = execute({"operation": "ls", "path": str(tmp_path)})
    assert "entries" in result
    names = [e["name"] for e in result["entries"]]
    assert "file.txt" in names
    assert "subdir" in names


def test_ls_entry_types(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    (tmp_path / "d").mkdir()
    result = execute({"operation": "ls", "path": str(tmp_path)})
    by_name = {e["name"]: e for e in result["entries"]}
    assert by_name["f.txt"]["type"] == "file"
    assert by_name["d"]["type"] == "dir"


def test_ls_missing_path():
    result = execute({"operation": "ls", "path": "/nonexistent_path_xyz"})
    assert "error" in result


def test_ls_file_as_dir(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("data")
    result = execute({"operation": "ls", "path": str(f)})
    assert "error" in result


def test_cat_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    result = execute({"operation": "cat", "path": str(f)})
    assert result["content"] == "hello world"
    assert result["size"] == 11


def test_cat_missing_file():
    result = execute({"operation": "cat", "path": "/nonexistent_file_xyz.txt"})
    assert "error" in result


def test_cat_directory(tmp_path):
    result = execute({"operation": "cat", "path": str(tmp_path)})
    assert "error" in result


def test_cat_no_path():
    result = execute({"operation": "cat"})
    assert "error" in result


def test_unknown_operation():
    result = execute({"operation": "upload"})
    assert "error" in result


# ---------------------------------------------------------------------------
# APPROVAL gate
# ---------------------------------------------------------------------------

def test_approval_read_ops_are_allow():
    for op in ("cwd", "ls", "cat", "read_lines", "stat", "glob"):
        assert APPROVAL({"operation": op}) == "allow", f"expected allow for {op}"


def test_approval_write_ops_are_ask():
    for op in ("write", "append", "replace", "backup", "restore_backup", "mkdir", "move"):
        assert APPROVAL({"operation": op}) == "ask", f"expected ask for {op}"


def test_approval_unknown_op_is_ask():
    assert APPROVAL({"operation": "frobnicate"}) == "ask"


# ---------------------------------------------------------------------------
# read_lines
# ---------------------------------------------------------------------------

def test_read_lines_basic(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = execute({"operation": "read_lines", "path": str(f), "start": 2, "end": 4})
    assert "error" not in result
    assert result["start"] == 2
    assert result["end"] == 4
    assert result["total_lines"] == 5
    assert len(result["lines"]) == 3
    assert result["lines"][0].rstrip() == "b"


def test_read_lines_no_end(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = execute({"operation": "read_lines", "path": str(f), "start": 3})
    assert result["end"] == result["total_lines"]
    assert len(result["lines"]) == 3


def test_read_lines_start_beyond_eof(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\n")
    result = execute({"operation": "read_lines", "path": str(f), "start": 100})
    assert "error" not in result
    assert result["lines"] == []


def test_read_lines_end_clamped(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\nc\n")
    result = execute({"operation": "read_lines", "path": str(f), "start": 1, "end": 9999})
    assert result["end"] == 3


def test_read_lines_missing_file():
    result = execute({"operation": "read_lines", "path": "/no/such/file.txt", "start": 1})
    assert "error" in result


def test_read_lines_missing_start(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("x\n")
    result = execute({"operation": "read_lines", "path": str(f)})
    assert "error" in result


# ---------------------------------------------------------------------------
# stat
# ---------------------------------------------------------------------------

def test_stat_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello")
    result = execute({"operation": "stat", "path": str(f)})
    assert "error" not in result
    assert result["is_file"] is True
    assert result["is_dir"] is False
    assert result["size"] == 5
    assert "mtime_iso" in result
    assert "permissions_octal" in result


def test_stat_directory(tmp_path):
    result = execute({"operation": "stat", "path": str(tmp_path)})
    assert result["is_dir"] is True
    assert result["is_file"] is False


def test_stat_missing():
    result = execute({"operation": "stat", "path": "/no/such/path_xyz"})
    assert "error" in result


# ---------------------------------------------------------------------------
# glob
# ---------------------------------------------------------------------------

def test_glob_finds_by_extension(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "b.txt").write_text("")
    (tmp_path / "c.py").write_text("")
    result = execute({"operation": "glob", "path": str(tmp_path), "pattern": "*.txt"})
    assert "error" not in result
    assert len(result["matches"]) == 2
    assert result["truncated"] is False


def test_glob_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "a.py").write_text("")
    (sub / "b.py").write_text("")
    result = execute({"operation": "glob", "path": str(tmp_path), "pattern": "**/*.py"})
    assert len(result["matches"]) == 2


def test_glob_no_matches(tmp_path):
    result = execute({"operation": "glob", "path": str(tmp_path), "pattern": "*.xyz"})
    assert "error" not in result
    assert result["matches"] == []


def test_glob_missing_pattern(tmp_path):
    result = execute({"operation": "glob", "path": str(tmp_path)})
    assert "error" in result


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

def test_write_creates_new_file(tmp_path):
    f = tmp_path / "new.txt"
    result = execute({"operation": "write", "path": str(f), "content": "hello"})
    assert "error" not in result
    assert result["created"] is True
    assert f.read_text() == "hello"


def test_write_overwrites_existing(tmp_path):
    f = tmp_path / "existing.txt"
    f.write_text("old")
    result = execute({"operation": "write", "path": str(f), "content": "new"})
    assert result["created"] is False
    assert f.read_text() == "new"


def test_write_returns_size(tmp_path):
    f = tmp_path / "f.txt"
    result = execute({"operation": "write", "path": str(f), "content": "abc"})
    assert result["size"] == 3


def test_write_missing_parent(tmp_path):
    f = tmp_path / "no_such_dir" / "f.txt"
    result = execute({"operation": "write", "path": str(f), "content": "x"})
    assert "error" in result


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------

def test_append_to_existing(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello")
    execute({"operation": "append", "path": str(f), "content": " world"})
    assert f.read_text() == "hello world"


def test_append_creates_file(tmp_path):
    f = tmp_path / "new.txt"
    result = execute({"operation": "append", "path": str(f), "content": "hi"})
    assert "error" not in result
    assert f.read_text() == "hi"


def test_append_returns_size(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("ab")
    result = execute({"operation": "append", "path": str(f), "content": "cd"})
    assert result["size"] == 4


# ---------------------------------------------------------------------------
# replace
# ---------------------------------------------------------------------------

def test_replace_basic(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello world")
    result = execute({"operation": "replace", "path": str(f), "old": "hello", "new": "goodbye"})
    assert result["replacements"] == 1
    assert f.read_text() == "goodbye world"


def test_replace_count_limits(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("aaa")
    result = execute({"operation": "replace", "path": str(f), "old": "a", "new": "b", "count": 2})
    assert result["replacements"] == 2
    assert f.read_text() == "bba"


def test_replace_all_with_minus_one(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("aaa")
    result = execute({"operation": "replace", "path": str(f), "old": "a", "new": "b", "count": -1})
    assert result["replacements"] == 3
    assert f.read_text() == "bbb"


def test_replace_not_found(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello")
    result = execute({"operation": "replace", "path": str(f), "old": "xyz", "new": "abc"})
    assert "error" in result
    assert f.read_text() == "hello"  # file unchanged


def test_replace_empty_old_rejected(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello")
    result = execute({"operation": "replace", "path": str(f), "old": "", "new": "x"})
    assert "error" in result


def test_replace_missing_file():
    result = execute({"operation": "replace", "path": "/no/file.txt", "old": "a", "new": "b"})
    assert "error" in result


def test_replace_delete_via_empty_new(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("remove this here")
    result = execute({"operation": "replace", "path": str(f), "old": "remove this ", "new": ""})
    assert result["replacements"] == 1
    assert f.read_text() == "here"


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------

def test_mkdir_creates(tmp_path):
    d = tmp_path / "newdir"
    result = execute({"operation": "mkdir", "path": str(d)})
    assert result["created"] is True
    assert d.is_dir()


def test_mkdir_existing(tmp_path):
    d = tmp_path / "existing"
    d.mkdir()
    result = execute({"operation": "mkdir", "path": str(d)})
    assert "error" not in result
    assert result["created"] is False


def test_mkdir_parents_true(tmp_path):
    d = tmp_path / "a" / "b" / "c"
    result = execute({"operation": "mkdir", "path": str(d), "parents": True})
    assert "error" not in result
    assert d.is_dir()


def test_mkdir_parents_false_missing_intermediate(tmp_path):
    d = tmp_path / "a" / "b" / "c"
    result = execute({"operation": "mkdir", "path": str(d), "parents": False})
    assert "error" in result


# ---------------------------------------------------------------------------
# move
# ---------------------------------------------------------------------------

def test_move_file(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("content")
    dest = tmp_path / "dest.txt"
    result = execute({"operation": "move", "path": str(src), "dest": str(dest)})
    assert "error" not in result
    assert not src.exists()
    assert dest.read_text() == "content"


def test_move_missing_dest_parent(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("x")
    result = execute({"operation": "move", "path": str(src), "dest": str(tmp_path / "nope" / "dest.txt")})
    assert "error" in result


def test_move_missing_source(tmp_path):
    result = execute({"operation": "move", "path": str(tmp_path / "ghost.txt"), "dest": str(tmp_path / "out.txt")})
    assert "error" in result


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

def test_backup_auto_dest(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("original")
    result = execute({"operation": "backup", "path": str(f)})
    assert "error" not in result
    backup = result["backup_path"]
    assert "data.txt" in backup
    assert backup.startswith("/tmp/nugget/backups/")
    assert f.read_text() == "original"  # source unchanged
    from pathlib import Path as P
    assert P(backup).read_text() == "original"


def test_backup_explicit_dest(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hi")
    dest = tmp_path / "my.bak"
    result = execute({"operation": "backup", "path": str(f), "dest": str(dest)})
    assert result["backup_path"] == str(dest)
    assert dest.read_text() == "hi"


def test_backup_missing_source(tmp_path):
    result = execute({"operation": "backup", "path": str(tmp_path / "ghost.txt")})
    assert "error" in result


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------

def test_restore_backup_basic(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("original")
    bak = tmp_path / "file.bak"
    execute({"operation": "backup", "path": str(f), "dest": str(bak)})
    f.write_text("modified")
    result = execute({"operation": "restore_backup", "path": str(f), "backup_path": str(bak)})
    assert "error" not in result
    assert f.read_text() == "original"


def test_restore_backup_preserves_backup(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("data")
    bak = tmp_path / "file.bak"
    execute({"operation": "backup", "path": str(f), "dest": str(bak)})
    execute({"operation": "restore_backup", "path": str(f), "backup_path": str(bak)})
    assert bak.exists()  # backup not deleted


def test_restore_backup_missing_backup(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    result = execute({"operation": "restore_backup", "path": str(f), "backup_path": str(tmp_path / "no.bak")})
    assert "error" in result
