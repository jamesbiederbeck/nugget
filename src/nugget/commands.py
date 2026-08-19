"""
Interactive /command handler for the nugget CLI.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import display
from .backends import Backend
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
    ("/backend",  ["/backends"], "[NAME]  show backend status or switch to NAME"),
    ("/model",    [],        "[TEXT]  show/list models or switch to a TEXT-filtered match"),
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


def _print_backend_status(cfg: Config) -> None:
    active = cfg._data.get("backend", "textgen")
    profiles_for: dict[str, list[str]] = {}
    for pname, pdata in cfg._profiles.items():
        b = pdata.get("backend")
        if b:
            profiles_for.setdefault(b, []).append(pname)

    for name in Backend.PROVIDERS:
        marker = f" {display.CYAN}*{display.RESET}" if name == active else ""
        if name == "textgen":
            usable, note = True, cfg._data.get("api_url", "")
        else:
            raw_url = (cfg._data.get("openrouter_base_url") or "https://openrouter.ai/api").rstrip("/")
            is_local = raw_url.startswith("http://localhost") or raw_url.startswith("http://127.")
            has_key = bool(cfg._data.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY"))
            usable = has_key or is_local
            note = raw_url if usable else "no API key set"
        status = f"{display.GREEN}usable{display.RESET}" if usable else f"{display.RED}not usable{display.RESET}"
        print(f"  {name}{marker}  {status}  {display.DIM}{note}{display.RESET}")
        for pname in sorted(profiles_for.get(name, [])):
            display.print_dim(f"      profile: {pname}")


def _print_model_status(backend_name: str, live) -> None:
    try:
        current = live.current_model()
    except Exception as e:
        display.print_error(f"Could not query current model: {e}")
        return
    display.print_dim(f"Current model ({backend_name}): {current}")
    try:
        models = live.list_models()
    except Exception as e:
        display.print_dim(f"(model list unavailable: {e})")
        return
    if backend_name == "textgen":
        for m in models:
            marker = f" {display.CYAN}*{display.RESET}" if m == current else ""
            print(f"  {m}{marker}")
    else:
        display.print_dim(f"{len(models)} models available — use /model TEXT to filter")


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
                    if p == ctx.cfg._active_profile:
                        suffix = " (modified)" if ctx.cfg._profile_modified else ""
                        marker = f" {display.CYAN}*{suffix}{display.RESET}"
                    else:
                        marker = ""
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

    elif cmd in ("/backend", "/backends"):
        if not arg:
            _print_backend_status(ctx.cfg)
        else:
            name = arg.strip().lower()
            if name not in Backend.PROVIDERS:
                display.print_error(f"Unknown backend: {name}  (choices: {', '.join(Backend.PROVIDERS)})")
                return None
            from .backends import make_backend
            old_value = ctx.cfg._data.get("backend")
            ctx.cfg._data["backend"] = name
            try:
                new_backend = make_backend(ctx.cfg)
            except Exception as e:
                ctx.cfg._data["backend"] = old_value
                display.print_error(f"Could not switch to {name}: {e}")
                return None
            ctx.backend_cell[0] = new_backend
            if ctx.cfg._active_profile is not None:
                ctx.cfg._profile_modified = True
            display.print_dim(f"Switched to backend: {name}")

    elif cmd == "/model":
        backend_name = ctx.cfg._data.get("backend", "textgen")
        live = ctx.backend_cell[0]
        if not arg:
            _print_model_status(backend_name, live)
            return None
        try:
            models = live.list_models()
        except Exception as e:
            display.print_error(f"Could not list models: {e}")
            return None
        matches = [m for m in models if arg.lower() in m.lower()]
        if not matches:
            display.print_error(f"No models matching {arg!r}.")
        elif len(matches) > 1:
            display.print_dim(f"{len(matches)} matches for {arg!r}:")
            for m in matches:
                print(f"  {m}")
        else:
            chosen = matches[0]
            if backend_name == "textgen":
                if not display.ask_yes_no(
                    f"Load {chosen}? This unloads the current model on the server. [y/N] "
                ):
                    display.print_dim("Cancelled.")
                    return None
                try:
                    live.load_model(chosen)
                except Exception as e:
                    display.print_error(f"Load failed: {e}")
                    return None
                ctx.cfg._data["model"] = chosen
            else:
                from .backends import make_backend
                ctx.cfg._data["openrouter_model"] = chosen
                ctx.backend_cell[0] = make_backend(ctx.cfg)
            if ctx.cfg._active_profile is not None:
                ctx.cfg._profile_modified = True
            display.print_dim(f"Model set to: {chosen}")

    else:
        display.print_error(f"Unknown command: {cmd}  (try /help)")

    return None
