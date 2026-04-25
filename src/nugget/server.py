"""
nugget web server — FastAPI + SSE streaming.

Install extras:  uv pip install -e ".[web]"
Run:             nugget-server [--host HOST] [--port PORT]
"""

import argparse
import asyncio
import copy
import json
import threading
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

# ── App and lazy globals ─────────────────────────────────────────────────────

app = FastAPI(title="nugget")

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


def _web_approval_config(cfg: Config) -> dict:
    """Convert 'ask' → 'allow' since there's no TTY in web mode."""
    ac = copy.deepcopy(cfg.approval_config())
    if ac.get("default") == "ask":
        ac["default"] = "allow"
    for rule in ac.get("rules", []):
        if rule.get("action") == "ask":
            rule["action"] = "allow"
    return ac


def _web_tool_executor(name: str, args: dict) -> object:
    cfg = _get_cfg()
    approved, reason = approval_mod.check(
        name, args, tool_registry.gate(name), _web_approval_config(cfg)
    )
    if not approved:
        return {"_denied": True, "reason": reason}
    return tool_registry.execute(name, args)


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

    def on_tool_denied(name: str, reason: str) -> None:
        emit({"type": "tool_denied", "name": name, "reason": reason})

    def run_in_thread() -> None:
        try:
            text, thinking, exchanges, _ = _get_backend().run(
                messages=session.messages,
                tool_schemas=active_schemas,
                tool_executor=_web_tool_executor,
                system_prompt=_build_system_prompt(cfg),
                thinking_effort=cfg.thinking_effort,
                on_token=on_token,
                on_thinking=on_thinking,
                on_tool_call=on_tool_call,
                on_tool_response=on_tool_response,
                on_tool_denied=on_tool_denied,
            )
            session.add_assistant(text, thinking=thinking, tool_calls=exchanges)
            session.save()
            emit({"type": "done", "text": text})
        except BackendError as e:
            emit({"type": "error", "message": str(e)})
        except Exception as e:
            emit({"type": "error", "message": f"Internal error: {e}"})
        finally:
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
    args = p.parse_args()

    print(f"nugget server → http://{args.host}:{args.port}")
    uvicorn.run("nugget.server:app", host=args.host, port=args.port, reload=False)
