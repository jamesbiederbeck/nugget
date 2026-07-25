import json

from nugget.backends import render_request
from nugget.backends.textgen import TextgenBackend
from nugget.backends.openrouter import OpenRouterBackend
from nugget.config import Config


def _textgen_backend():
    return TextgenBackend(Config({"backend": "textgen", "api_url": "http://127.0.0.1:5000"}))


def _openrouter_backend():
    return OpenRouterBackend(Config({"backend": "openrouter", "openrouter_api_key": "x"}))


def test_render_request_textgen_matches_build_prompt():
    from nugget.backends.textgen import build_prompt

    backend = _textgen_backend()
    messages = [{"role": "user", "content": "hi"}]
    rendered = render_request(backend, messages, [], "You are helpful.", 0)
    assert rendered == build_prompt(messages, [], "You are helpful.", 0)
    assert "<|turn>system" in rendered
    assert "hi" in rendered


def test_render_request_textgen_with_attachment_uses_chat_json():
    backend = _textgen_backend()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_0",
                    "name": "cat",
                    "args": {},
                    "result": {
                        "_attachment": True,
                        "images": [{"mime": "image/png", "data_b64": "eA=="}],
                    },
                }
            ],
        }
    ]
    rendered = render_request(backend, messages, [], "sys", 0)
    parsed = json.loads(rendered)
    assert parsed[0] == {"role": "system", "content": "sys"}


def test_render_request_openrouter_is_json_messages():
    backend = _openrouter_backend()
    messages = [{"role": "user", "content": "hello"}]
    rendered = render_request(backend, messages, [], "sys prompt", 0)
    parsed = json.loads(rendered)
    assert parsed[0] == {"role": "system", "content": "sys prompt"}
    assert parsed[1] == {"role": "user", "content": "hello"}
