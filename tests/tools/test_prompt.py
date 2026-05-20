"""Tests for the prompt tool."""

import sys
import pytest
from unittest.mock import patch
from nugget.tools.prompt import execute
from nugget import display


def test_missing_question():
    result = execute({})
    assert "error" in result
    assert "question" in result["error"]


def test_empty_question():
    result = execute({"question": "  "})
    assert "error" in result


def test_non_tty_returns_error(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    result = execute({"question": "Pick one"})
    assert "error" in result
    assert "tty" in result["error"].lower() or "terminal" in result["error"].lower()


def test_invalid_choices_type(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    result = execute({"question": "Pick one", "choices": "not-a-list"})
    assert "error" in result
    assert "list" in result["error"]


def test_display_has_prompt_user():
    # Catches the regression where display.prompt_user was missing,
    # causing an AttributeError when the prompt tool ran on a real tty.
    assert callable(getattr(display, "prompt_user", None)), \
        "display.prompt_user must exist and be callable"


def test_free_text_answer(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch("nugget.display.prompt_user", return_value="my answer") as mock_fn:
        result = execute({"question": "What is your name?"})
    assert result == {"answer": "my answer"}
    mock_fn.assert_called_once_with("What is your name?", None)


def test_choices_answer(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch("nugget.display.prompt_user", return_value="option B") as mock_fn:
        result = execute({"question": "Pick one", "choices": ["option A", "option B"]})
    assert result == {"answer": "option B"}
    mock_fn.assert_called_once_with("Pick one", ["option A", "option B"])
