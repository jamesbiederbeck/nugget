import pytest
import requests
from unittest.mock import MagicMock
from nugget.tools.http_fetch import execute, APPROVAL


# ── APPROVAL gate ─────────────────────────────────────────────────────────────

def test_approval_get():
    assert APPROVAL({"method": "GET"}) == "allow"

def test_approval_head():
    assert APPROVAL({"method": "HEAD"}) == "allow"

def test_approval_default_is_get():
    assert APPROVAL({}) == "allow"

def test_approval_post():
    assert APPROVAL({"method": "POST"}) == "ask"

def test_approval_put():
    assert APPROVAL({"method": "PUT"}) == "ask"

def test_approval_delete():
    assert APPROVAL({"method": "DELETE"}) == "ask"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(text="hello", status=200, url="http://example.com", mocker=None):
    resp = MagicMock()
    resp.status_code = status
    resp.url = url
    resp.text = text
    resp.json.return_value = {"key": "value"}
    return resp


# ── Basic GET ─────────────────────────────────────────────────────────────────

def test_get_returns_content(mocker):
    mocker.patch("requests.request", return_value=_mock_response(text="body text"))
    result = execute({"url": "http://example.com"})
    assert result["status"] == 200
    assert result["content"] == "body text"
    assert not result["truncated"]


def test_get_truncates_at_max_chars(mocker):
    long_body = "x" * 10000
    mocker.patch("requests.request", return_value=_mock_response(text=long_body))
    result = execute({"url": "http://example.com", "max_chars": 100})
    assert len(result["content"]) == 100
    assert result["truncated"]


def test_as_json(mocker):
    mocker.patch("requests.request", return_value=_mock_response())
    result = execute({"url": "http://example.com", "as_json": True})
    assert "json" in result
    assert result["json"] == {"key": "value"}
    assert "content" not in result


def test_as_json_invalid(mocker):
    resp = _mock_response(text="not json")
    resp.json.side_effect = ValueError("no json")
    mocker.patch("requests.request", return_value=resp)
    result = execute({"url": "http://example.com", "as_json": True})
    assert "error" in result
    assert "content" in result


def test_url_forwarded(mocker):
    mock_req = mocker.patch("requests.request", return_value=_mock_response())
    execute({"url": "http://example.com/path"})
    args, kwargs = mock_req.call_args
    assert args[1] == "http://example.com/path"


def test_headers_forwarded(mocker):
    mock_req = mocker.patch("requests.request", return_value=_mock_response())
    execute({"url": "http://example.com", "headers": {"X-Foo": "bar"}})
    _, kwargs = mock_req.call_args
    assert kwargs["headers"]["X-Foo"] == "bar"


def test_missing_url():
    result = execute({})
    assert "error" in result


def test_timeout_error(mocker):
    mocker.patch("requests.request", side_effect=requests.exceptions.Timeout())
    result = execute({"url": "http://example.com"})
    assert "error" in result
    assert "timed out" in result["error"]


def test_connection_error(mocker):
    mocker.patch("requests.request", side_effect=requests.exceptions.ConnectionError("refused"))
    result = execute({"url": "http://example.com"})
    assert "error" in result
    assert "connection" in result["error"]
