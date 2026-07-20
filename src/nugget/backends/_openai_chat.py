"""
Shared OpenAI-compatible chat-completions plumbing, used by both
OpenRouterBackend and TextgenBackend (the latter only once an attachment
enters the conversation — see textgen.py's `_run_chat_mode`).

Kept pure (no backend state) so both backends can call in with their own
session/url/model, mirroring the existing `_routing.py` convention.
"""

import json
from typing import Callable

import requests

from . import BackendError


def build_messages(messages: list[dict], system_prompt: str) -> list[dict]:
    """
    Build the OpenAI-format message list from nugget's internal format.
    system_prompt goes as a "system" role message first.

    A tool result carrying an `_attachment` sentinel (see filebrowser.cat on
    an image, or the `pdf` tool) can't ride in a `role: tool` message as-is —
    OpenAI's protocol requires tool-role content be a plain string, no
    array/image parts. So such results get a text-only stub in the tool
    message, followed by a synthetic `user` message carrying the actual
    image_url parts, which every OpenAI-compatible endpoint accepts as an
    ordinary multimodal user turn.
    """
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        if msg["role"] == "user":
            out.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for i, tc in enumerate(msg["tool_calls"])
                ]
            out.append(assistant_msg)
            for tc in msg.get("tool_calls", []):
                result = tc["result"]
                if isinstance(result, dict) and result.get("_attachment") and result.get("images"):
                    out.append(_tool_stub_message(tc, result))
                    out.append(_attachment_followup_message(result))
                else:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "call_0"),
                        "content": json.dumps(result),
                    })
    return out


def _tool_stub_message(tc: dict, result: dict) -> dict:
    stub = {"attached": True, "image_count": len(result.get("images", []))}
    if result.get("text"):
        stub["text"] = result["text"]
    return {
        "role": "tool",
        "tool_call_id": tc.get("id", "call_0"),
        "content": json.dumps(stub),
    }


def _attachment_followup_message(result: dict) -> dict:
    parts: list[dict] = [{"type": "text", "text": "[attached content from the tool call above]"}]
    for img in result["images"]:
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img['mime']};base64,{img['data_b64']}"},
        })
    return {"role": "user", "content": parts}


def _has_image_content(payload: dict) -> bool:
    return any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for m in payload.get("messages", [])
        if isinstance(m.get("content"), list)
        for part in m["content"]
    )


def _wrap_http_error(e: requests.HTTPError, payload: dict) -> BackendError:
    body = ""
    try:
        body = (e.response.text or "")[:500]
    except Exception:
        pass
    if _has_image_content(payload) and any(
        kw in body.lower() for kw in ("mmproj", "clip", "vision", "image", "multimodal")
    ):
        return BackendError(
            "This request included an image, but the currently loaded model does not "
            "appear to support image input (no vision projector/mmproj loaded). Load a "
            "vision-capable model with its mmproj file, or use a backend/model that "
            "supports images."
        )
    return BackendError(str(e))


def complete(
    session: requests.Session,
    url: str,
    model: str,
    oai_messages: list[dict],
    tool_schemas: list[dict],
    temperature: float,
    max_tokens: int,
    debug: bool = False,
) -> tuple[str, str | None, list[dict], dict | None]:
    """Non-streaming completion. Returns (text, thinking, tool_calls_raw, usage)."""
    payload: dict = {
        "model": model,
        "messages": oai_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tool_schemas:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"
    if debug:
        print(json.dumps({"url": url, "payload": payload}, indent=2))
    try:
        resp = session.post(url, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise _wrap_http_error(e, payload) from e
    except requests.RequestException as e:
        raise BackendError(str(e)) from e
    data = resp.json()
    usage = data.get("usage") or None
    choice = data["choices"][0]
    msg = choice["message"]
    text = msg.get("content") or ""
    thinking = msg.get("reasoning_content")
    tool_calls = msg.get("tool_calls") or []
    return text, thinking, tool_calls, usage


def complete_streaming(
    session: requests.Session,
    url: str,
    model: str,
    oai_messages: list[dict],
    tool_schemas: list[dict],
    temperature: float,
    max_tokens: int,
    on_token: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_thinking_end: Callable[[], None] | None = None,
    debug: bool = False,
) -> tuple[str, str | None, list[dict], dict | None]:
    """
    Streaming completion. Fires on_token incrementally for visible text,
    on_thinking incrementally for reasoning content as it arrives, and
    on_thinking_end once reasoning gives way to visible content. Assembles
    partial tool-call-argument deltas across chunks. Returns
    (text, thinking, tool_calls_raw, usage).
    """
    payload: dict = {
        "model": model,
        "messages": oai_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tool_schemas:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"
    if debug:
        print(json.dumps({"url": url, "streaming": True}, indent=2))
    try:
        resp = session.post(url, json=payload, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise _wrap_http_error(e, payload) from e
    except requests.RequestException as e:
        raise BackendError(str(e)) from e

    usage = None
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    # tool_calls_buf: index → {"id", "name", "args_str"}
    tool_calls_buf: dict[int, dict] = {}

    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        if raw_line == b"data: [DONE]":
            break
        if not raw_line.startswith(b"data: "):
            continue
        chunk = json.loads(raw_line[6:])
        # Usage-only chunk sent before [DONE] when stream_options.include_usage is set
        if not chunk.get("choices"):
            if "usage" in chunk:
                usage = chunk["usage"]
            continue
        choice = chunk["choices"][0]
        delta = choice.get("delta", {})

        # Reasoning / thinking
        reasoning_delta = delta.get("reasoning_content") or ""
        if reasoning_delta:
            thinking_parts.append(reasoning_delta)
            if on_thinking:
                on_thinking(reasoning_delta)

        # Visible text
        content_delta = delta.get("content") or ""
        if content_delta:
            if thinking_parts and not text_parts and on_thinking_end:
                on_thinking_end()
            text_parts.append(content_delta)
            if on_token:
                on_token(content_delta)

        # Tool call argument deltas — merge by index
        for tc_delta in delta.get("tool_calls") or []:
            idx = tc_delta.get("index", 0)
            if idx not in tool_calls_buf:
                tool_calls_buf[idx] = {"id": "", "name": "", "args_str": ""}
            buf = tool_calls_buf[idx]
            if tc_delta.get("id"):
                buf["id"] = tc_delta["id"]
            fn = tc_delta.get("function") or {}
            if fn.get("name"):
                buf["name"] += fn["name"]
            if fn.get("arguments"):
                buf["args_str"] += fn["arguments"]

    full_text = "".join(text_parts)
    full_thinking = "".join(thinking_parts) or None

    # If reasoning never gave way to visible content (e.g. straight into
    # a tool call), close the block here instead of leaving it dangling.
    if full_thinking and not text_parts and on_thinking_end:
        on_thinking_end()

    # Convert buf → OpenAI tool_calls format, preserving stream order via index
    tool_calls_raw = [
        {
            "id": buf["id"],
            "type": "function",
            "function": {"name": buf["name"], "arguments": buf["args_str"]},
        }
        for _, buf in sorted(tool_calls_buf.items())
    ]
    return full_text, full_thinking, tool_calls_raw, usage
