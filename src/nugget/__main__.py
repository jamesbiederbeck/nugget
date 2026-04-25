"""
python -m nugget [OPTIONS] [MESSAGE]

Interactive or one-shot chat via a configurable local model backend.
"""

import argparse
import sys

from .config import Config
from .backends import make_backend, BackendError
from .session import Session
from . import tools as tool_registry
from . import display
from . import approval as approval_mod
from . import commands as commands_mod
from .commands import CommandContext
from .tools.memory import get_pinned as _get_pinned


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nugget",
        description="Chat with a locally-hosted model",
    )

    p.add_argument("message", nargs="?", help="Initial message (omit for interactive)")
    p.add_argument("--session", "-s", metavar="ID", help="Session ID to resume or create")
    p.add_argument("--list-sessions", action="store_true", help="List saved sessions and exit")
    p.add_argument("--non-interactive", "-n", action="store_true",
                   help="Exit after the first response (requires MESSAGE)")

    # Tool filtering
    tg = p.add_argument_group("tool filtering")
    tg.add_argument("--include-tools", metavar="t1,t2",
                    help="Only expose these tools (comma-separated)")
    tg.add_argument("--exclude-tools", metavar="t1,t2",
                    help="Exclude these tools (comma-separated)")
    tg.add_argument("--list-tools", action="store_true", help="List available tools and exit")

    # Thinking
    thg = p.add_argument_group("thinking")
    thg.add_argument("--thinking", action="store_true", default=None,
                     help="Enable thinking (effort 2 if --thinking-effort not set)")
    thg.add_argument("--no-thinking", dest="thinking", action="store_false",
                     help="Disable thinking")
    thg.add_argument("--thinking-effort", type=int, metavar="N", choices=[0, 1, 2, 3],
                     help="0=off 1=low 2=medium 3=high")

    # Display flags
    dg = p.add_argument_group("display")
    dg.add_argument("--verbose", "-v", action="store_true",
                    help="Show thinking, tool calls/responses, and system prompt")
    dg.add_argument("--show-thinking", action="store_true", default=None)
    dg.add_argument("--hide-thinking", dest="show_thinking", action="store_false")
    dg.add_argument("--show-tool-calls", action="store_true", default=None)
    dg.add_argument("--hide-tool-calls", dest="show_tool_calls", action="store_false")
    dg.add_argument("--show-tool-responses", action="store_true", default=None)
    dg.add_argument("--hide-tool-responses", dest="show_tool_responses", action="store_false")
    dg.add_argument("--show-system-prompt", action="store_true", default=None)

    # Debug
    p.add_argument("--debug", action="store_true",
                   help="Print each completion request payload to stdout before sending")

    # Config overrides
    p.add_argument("--backend", metavar="NAME", help="Backend to use (e.g. textgen)")
    p.add_argument("--system", metavar="PROMPT", help="Override system prompt for this run")
    p.add_argument("--max-tokens", type=int, metavar="N")
    p.add_argument("--temperature", type=float, metavar="F")

    return p


def resolve_thinking_effort(args, cfg: Config) -> int:
    if args.thinking_effort is not None:
        return args.thinking_effort
    if args.thinking is True:
        return 2
    if args.thinking is False:
        return 0
    return cfg.thinking_effort


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()

    cfg = Config.ensure_default()

    # ── List sessions ────────────────────────────────────────────────────────
    if args.list_sessions:
        sessions = Session.list_sessions(cfg.sessions_path())
        if not sessions:
            print("No sessions found.")
        else:
            display.print_session_list(sessions)
        return

    # ── List tools ───────────────────────────────────────────────────────────
    if args.list_tools:
        for name in tool_registry.list_names():
            schema = tool_registry.all_tools()[name][0]["function"]
            print(f"  {name:20s}  {schema.get('description', '')}")
        return

    # ── Build config overrides ───────────────────────────────────────────────
    overrides = {}
    if args.backend:
        overrides["backend"] = args.backend
    if args.system:
        overrides["system_prompt"] = args.system
    if args.max_tokens:
        overrides["max_tokens"] = args.max_tokens
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.debug:
        overrides["debug"] = True

    if args.verbose:
        for flag in ("show_thinking", "show_tool_calls", "show_tool_responses", "show_system_prompt"):
            overrides[flag] = True

    for flag in ("show_thinking", "show_tool_calls", "show_tool_responses", "show_system_prompt"):
        val = getattr(args, flag)
        if val is not None:
            overrides[flag] = val

    cfg = Config(overrides)

    thinking_effort = resolve_thinking_effort(args, cfg)

    # ── Tool schema selection ────────────────────────────────────────────────
    include = [t.strip() for t in args.include_tools.split(",")] if args.include_tools else None
    exclude = [t.strip() for t in args.exclude_tools.split(",")] if args.exclude_tools else None
    active_schemas = tool_registry.schemas(include=include, exclude=exclude)

    # ── Session ──────────────────────────────────────────────────────────────
    if args.session == "last":
        recent = Session.list_sessions(cfg.sessions_path())
        session_id = recent[0]["id"] if recent else None
        _session = Session.load(session_id, cfg.sessions_path()) if session_id else Session.new(cfg.sessions_path())
    elif args.session:
        _session = Session.load(args.session, cfg.sessions_path())
    else:
        _session = Session.new(cfg.sessions_path())

    # Mutable reference so /session command can swap the active session
    session_cell = [_session]

    backend = make_backend(cfg)

    if sys.stdin.isatty():
        display.print_session_header(session_cell[0].id)

    def _system_prompt() -> str:
        from datetime import datetime, timezone
        parts = [cfg.system_prompt]
        if cfg.append_datetime:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            parts.append(f"Current date and time: {now}")
        pinned = _get_pinned()
        if pinned:
            pins = "\n".join(f"- {m['key']}: {m['value']}" for m in pinned)
            parts.append(f"## Pinned memories\n{pins}")
        return "\n\n".join(parts)

    if cfg.show_system_prompt:
        from .backends.textgen import build_prompt
        preview = build_prompt([], active_schemas, _system_prompt(), thinking_effort)
        display.print_system_prompt(preview)

    def on_thinking(text: str) -> None:
        if cfg.show_thinking:
            display.print_thinking(text)

    def on_tool_call(name: str, args: dict) -> None:
        if cfg.show_tool_calls:
            display.print_tool_call(name, args)

    def on_tool_response(name: str, result: object) -> None:
        if cfg.show_tool_responses:
            display.print_tool_response(name, result)

    def on_tool_routed(name: str, result: object, sink: str) -> None:
        # Routed results never enter the model's context, so always surface
        # them to the user regardless of cfg.show_tool_responses.
        display.print_tool_response(name, result)

    def on_tool_denied(name: str, reason: str) -> None:
        display.print_error(f"tool '{name}' not executed: {reason}")

    def sink_approval_prompt(name: str, abs_path) -> bool:
        if not sys.stdin.isatty():
            return False
        print(f"\n{display.BOLD}{display.YELLOW}[approval]{display.RESET} "
              f"{display.CYAN}{name}{display.RESET} "
              f"{display.DIM}write → {abs_path}{display.RESET}")
        try:
            answer = input(f"{display.BOLD}Allow? [y/N]{display.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            answer = ""
        return answer in ("y", "yes")

    def tool_executor(name: str, args: dict) -> object:
        approved, reason = approval_mod.check(
            name, args, tool_registry.gate(name), cfg.approval_config()
        )
        if not approved:
            return {"_denied": True, "reason": reason}
        return tool_registry.execute(name, args)

    def run_turn(user_input: str) -> None:
        session = session_cell[0]
        session.add_user(user_input)

        streaming_started = [False]

        def on_token(tok: str) -> None:
            if not streaming_started[0]:
                display.print_assistant_begin()
                streaming_started[0] = True
            display.print_token(tok)

        try:
            text, thinking, tool_exchanges, _ = backend.run(
                messages=session.messages,
                tool_schemas=active_schemas,
                tool_executor=tool_executor,
                system_prompt=_system_prompt(),
                thinking_effort=thinking_effort,
                on_thinking=on_thinking,
                on_tool_call=on_tool_call,
                on_tool_response=on_tool_response,
                on_tool_denied=on_tool_denied,
                on_token=on_token,
                on_tool_routed=on_tool_routed,
                check_file_sink=approval_mod.check_file_sink,
                sink_approval_prompt=sink_approval_prompt,
                approval_config=cfg.approval_config(),
            )
        except BackendError as e:
            if streaming_started[0]:
                display.print_assistant_end()
            display.print_error(str(e))
            return
        except KeyboardInterrupt:
            if streaming_started[0]:
                display.print_assistant_end()
            print()
            return

        if streaming_started[0]:
            display.print_assistant_end()
        elif text:
            display.print_assistant(text)

        session.add_assistant(text, thinking=thinking, tool_calls=tool_exchanges)
        session.save()

    # ── One-shot or interactive ──────────────────────────────────────────────
    if args.message:
        run_turn(args.message)
        if args.non_interactive:
            return

    if args.non_interactive and not args.message:
        parser.error("--non-interactive requires a MESSAGE argument")

    # ── Readline history ─────────────────────────────────────────────────────
    try:
        import readline
        import atexit
        from pathlib import Path as _Path
        _hist = _Path.home() / ".local" / "share" / "nugget" / "history"
        _hist.parent.mkdir(parents=True, exist_ok=True)
        try:
            lines = _hist.read_text().splitlines()
            cleaned = [l for l in lines if l.strip() and l.strip() != "/"]
            if len(cleaned) != len(lines):
                _hist.write_text("\n".join(cleaned) + "\n")
            readline.read_history_file(_hist)
        except FileNotFoundError:
            pass
        readline.set_history_length(1000)
        atexit.register(readline.write_history_file, _hist)
    except ImportError:
        pass

    # ── Command context ──────────────────────────────────────────────────────
    ctx = CommandContext(
        session_cell=session_cell,
        cfg=cfg,
        active_schemas=active_schemas,
        get_system_prompt=_system_prompt,
        sessions_path=cfg.sessions_path(),
    )

    while True:
        user_input = display.print_user_prompt()
        if not user_input:
            break
        if user_input.startswith("/"):
            if commands_mod.dispatch(user_input, ctx) == "exit":
                break
            continue
        run_turn(user_input)


if __name__ == "__main__":
    main()
