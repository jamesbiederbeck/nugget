import pytest
from nugget.tools.filebrowser import execute


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
