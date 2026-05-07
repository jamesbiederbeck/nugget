"""
nugget web server — FastAPI + SSE streaming.

Install extras:  uv pip install -e ".[web]"
Run:             nugget-server [--host HOST] [--port PORT]
"""

import argparse
import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .session import Session
from .backends import make_backend, BackendError
from . import tools as tool_registry
from . import approval as approval_mod
from .tools.memory import get_pinned as _get_pinned
from .subagent import _session_id as _subagent_session_id, _event_callbacks as _subagent_event_callbacks

# ── App and lazy globals ─────────────────────────────────────────────────────

logger = logging.getLogger("nugget.server")

app = FastAPI(title="nugget")

# call_id → {"call_id", "tool", "args", "event", "approved", "reason"}
_pending_approvals: dict[str, dict] = {}
_pending_lock = threading.Lock()

_cfg: Config | None = None
_backend = None


def _get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config.ensure_default()
    return _cfg


def _get_backend():
    global _backend
    if _backend is None:
        _backend = make_backend(_get_cfg())
    return _backend


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_system_prompt(cfg: Config) -> str:
    parts = [cfg.system_prompt]
    if cfg.append_datetime:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"Current date and time: {now}")
    pinned = _get_pinned()
    if pinned:
        pins = "\n".join(f"- {m['key']}: {m['value']}" for m in pinned)
        parts.append(f"## Pinned memories\n{pins}")
    return "\n\n".join(parts)


def _make_web_ask(emit):
    """Return a (name, args) -> (approved, reason) callable that emits an SSE approval
    request and blocks until the user responds via POST /api/approvals/{call_id}/respond."""
    def web_ask(name: str, args: dict) -> tuple[bool, str | None]:
        call_id = str(uuid.uuid4())
        ev = threading.Event()
        with _pending_lock:
            _pending_approvals[call_id] = {
                "call_id": call_id,
                "tool": name,
                "args": args,
                "event": ev,
                "approved": None,
                "reason": None,
            }
        emit({"type": "approval_required", "call_id": call_id, "name": name, "args": args})
        ev.wait(timeout=300)
        with _pending_lock:
            entry = _pending_approvals.pop(call_id, None)
        if not entry or not entry.get("approved"):
            reason = (entry or {}).get("reason") or f"tool '{name}' denied by user"
            return False, reason
        return True, None
    return web_ask


def _make_web_tool_executor(emit):
    """Return a tool executor that pauses on 'ask' and waits for web approval."""
    web_ask = _make_web_ask(emit)

    def executor(name: str, args: dict) -> object:
        cfg = _get_cfg()
        action = approval_mod._resolve_action(
            name, args, tool_registry.gate(name), cfg.approval_config()
        )
        if action == "deny":
            return {"_denied": True, "reason": f"tool '{name}' blocked by approval policy"}
        if action == "ask":
            approved, reason = web_ask(name, args)
            if not approved:
                return {"_denied": True, "reason": reason}
        return tool_registry.execute(name, args)
    return executor


# ── Session API ───────────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return Session.list_sessions(_get_cfg().sessions_path())


@app.post("/api/sessions")
async def create_session():
    cfg = _get_cfg()
    session = Session.new(cfg.sessions_path())
    session.save()
    return {"id": session.id}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    cfg = _get_cfg()
    session = Session.load(session_id, cfg.sessions_path())
    if not session.path.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": session.messages,
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    cfg = _get_cfg()
    session = Session.load(session_id, cfg.sessions_path())
    if session.path.exists():
        session.path.unlink()
    return {"deleted": session_id}


# ── Chat SSE endpoint ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    cfg = _get_cfg()
    session = Session.load(session_id, cfg.sessions_path())
    session.add_user(req.message)
    active_schemas = tool_registry.schemas()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def emit(event: dict) -> None:
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def on_token(tok: str) -> None:
        emit({"type": "token", "text": tok})

    def on_thinking(text: str) -> None:
        emit({"type": "thinking", "text": text})

    def on_tool_call(name: str, args: dict) -> None:
        emit({"type": "tool_call", "name": name, "args": args})

    def on_tool_response(name: str, result: object) -> None:
        emit({"type": "tool_result", "name": name, "result": result})

    def on_tool_routed(name: str, result: object, sink: str) -> None:
        emit({"type": "tool_routed", "name": name, "result": result, "sink": sink})

    def on_tool_denied(name: str, reason: str) -> None:
        emit({"type": "tool_denied", "name": name, "reason": reason})

    def on_subagent_call(*, task: str, tool_count: int, parent_depth: int) -> None:
        emit({"type": "subagent_call", "task": task, "tool_count": tool_count, "parent_depth": parent_depth})

    def on_subagent_done(*, answer: str, tool_calls: int, finish_reason: str | None) -> None:
        emit({"type": "subagent_done", "answer": answer, "tool_calls": tool_calls, "finish_reason": finish_reason})

    def run_in_thread() -> None:
        backend = _get_backend()
        backend_name = cfg.get("backend", "textgen")
        model = getattr(backend, "_model", None) or cfg.model
        logger.info(
            "chat request  session=%s backend=%s model=%s input_chars=%d",
            session.id, backend_name, model, len(req.message),
        )
        sid_token = _subagent_session_id.set(session.id)
        cb_token = _subagent_event_callbacks.set({
            "on_subagent_call": on_subagent_call,
            "on_subagent_done": on_subagent_done,
            "web_ask": _make_web_ask(emit),
        })
        t0 = time.monotonic()
        try:
            text, thinking, exchanges, finish_reason = backend.run(
                messages=session.messages,
                tool_schemas=active_schemas,
                tool_executor=_make_web_tool_executor(emit),
                system_prompt=_build_system_prompt(cfg),
                thinking_effort=cfg.thinking_effort,
                on_token=on_token,
                on_thinking=on_thinking,
                on_tool_call=on_tool_call,
                on_tool_response=on_tool_response,
                on_tool_routed=on_tool_routed,
                on_tool_denied=on_tool_denied,
            )
            elapsed = time.monotonic() - t0
            usage = getattr(backend, "last_usage", None) or {}
            stats = [
                f"session={session.id}",
                f"backend={backend_name}",
                f"model={model}",
                f"elapsed={elapsed:.2f}s",
                f"tools={len(exchanges)}",
                f"finish={finish_reason}",
            ]
            if usage.get("prompt_tokens") is not None:
                stats.append(f"prompt_tokens={usage['prompt_tokens']}")
            if usage.get("completion_tokens") is not None:
                stats.append(f"completion_tokens={usage['completion_tokens']}")
            if usage.get("total_tokens") is not None:
                stats.append(f"total_tokens={usage['total_tokens']}")
            logger.info("chat done  %s", "  ".join(stats))
            session.add_assistant(text, thinking=thinking, tool_calls=exchanges)
            session.save()
            emit({"type": "done", "text": text})
        except BackendError as e:
            elapsed = time.monotonic() - t0
            logger.warning(
                "chat error  session=%s backend=%s elapsed=%.2fs error=%s",
                session.id, backend_name, elapsed, e,
            )
            emit({"type": "error", "message": str(e)})
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.exception(
                "chat internal error  session=%s backend=%s elapsed=%.2fs",
                session.id, backend_name, elapsed,
            )
            emit({"type": "error", "message": f"Internal error: {e}"})
        finally:
            _subagent_session_id.reset(sid_token)
            _subagent_event_callbacks.reset(cb_token)
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    threading.Thread(target=run_in_thread, daemon=True).start()

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Approval API ──────────────────────────────────────────────────────────────

@app.get("/api/approvals/pending")
async def list_pending_approvals():
    with _pending_lock:
        return [
            {"call_id": v["call_id"], "tool": v["tool"], "args": v["args"]}
            for v in _pending_approvals.values()
        ]


class ApprovalDecision(BaseModel):
    decision: str  # "approve" or "deny"


@app.post("/api/approvals/{call_id}/respond")
async def respond_to_approval(call_id: str, body: ApprovalDecision):
    with _pending_lock:
        entry = _pending_approvals.get(call_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Approval not found")
    entry["approved"] = body.decision == "approve"
    entry["reason"] = None if entry["approved"] else f"tool '{entry['tool']}' denied by user"
    entry["event"].set()
    return {"ok": True}


@app.post("/api/tools/reload")
async def reload_tools():
    tools = tool_registry.reload()
    return {"tools": tools}


# ── Static frontend ───────────────────────────────────────────────────────────

_WEB_DIR = Path(__file__).parent / "web"
if _WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="nugget-server", description="nugget web server")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p.add_argument("--backend", metavar="NAME", help="Backend to use (e.g. openrouter)")
    p.add_argument("--model", metavar="MODEL", help="Model to use (e.g. google/gemma-4-31b-it)")
    p.add_argument("--profile", metavar="NAME", help="Named config profile to activate")
    args = p.parse_args()

    if args.profile or args.backend or args.model:
        from .config import Config as _Config
        global _cfg
        overrides = {}
        if args.backend:
            overrides["backend"] = args.backend
        if args.model:
            overrides["openrouter_model"] = args.model
        _cfg = _Config(overrides or None, profile=args.profile)

    print(f"nugget server → http://{args.host}:{args.port}")
    uvicorn.run("nugget.server:app", host=args.host, port=args.port, reload=False)
