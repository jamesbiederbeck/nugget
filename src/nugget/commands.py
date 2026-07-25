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


# (canonical_name, aliases, description)
COMMANDS: list[tuple[str, list[str], str]] = [
    ("/help",     ["/?"],    "show this help"),
    ("/exit",     ["/quit"], "exit the session"),
    ("/clear",    [],        "clear message history (keeps session file)"),
    ("/rewind",   [],        "undo the last turn"),
    ("/prompt",   [],        "show the current system prompt"),
    ("/export",   [],        "[FILE]  write the full rendered model payload for this session to FILE"),
    ("/sessions", [],        "list saved sessions"),
    ("/session",  [],        "[ID]  show current session ID, or switch to ID"),
    ("/tools",    [],        "list active tools"),
    ("/memory",   [],        "show pinned memories and all stored keys"),
    ("/verbose",  [],        "toggle verbose display (thinking + tool calls/responses)"),
    ("/thinking", [],        "toggle thinking display only"),
    ("/profile",  [],        "[NAME]  list profiles or switch to NAME"),
]

ALL_COMMAND_NAMES: list[str] = [
    n for name, aliases, _ in COMMANDS for n in ([name] + aliases)
]
COMMAND_DESCRIPTIONS: dict[str, str] = {
    n: desc
    for name, aliases, desc in COMMANDS
    for n in ([name] + aliases)
}


def _build_help() -> str:
    lines = []
    for name, aliases, desc in COMMANDS:
        all_names = "  " + "  ".join([name] + aliases)
        lines.append(f"{all_names:<22} {desc}")
    lines.append(f"{'  !<command>':<22} run a shell command directly")
    return "\n".join(lines)


_HELP = _build_help()


@dataclass
class CommandContext:
    session_cell: list              # [Session] — mutable; session_cell[0] is active session
    cfg: Config
    active_schemas_cell: list       # [list[dict]] — mutable
    backend_cell: list              # [Backend] — mutable
    get_system_prompt: Callable[[], str]
    get_thinking_effort: Callable[[], int]
    sessions_path: Path
    cli_overrides: dict             # overrides captured before Config() construction
    cli_include: list | None        # from --include-tools flag
    cli_exclude: list | None        # from --exclude-tools flag


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

    elif cmd == "/export":
        from .backends import render_request
        path = Path(arg).expanduser() if arg else Path.cwd() / f"nugget-export-{session.id}.txt"
        rendered = render_request(
            ctx.backend_cell[0],
            session.messages,
            ctx.active_schemas_cell[0],
            ctx.get_system_prompt(),
            ctx.get_thinking_effort(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
        display.print_dim(f"Exported rendered prompt to {path} ({len(rendered)} chars)")

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
        if not ctx.active_schemas_cell[0]:
            display.print_dim("No active tools.")
        else:
            for schema in ctx.active_schemas_cell[0]:
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

    elif cmd == "/profile":
        if not arg:
            profiles = sorted(ctx.cfg._profiles.keys())
            if not profiles:
                display.print_dim("No profiles defined.")
            else:
                for p in profiles:
                    marker = f" {display.CYAN}*{display.RESET}" if p == ctx.cfg._active_profile else ""
                    display.print_dim(f"  {p}{marker}")
        else:
            try:
                ctx.cfg.apply_profile(
                    arg,
                    cli_overrides=ctx.cli_overrides,
                    cli_include=ctx.cli_include,
                    cli_exclude=ctx.cli_exclude,
                )
            except ValueError as e:
                display.print_error(str(e))
                return None
            from . import tools as tool_registry
            from . import mcp_client
            from .backends import make_backend
            inc = ctx.cli_include or ctx.cfg.get("include_tools")
            exc = ctx.cli_exclude or ctx.cfg.get("exclude_tools")
            ctx.active_schemas_cell[0] = (
                tool_registry.schemas(include=inc, exclude=exc) + mcp_client.schemas(ctx.cfg)
            )
            ctx.backend_cell[0] = make_backend(ctx.cfg)
            display.print_dim(f"Switched to profile: {arg}")

    else:
        display.print_error(f"Unknown command: {cmd}  (try /help)")

    return None
