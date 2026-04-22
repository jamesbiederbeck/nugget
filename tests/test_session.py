import json
import time
import pytest
from nugget.session import Session


def test_new_session_has_id(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    assert len(s.id) == 8
    assert s.messages == []


def test_add_user_message(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_user("hello")
    assert len(s.messages) == 1
    assert s.messages[0] == {"role": "user", "content": "hello"}


def test_add_assistant_message(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_assistant("hi there")
    msg = s.messages[0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "hi there"
    assert "thinking" not in msg
    assert "tool_calls" not in msg


def test_add_assistant_with_thinking(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_assistant("response", thinking="I thought about it")
    assert s.messages[0]["thinking"] == "I thought about it"


def test_add_assistant_with_tool_calls(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    calls = [{"name": "shell", "args": {"command": "ls"}, "result": {"stdout": ""}}]
    s.add_assistant("done", tool_calls=calls)
    assert s.messages[0]["tool_calls"] == calls


def test_save_and_load_roundtrip(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_user("question")
    s.add_assistant("answer")
    s.save()

    loaded = Session.load(s.id, tmp_sessions_dir)
    assert loaded.id == s.id
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["content"] == "question"
    assert loaded.messages[1]["content"] == "answer"


def test_save_updates_updated_at(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    before = s.updated_at
    time.sleep(0.01)
    s.add_user("hi")
    s.save()
    assert s.updated_at > before


def test_load_nonexistent_session(tmp_sessions_dir):
    # Loading a session that doesn't exist returns an empty session
    s = Session.load("fakeid", tmp_sessions_dir)
    assert s.messages == []
    assert s.id == "fakeid"


def test_list_sessions(tmp_sessions_dir):
    s1 = Session.new(tmp_sessions_dir)
    s1.add_user("first question")
    s1.save()

    s2 = Session.new(tmp_sessions_dir)
    s2.add_user("second question")
    s2.save()

    sessions = Session.list_sessions(tmp_sessions_dir)
    assert len(sessions) == 2
    ids = [s["id"] for s in sessions]
    assert s1.id in ids
    assert s2.id in ids


def test_list_sessions_preview(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_user("what is the meaning of life")
    s.save()

    sessions = Session.list_sessions(tmp_sessions_dir)
    assert sessions[0]["preview"].startswith("what is the meaning")


def test_list_sessions_turn_count(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.add_user("q1")
    s.add_assistant("a1")
    s.add_user("q2")
    s.add_assistant("a2")
    s.save()

    sessions = Session.list_sessions(tmp_sessions_dir)
    assert sessions[0]["turns"] == 2


def test_list_sessions_empty_dir(tmp_sessions_dir):
    assert Session.list_sessions(tmp_sessions_dir) == []


def test_session_file_path(tmp_sessions_dir):
    s = Session.new(tmp_sessions_dir)
    s.save()
    assert (tmp_sessions_dir / f"{s.id}.json").exists()
