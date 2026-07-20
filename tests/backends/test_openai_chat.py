import json

from nugget.backends import _openai_chat


def test_build_messages_plain_user_and_assistant():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = _openai_chat.build_messages(messages, "sys prompt")
    assert out[0] == {"role": "system", "content": "sys prompt"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2] == {"role": "assistant", "content": "hello"}


def test_build_messages_tool_call_without_attachment():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "calculator", "args": {"expression": "1+1"}, "result": {"value": 2}},
            ],
        },
    ]
    out = _openai_chat.build_messages(messages, "sys")
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert json.loads(tool_msgs[0]["content"]) == {"value": 2}


def test_build_messages_attachment_result_expands_to_stub_and_followup():
    attachment_result = {
        "_attachment": True,
        "images": [{"mime": "image/png", "data_b64": "AAAA", "source": "photo.png"}],
        "text": None,
    }
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "filebrowser", "args": {"operation": "cat", "path": "photo.png"},
                 "result": attachment_result},
            ],
        },
    ]
    out = _openai_chat.build_messages(messages, "sys")

    # system, assistant, tool-stub, synthetic user-with-image
    assert len(out) == 4
    tool_stub = out[2]
    assert tool_stub["role"] == "tool"
    assert tool_stub["tool_call_id"] == "call_1"
    stub_content = json.loads(tool_stub["content"])
    assert stub_content == {"attached": True, "image_count": 1}
    assert "AAAA" not in tool_stub["content"]  # base64 must never leak into the tool-role stub

    followup = out[3]
    assert followup["role"] == "user"
    assert isinstance(followup["content"], list)
    image_parts = [p for p in followup["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_build_messages_attachment_with_text_included_in_stub():
    attachment_result = {"_attachment": True, "images": [{"mime": "image/png", "data_b64": "AAAA", "source": "x.png"}],
                          "text": "some extracted text"}
    messages = [
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "call_1", "name": "pdf", "args": {"path": "x.pdf"}, "result": attachment_result}],
        },
    ]
    out = _openai_chat.build_messages(messages, "sys")
    stub_content = json.loads(out[2]["content"])
    assert stub_content["text"] == "some extracted text"


def test_build_messages_attachment_no_images_stays_plain_tool_message():
    # A pdf result with extractable text and no images should NOT trigger
    # the attachment-expansion path — it's plain text, just answer inline.
    result = {"_attachment": True, "images": [], "text": "full extracted text"}
    messages = [
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "call_1", "name": "pdf", "args": {"path": "x.pdf"}, "result": result}],
        },
    ]
    out = _openai_chat.build_messages(messages, "sys")
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert json.loads(tool_msgs[0]["content"]) == result
    assert not any(m["role"] == "user" and isinstance(m.get("content"), list) for m in out)


def test_has_image_content():
    payload_with = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]}
    payload_without = {"messages": [{"role": "user", "content": "hi"}]}
    assert _openai_chat._has_image_content(payload_with) is True
    assert _openai_chat._has_image_content(payload_without) is False


def test_wrap_http_error_mmproj_hint():
    import requests
    from nugget.backends import BackendError

    class FakeResp:
        text = "Error: model does not support images, no mmproj loaded"

    e = requests.HTTPError()
    e.response = FakeResp()
    payload = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]}
    err = _openai_chat._wrap_http_error(e, payload)
    assert isinstance(err, BackendError)
    assert "mmproj" in str(err).lower() or "vision" in str(err).lower()


def test_wrap_http_error_without_image_content_is_generic():
    import requests
    from nugget.backends import BackendError

    class FakeResp:
        text = "some unrelated 500 error"

    e = requests.HTTPError("boom")
    e.response = FakeResp()
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    err = _openai_chat._wrap_http_error(e, payload)
    assert isinstance(err, BackendError)
    assert "mmproj" not in str(err).lower()
