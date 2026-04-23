"""
Interactive /command handler for the nugget CLI.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import display
from .config import Config
from .session import Session
from .tools.memory import execute as _memory_execute, get_pinned


@dataclass
class CommandContext:
    session_cell: list          # [Session] — mutable; session_cell[0] is active session
    cfg: Config
    active_schemas: list[dict]
    get_system_prompt: Callable[[], str]
    sessions_path: Path


_HELP = """
  /help              show this help
  /exit  /quit       exit the session
  /clear             clear message history (keeps session file)
  /rewind            undo the last turn
  /prompt            show the current system prompt
  /sessions          list saved sessions
  /session [ID]      show current session ID, or switch to ID
  /tools             list active tools
  /memory            show pinned memories and all stored keys
  /verbose           toggle verbose display (thinking + tool calls/responses)
  /thinking          toggle thinking display only
""".strip()


def dispatch(raw: str, ctx: CommandContext) -> str | None:
    """Parse and run a /command. Returns 'exit' to quit the loop, None to continue."""
    parts = raw.strip().split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None

    session = ctx.session_cell[0]

    if cmd in ("/help", "/?"):
        print(_HELP)

    elif cmd in ("/exit", "/quit"):
        return "exit"

    elif cmd == "/clear":
        session.messages.clear()
        session.save()
        display.print_dim("History cleared.")

    elif cmd == "/rewind":
        if not session.messages:
            display.print_dim("Nothing to rewind.")
        else:
            if session.messages[-1]["role"] == "assistant":
                session.messages.pop()
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()
            session.save()
            display.print_dim(f"Rewound. {len(session.messages)} messages remain.")

    elif cmd == "/prompt":
        display.print_system_prompt(ctx.get_system_prompt())

    elif cmd == "/sessions":
        sessions = Session.list_sessions(ctx.sessions_path)
        if not sessions:
            display.print_dim("No sessions found.")
        else:
            display.print_session_list(sessions)

    elif cmd == "/session":
        if not arg:
            display.print_dim(f"Current session: {session.id}")
        else:
            ctx.session_cell[0] = Session.load(arg, ctx.sessions_path)
            display.print_session_header(ctx.session_cell[0].id)

    elif cmd == "/tools":
        if not ctx.active_schemas:
            display.print_dim("No active tools.")
        else:
            for schema in ctx.active_schemas:
                fn = schema["function"]
                print(f"  {display.CYAN}{fn['name']}{display.RESET}  "
                      f"{display.DIM}{fn.get('description', '')}{display.RESET}")

    elif cmd == "/memory":
        pinned = get_pinned()
        result = _memory_execute({"operation": "list"})
        keys = result.get("keys", [])
        if not keys:
            display.print_dim("No memories stored.")
        else:
            display.print_dim(f"Memories ({len(keys)}):")
            for k in keys:
                pin_marker = f" {display.YELLOW}*pinned*{display.RESET}" if k.get("pinned") else ""
                print(f"  {display.CYAN}{k['key']}{display.RESET}{pin_marker}"
                      f"  {display.DIM}{k['updated_at'][:16]}{display.RESET}")

    elif cmd == "/verbose":
        flags = ["show_thinking", "show_tool_calls", "show_tool_responses"]
        current = all(ctx.cfg._data.get(f) for f in flags)
        new_val = not current
        for f in flags:
            ctx.cfg._data[f] = new_val
        display.print_dim(f"Verbose {'on' if new_val else 'off'}.")

    elif cmd == "/thinking":
        current = ctx.cfg._data.get("show_thinking", False)
        ctx.cfg._data["show_thinking"] = not current
        display.print_dim(f"Thinking display {'on' if not current else 'off'}.")

    else:
        display.print_error(f"Unknown command: {cmd}  (try /help)")

    return None
