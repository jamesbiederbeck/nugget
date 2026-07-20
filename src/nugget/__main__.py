"""
python -m nugget [OPTIONS] [MESSAGE]

Interactive or one-shot chat via a configurable local model backend.
"""

import argparse
import subprocess
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError as _PNF

from .config import Config
from .backends import make_backend, BackendError
from .session import Session
from . import tools as tool_registry
from . import mcp_client
from . import display
from . import approval as approval_mod
from . import commands as commands_mod
from .commands import CommandContext
from .tools.memory import get_pinned as _get_pinned
from .subagent import _session_id as _subagent_session_id


def _run_shell_passthrough(cmd: str) -> str:
    """
    Run a shell command, streaming output to the terminal live (same as a
    real shell) while also capturing it to return — the caller decides how
    much of the return value (if any) enters conversation context.
    """
    proc = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    captured = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
        captured.append(line)
    proc.wait()
    return "".join(captured)


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nugget",
        description="Chat with a locally-hosted model",
    )

    p.add_argument("message", nargs="?", help="Initial message (omit for interactive)")
    p.add_argument("--session", "-s", metavar="ID", help="Session ID to resume or create")
    p.add_argument("--list-sessions", action="store_true", help="List saved sessions and exit")
    p.add_argument("--non-interactive", "-n", action="store_true",
                   help="Exit after the first response (requires MESSAGE or stdin)")

    # Tool filtering
    tg = p.add_argument_group("tool filtering")
    tg.add_argument("--include-tools", metavar="t1,t2",
                    help="Only expose these tools (comma-separated)")
    tg.add_argument("--exclude-tools", metavar="t1,t2",
                    help="Exclude these tools (comma-separated)")
    tg.add_argument("--list-tools", action="store_true", help="List available tools and exit")
    p.add_argument("--profile", metavar="NAME", help="Named config profile to activate")

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
    p.add_argument("--api-url", metavar="URL", help="Backend API URL (e.g. http://host:5000)")
    p.add_argument("--model", metavar="MODEL", help="Model to use (e.g. openai/gpt-4o for openrouter backend)")
    p.add_argument("--system", metavar="PROMPT", help="Override system prompt for this run")
    p.add_argument("--max-tokens", type=int, metavar="N")
    p.add_argument("--temperature", type=float, metavar="F")

    try:
        _ver = _pkg_version("nugget")
    except _PNF:
        _ver = "unknown (package not installed)"
    p.add_argument("--version", action="version", version=f"nugget {_ver}")

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
    if args.api_url:
        overrides["api_url"] = args.api_url
    if args.model:
        overrides["openrouter_model"] = args.model
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

    # Capture CLI flags before Config() so /profile can re-apply them
    _cli_overrides = dict(overrides)
    _cli_include = [t.strip() for t in args.include_tools.split(",")] if args.include_tools else None
    _cli_exclude = [t.strip() for t in args.exclude_tools.split(",")] if args.exclude_tools else None

    cfg = Config(overrides, profile=args.profile)

    # If a CLI flag pins thinking effort, freeze it; otherwise read cfg dynamically
    # so that /profile switches pick up the new profile's thinking_effort value.
    _cli_thinking_effort = resolve_thinking_effort(args, cfg) if (
        args.thinking_effort is not None or args.thinking is not None
    ) else None

    def get_thinking_effort() -> int:
        if _cli_thinking_effort is not None:
            return _cli_thinking_effort
        return cfg.thinking_effort

    # ── Tool schema selection ────────────────────────────────────────────────
    if args.include_tools:
        include = [t.strip() for t in args.include_tools.split(",")]
    elif cfg.get("include_tools"):
        include = cfg.get("include_tools")
    else:
        include = None

    if args.exclude_tools:
        exclude = [t.strip() for t in args.exclude_tools.split(",")]
    elif cfg.get("exclude_tools"):
        exclude = cfg.get("exclude_tools")
    else:
        exclude = None

    active_schemas = tool_registry.schemas(include=include, exclude=exclude) + mcp_client.schemas(cfg)

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
    backend_cell = [backend]
    active_schemas_cell = [active_schemas]

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
        preview = build_prompt([], active_schemas, _system_prompt(), get_thinking_effort())
        display.print_system_prompt(preview)

    thinking_open = [False]

    def on_thinking(text: str) -> None:
        if not cfg.show_thinking:
            return
        if not thinking_open[0]:
            display.print_thinking_begin()
            thinking_open[0] = True
        display.print_thinking_token(text)

    def on_thinking_end() -> None:
        if cfg.show_thinking and thinking_open[0]:
            display.print_thinking_end()
        thinking_open[0] = False

    def on_tool_call(name: str, args: dict) -> None:
        if cfg.show_tool_calls:
            display.print_tool_call(name, args)

    def on_tool_response(name: str, result: object) -> None:
        if cfg.show_tool_responses:
            display.print_tool_response(name, result)

    def on_tool_routed(name: str, result: object, sink: str) -> None:
        # Routed results never enter the model's context, so always surface
        # them to the user regardless of cfg.show_tool_responses.
        display.print_routed_output(name, result, sink)

    def on_tool_denied(name: str, reason: str) -> None:
        display.print_error(f"tool '{name}' not executed: {reason}")

    def sink_approval_prompt(name: str, abs_path) -> bool:
        if not sys.stdin.isatty():
            return False
        print(f"\n{display.BOLD}{display.YELLOW}[approval]{display.RESET} "
              f"{display.CYAN}{name}{display.RESET} "
              f"{display.DIM}write → {abs_path}{display.RESET}")
        return display.ask_yes_no(f"{display.BOLD}Allow? [y/N]{display.RESET} ")

    def tool_executor(name: str, args: dict) -> object:
        is_mcp = mcp_client.owns(name)
        gate = mcp_client.gate(name) if is_mcp else tool_registry.gate(name)
        approved, reason = approval_mod.check(name, args, gate, cfg.approval_config())
        if not approved:
            return {"_denied": True, "reason": reason}
        return mcp_client.execute(name, args) if is_mcp else tool_registry.execute(name, args)

    def run_turn(user_input: str) -> None:
        session = session_cell[0]
        session.add_user(user_input)

        streaming_started = [False]

        def on_token(tok: str) -> None:
            if not streaming_started[0]:
                display.print_assistant_begin()
                streaming_started[0] = True
            display.print_token(tok)

        sid_token = _subagent_session_id.set(session.id)
        try:
            text, thinking, tool_exchanges, _ = backend_cell[0].run(
                messages=session.messages,
                tool_schemas=active_schemas_cell[0],
                tool_executor=tool_executor,
                system_prompt=_system_prompt(),
                thinking_effort=get_thinking_effort(),
                on_thinking=on_thinking,
                on_thinking_end=on_thinking_end,
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
        finally:
            _subagent_session_id.reset(sid_token)

        if streaming_started[0]:
            display.print_assistant_end()
        elif text:
            display.print_assistant(text)

        session.add_assistant(text, thinking=thinking, tool_calls=tool_exchanges)
        session.save()

    # ── stdin detection ──────────────────────────────────────────────────────
    stdin_text = ""
    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read().strip()

    if stdin_text:
        combined = f"{args.message}\n\n{stdin_text}" if args.message else stdin_text
        run_turn(combined)
        return

    # ── One-shot or interactive ──────────────────────────────────────────────
    if args.message:
        run_turn(args.message)
        if args.non_interactive:
            return

    if args.non_interactive and not args.message:
        parser.error("--non-interactive requires a MESSAGE argument or stdin input")

    # ── prompt_toolkit setup ─────────────────────────────────────────────────
    if sys.stdin.isatty():
        from pathlib import Path as _Path
        from .commands import COMMAND_DESCRIPTIONS
        _pt_hist = _Path.home() / ".local" / "share" / "nugget" / "prompt_history"
        display.setup_prompt(COMMAND_DESCRIPTIONS, _pt_hist)

    # ── Command context ──────────────────────────────────────────────────────
    ctx = CommandContext(
        session_cell=session_cell,
        cfg=cfg,
        active_schemas_cell=active_schemas_cell,
        backend_cell=backend_cell,
        get_system_prompt=_system_prompt,
        sessions_path=cfg.sessions_path(),
        cli_overrides=_cli_overrides,
        cli_include=_cli_include,
        cli_exclude=_cli_exclude,
    )

    while True:
        user_input = display.print_user_prompt()
        if not user_input:
            break
        if user_input.startswith("/"):
            if commands_mod.dispatch(user_input, ctx) == "exit":
                break
            continue
        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if shell_cmd:
                display.print_shell_command(shell_cmd)
                try:
                    output = _run_shell_passthrough(shell_cmd)
                except OSError as e:
                    display.print_error(str(e))
                else:
                    max_chars = cfg.get("shell_output_max_chars", 1000)
                    truncated = output[:max_chars]
                    note = ""
                    if len(output) > max_chars:
                        note = f"\n... [truncated, {len(output) - max_chars} more characters]"
                    context_msg = (
                        "(I ran a shell command myself, directly in my terminal — not "
                        "via your shell tool. This is just the output, for your "
                        "reference. Don't re-run it.)\n"
                        f"$ {shell_cmd}\n{truncated}{note}"
                    )
                    session = session_cell[0]
                    session.add_user(context_msg)
                    session.save()
                    display.print_dim(f"[added to context, {len(truncated)} chars]")
            continue
        run_turn(user_input)


if __name__ == "__main__":
    main()
