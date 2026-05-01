import subprocess
import pytest
from nugget.tools.grep_search import execute


def test_basic_match(tmp_path):
    (tmp_path / "foo.py").write_text("def hello():\n    pass\n")
    result = execute({"pattern": "hello", "path": str(tmp_path)})
    assert result["count"] == 1
    assert "hello" in result["matches"][0]
    assert not result["truncated"]


def test_no_match(tmp_path):
    (tmp_path / "bar.py").write_text("nothing here\n")
    result = execute({"pattern": "xyzzy_not_present", "path": str(tmp_path)})
    assert result["count"] == 0
    assert result["matches"] == []


def test_case_insensitive_default(tmp_path):
    (tmp_path / "f.py").write_text("HELLO world\n")
    result = execute({"pattern": "hello", "path": str(tmp_path)})
    assert result["count"] == 1


def test_case_sensitive(tmp_path):
    (tmp_path / "f.py").write_text("HELLO world\n")
    result = execute({"pattern": "hello", "path": str(tmp_path), "case_sensitive": True})
    assert result["count"] == 0


def test_include_glob(tmp_path):
    (tmp_path / "match.py").write_text("target\n")
    (tmp_path / "skip.txt").write_text("target\n")
    result = execute({"pattern": "target", "path": str(tmp_path), "include": "*.py"})
    assert result["count"] == 1
    assert "match.py" in result["matches"][0]


def test_missing_pattern():
    result = execute({})
    assert "error" in result


def test_invalid_path():
    result = execute({"pattern": "hello", "path": "/nonexistent/path/xyz"})
    assert "error" in result


def test_max_results(tmp_path):
    (tmp_path / "many.txt").write_text("\n".join(["hit"] * 20))
    result = execute({"pattern": "hit", "path": str(tmp_path), "max_results": 5})
    assert result["count"] <= 5
    assert result["truncated"]


def test_rg_not_found(mocker):
    mocker.patch("subprocess.run", side_effect=FileNotFoundError)
    result = execute({"pattern": "foo"})
    assert "error" in result
    assert "ripgrep" in result["error"]


def test_timeout(mocker):
    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["rg"], 15))
    result = execute({"pattern": "foo"})
    assert "error" in result
    assert "timed out" in result["error"]


def test_result_contains_file_and_line(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\ny = target\nz = 3\n")
    result = execute({"pattern": "target", "path": str(tmp_path)})
    assert result["count"] == 1
    # rg --line-number --no-heading format: file:line:content
    assert "2" in result["matches"][0]
