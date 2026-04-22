import sys

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


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


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


def print_system_prompt(text: str) -> None:
    print(f"\n{DIM}{YELLOW}[system]{RESET}")
    for line in text.strip().splitlines():
        print(f"  {DIM}{line}{RESET}")
    print(f"{DIM}{YELLOW}[/system]{RESET}\n")


def print_assistant(text: str) -> None:
    print(f"\n{BOLD}{WHITE}assistant:{RESET} {text}\n")


def print_user_prompt() -> str:
    try:
        return input(f"{BOLD}{BLUE}you:{RESET} ")
    except (EOFError, KeyboardInterrupt):
        print()
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
