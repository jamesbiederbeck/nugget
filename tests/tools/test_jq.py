import json
import pytest
from nugget.tools.jq import execute


# ── Basic queries ─────────────────────────────────────────────────────────────

def test_simple_key_from_string():
    data = json.dumps({"name": "nugget", "version": "0.3.0"})
    result = execute({"data": data, "query": "name"})
    assert result["result"] == "nugget"
    assert result["query"] == "name"


def test_simple_key_from_dict():
    result = execute({"data": {"name": "nugget"}, "query": "name"})
    assert result["result"] == "nugget"


def test_nested_key():
    data = json.dumps({"a": {"b": {"c": 42}}})
    result = execute({"data": data, "query": "a.b.c"})
    assert result["result"] == 42


def test_list_filter():
    data = json.dumps({"items": [{"status": "open", "id": 1}, {"status": "done", "id": 2}]})
    result = execute({"data": data, "query": "items[?status=='open'].id"})
    assert result["result"] == [1]


def test_returns_none_for_missing_key():
    data = json.dumps({"a": 1})
    result = execute({"data": data, "query": "b"})
    assert result["result"] is None


def test_list_input():
    result = execute({"data": [1, 2, 3], "query": "[1]"})
    assert result["result"] == 2


# ── Error cases ───────────────────────────────────────────────────────────────

def test_invalid_json_string():
    result = execute({"data": "not valid json {{{", "query": "foo"})
    assert "error" in result
    assert "not valid JSON" in result["error"]


def test_invalid_jmespath():
    result = execute({"data": "{}", "query": "[[["})
    assert "error" in result
    assert "JMESPath" in result["error"]


def test_missing_data():
    result = execute({"query": "foo"})
    assert "error" in result


def test_missing_query():
    result = execute({"data": "{}"})
    assert "error" in result


def test_empty_query():
    result = execute({"data": "{}", "query": ""})
    assert "error" in result
