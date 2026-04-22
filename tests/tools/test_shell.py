import subprocess
import pytest
from unittest.mock import MagicMock
from nugget.tools.shell import execute


def test_success(mocker):
    mock_result = MagicMock()
    mock_result.stdout = "hello"
    mock_result.stderr = ""
    mock_result.returncode = 0
    mocker.patch("subprocess.run", return_value=mock_result)

    result = execute({"command": "echo hello"})
    assert result["stdout"] == "hello"
    assert result["stderr"] == ""
    assert result["returncode"] == 0


def test_nonzero_exit(mocker):
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = "not found"
    mock_result.returncode = 127
    mocker.patch("subprocess.run", return_value=mock_result)

    result = execute({"command": "badcmd"})
    assert result["returncode"] == 127
    assert result["stderr"] == "not found"


def test_timeout(mocker):
    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 5))
    result = execute({"command": "sleep 999", "timeout": 5})
    assert "error" in result
    assert "timed out" in result["error"]


def test_custom_timeout_passed(mocker):
    mock_run = mocker.patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0))
    execute({"command": "ls", "timeout": 30})
    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 30


def test_default_timeout_used(mocker):
    mock_run = mocker.patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0))
    execute({"command": "ls"})
    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 10


def test_exception_wrapped(mocker):
    mocker.patch("subprocess.run", side_effect=OSError("permission denied"))
    result = execute({"command": "restricted"})
    assert "error" in result


def test_missing_command_key():
    # Should not raise; command defaults to ""
    result = execute({})
    assert isinstance(result, dict)
