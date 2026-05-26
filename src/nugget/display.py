import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

# ANSI colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RED = "\033[31m"
WHITE = "\033[37m"

_pt_session: "PromptSession | None" = None


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


def setup_prompt(command_descriptions: dict[str, str], history_path) -> None:
    """Initialize the prompt_toolkit session. Call once from main when stdin is a tty."""
    global _pt_session
    from pathlib import Path as _Path
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import ConditionalCompleter
    from prompt_toolkit.filters import Condition
    from .completer import SlashCommandCompleter

    hist = _Path(history_path)
    hist.parent.mkdir(parents=True, exist_ok=True)

    _slash_completer = SlashCommandCompleter(command_descriptions)

    _pt_session = PromptSession(
        history=FileHistory(str(hist)),
        completer=ConditionalCompleter(
            _slash_completer,
            Condition(lambda: _pt_session.app.current_buffer.text.startswith("/")),
        ),
        complete_while_typing=True,
    )


def print_thinking(text: str) -> None:
    print(f"\n{DIM}{MAGENTA}[thinking]{RESET}")
    for line in text.strip().splitlines():
        print(f"  {DIM}{line}{RESET}")
    print(f"{DIM}{MAGENTA}[/thinking]{RESET}\n")


def print_tool_call(name: str, args: dict) -> None:
    import json
    args_str = json.dumps(args, indent=2)
    print(f"\n{BOLD}{CYAN}→ tool:{RESET} {CYAN}{name}{RESET}")
    for line in args_str.splitlines():
        print(f"  {DIM}{line}{RESET}")


def print_tool_response(name: str, result: object) -> None:
    import json
    result_str = json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
    print(f"{BOLD}{GREEN}← result:{RESET} {DIM}{name}{RESET}")
    for line in result_str.splitlines():
        print(f"  {DIM}{line}{RESET}")
    print()


def _extract_display_text(result: object) -> str:
    import json
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and isinstance(result.get("content"), str):
        return result["content"]
    return json.dumps(result, indent=2)


def print_routed_output(name: str, result: object, sink: str) -> None:
    if isinstance(result, dict) and "_display_format" in result:
        result = result["_content"]
    text = _extract_display_text(result)
    print(f"{BOLD}{GREEN}← display:{RESET} {DIM}{name}{RESET}")
    print(text)
    print()


def print_system_prompt(text: str) -> None:
    print(f"\n{DIM}{YELLOW}[system]{RESET}")
    for line in text.strip().splitlines():
        print(f"  {DIM}{line}{RESET}")
    print(f"{DIM}{YELLOW}[/system]{RESET}\n")


def print_assistant(text: str) -> None:
    print(f"\n{BOLD}{WHITE}assistant:{RESET} {text}\n")


def print_assistant_begin() -> None:
    print(f"\n{BOLD}{WHITE}assistant:{RESET} ", end="", flush=True)


def print_assistant_end() -> None:
    print("\n")


def print_token(text: str) -> None:
    print(text, end="", flush=True)


def print_user_prompt() -> str:
    if _pt_session is not None:
        from prompt_toolkit.formatted_text import ANSI
        try:
            return _pt_session.prompt(ANSI(f"{BOLD}{BLUE}you:{RESET} "))
        except EOFError:
            print()
            return ""
        except KeyboardInterrupt:
            print()
            return ""
    try:
        return input(f"\001{BOLD}\002\001{BLUE}\002you:\001{RESET}\002 ")
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def ask_yes_no(prompt_text: str) -> bool:
    """Prompt for y/N using prompt_toolkit if available, else plain input."""
    if _pt_session is not None:
        from prompt_toolkit.formatted_text import ANSI
        try:
            answer = _pt_session.prompt(ANSI(prompt_text)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            answer = ""
    else:
        try:
            answer = input(prompt_text).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            answer = ""
    return answer in ("y", "yes")


def prompt_user(question: str, choices: list[str] | None = None) -> str:
    """
    Interactively ask the user a question (called from the prompt tool).
    If choices are given, shows a numbered list and accepts number or tab-completed text.
    Raises RuntimeError if stdin is not a tty.
    """
    if not sys.stdin.isatty():
        raise RuntimeError("no terminal available")

    print(f"\n{BOLD}{YELLOW}[prompt]{RESET} {question}")

    if choices:
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.formatted_text import ANSI
        for i, c in enumerate(choices, 1):
            print(f"  {DIM}{i}.{RESET} {c}")
        completer = WordCompleter(choices, ignore_case=True)
        while True:
            if _pt_session is not None:
                try:
                    raw = _pt_session.prompt(
                        ANSI(f"{BOLD}Choice:{RESET} "),
                        completer=completer,
                    )
                except (EOFError, KeyboardInterrupt):
                    raw = ""
            else:
                try:
                    raw = input(f"{BOLD}Choice:{RESET} ")
                except (EOFError, KeyboardInterrupt):
                    raw = ""
            raw = raw.strip()
            if not raw:
                continue
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
                print(f"{RED}Enter 1–{len(choices)} or the choice text.{RESET}")
                continue
            matches = [c for c in choices if c.lower().startswith(raw.lower())]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print(f"{RED}Ambiguous — did you mean: {', '.join(matches)}?{RESET}")
                continue
            print(f"{RED}Not a valid choice.{RESET}")
    else:
        from prompt_toolkit.formatted_text import ANSI
        if _pt_session is not None:
            try:
                return _pt_session.prompt(ANSI(f"{BOLD}Answer:{RESET} "))
            except (EOFError, KeyboardInterrupt):
                return ""
        else:
            try:
                return input(f"{BOLD}Answer:{RESET} ")
            except (EOFError, KeyboardInterrupt):
                return ""


def print_error(msg: str) -> None:
    print(f"{RED}error:{RESET} {msg}", file=sys.stderr)


def print_dim(msg: str) -> None:
    print(f"{DIM}{msg}{RESET}")


def print_session_header(session_id: str) -> None:
    print(_c(DIM, f"session {session_id}"))


def print_session_list(sessions: list[dict]) -> None:
    for s in sessions:
        ts = _c(DIM, s["updated_at"][:16])
        sid = _c(CYAN, s["id"])
        tns = _c(DIM, f"[{s['turns']} turns]")
        prv = s["preview"]
        print(f"  {sid}  {ts}  {tns}  {prv}")
