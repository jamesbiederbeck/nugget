"""Tests for SlashCommandCompleter."""

import pytest
from prompt_toolkit.document import Document
from nugget.completer import SlashCommandCompleter
from nugget.commands import COMMAND_DESCRIPTIONS


@pytest.fixture
def completer():
    return SlashCommandCompleter(COMMAND_DESCRIPTIONS)


def _complete(completer, text):
    doc = Document(text, cursor_position=len(text))
    return list(completer.get_completions(doc, None))


def test_slash_prefix_returns_all_commands(completer):
    results = _complete(completer, "/")
    names = [c.text for c in results]
    assert "/profile" in names
    assert "/help" in names
    assert "/exit" in names


def test_partial_slash_filters_correctly(completer):
    results = _complete(completer, "/pr")
    names = [c.text for c in results]
    assert "/profile" in names
    assert "/prompt" in names
    # should not include unrelated commands
    assert "/exit" not in names


def test_completions_have_display_meta(completer):
    results = _complete(completer, "/p")
    assert all(c.display_meta for c in results)


def test_space_after_command_yields_nothing(completer):
    results = _complete(completer, "/profile ")
    assert results == []


def test_non_slash_input_yields_nothing(completer):
    results = _complete(completer, "hello")
    assert results == []


def test_empty_input_yields_nothing(completer):
    results = _complete(completer, "")
    assert results == []
