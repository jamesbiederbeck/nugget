import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "claude_history",
        "description": (
            "Search and read past Claude Code conversations (AKA *'Sessions'*) via the claude-history "
            "agent protocol. Workflow: 'list' shows the most recent sessions for a "
            "directory (no ch_ ref needed — just session ids, timestamps, previews); "
            "'search' finds conversations (returns ch_ ref handles with message refs "
            "like m7..m9); 'within' narrows the search to one conversation; 'outline' "
            "summarises a conversation's structure; 'read' reads message ranges, e.g. "
            "refs=['ch_1234abcd5678:m7..m9']. Use search_mode 'semantic' or 'hybrid' "
            "for conceptual recall, 'lexical' or 'exact' for identifiers, filenames, "
            "and error messages. Always pass the ch_ handles emitted by search, never "
            "session UUIDs, to 'within'/'read'/'outline'. Prefer bounded reads over "
            "full transcripts. 'list' and 'search' (when scope='local') default to "
            "the nugget process's current working directory — pass a 'directory' arg "
            "to target a different workspace, or scope='global' on 'search' to search "
            "every workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of: 'list', 'search', 'within', 'read', 'outline'",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for 'search' and 'within')",
                },
                "conversation": {
                    "type": "string",
                    "description": (
                        "Conversation ref handle, e.g. 'ch_1234abcd5678' "
                        "(required for 'within' and 'outline')"
                    ),
                },
                "refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Conversation or message range refs for 'read', e.g. "
                        "['ch_1234abcd5678', 'ch_1234abcd5678:m7..m9']"
                    ),
                },
                "focus": {
                    "type": "string",
                    "description": (
                        "Message range to prioritise when 'read' output is "
                        "truncated by the budget, e.g. 'm8..m8'"
                    ),
                },
                "search_mode": {
                    "type": "string",
                    "description": (
                        "Search algorithm for 'search' and 'within': 'hybrid' "
                        "(default), 'semantic', 'lexical', or 'exact'"
                    ),
                },
                "scope": {
                    "type": "string",
                    "description": "Scope for 'search': 'local' (default) or 'global'",
                },
                "directory": {
                    "type": "string",
                    "description": (
                        "Absolute directory path to scope the operation to. Used by "
                        "'list' (which directory's sessions to list) and 'search' "
                        "(when scope='local', which workspace to restrict to). "
                        "Defaults to the nugget process's current working directory."
                    ),
                },
                "top": {
                    "type": "integer",
                    "description": (
                        "Max results for 'list' (default 10), 'search' (default 10), "
                        "or 'within' (default 20)"
                    ),
                },
                "hits_per_conv": {
                    "type": "integer",
                    "description": "Max evidence hits per conversation in 'search' output (default 2)",
                },
                "budget": {
                    "type": "integer",
                    "description": "Output token budget for 'read' and 'outline' (default 6000)",
                },
                "include_tools": {
                    "type": "boolean",
                    "description": "Include tool calls in 'read' and 'outline' output (default false)",
                },
                "include_tool_results": {
                    "type": "boolean",
                    "description": "Include tool results in 'read' and 'outline' output (default false)",
                },
                "include_thinking": {
                    "type": "boolean",
                    "description": "Include thinking blocks in 'read' and 'outline' output (default false)",
                },
            },
            "required": ["operation"],
        },
    },
}

_MODES = ("hybrid", "semantic", "lexical", "exact")


def _run(cmd: list[str], timeout: int = 60, cwd: str | None = None) -> dict:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or os.getcwd()
        )
    except FileNotFoundError:
        return {"error": "claude-history not found — install it first"}
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout}s"}
    if result.returncode != 0:
        err = result.stderr.strip()
        return {"error": err or f"claude-history exited with code {result.returncode}"}
    return {"output": result.stdout.strip()}


def _read_flags(args: dict) -> list[str]:
    flags = []
    if args.get("budget"):
        flags.extend(["--budget", str(args["budget"])])
    if args.get("include_tools"):
        flags.append("--tools")
    if args.get("include_tool_results"):
        flags.append("--tool-results")
    if args.get("include_thinking"):
        flags.append("--thinking")
    return flags


def _project_dir(directory: str) -> Path:
    resolved = os.path.abspath(os.path.expanduser(directory))
    slug = resolved.replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / slug


def _session_preview(path: Path, max_chars: int = 200) -> str:
    try:
        with open(path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "user":
                    continue
                content = obj.get("message", {}).get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                else:
                    text = ""
                text = text.strip()
                if text:
                    return text[:max_chars]
    except OSError:
        pass
    return ""


def _list_sessions(directory: str, top: int) -> dict:
    proj_dir = _project_dir(directory)
    if not proj_dir.is_dir():
        return {"error": f"no session history found for directory '{directory}'"}
    files = sorted(
        (p for p in proj_dir.glob("*.jsonl") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:top]
    sessions = [
        {
            "session": p.stem,
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "preview": _session_preview(p),
        }
        for p in files
    ]
    return {"output": json.dumps(sessions, indent=2)}


def execute(args: dict) -> dict:
    op = args.get("operation", "")
    mode = args.get("search_mode")
    directory = args.get("directory") or os.getcwd()

    if op == "list":
        return _list_sessions(directory, args.get("top") or 10)

    elif op == "search":
        query = args.get("query")
        if not query:
            return {"error": "'search' requires query"}
        cmd = ["claude-history", "agent", "search"]
        cmd.append("--all" if args.get("scope") == "global" else "--local")
        if args.get("top"):
            cmd.extend(["--top", str(args["top"])])
        if args.get("hits_per_conv"):
            cmd.extend(["--hits-per-conv", str(args["hits_per_conv"])])
        if mode in _MODES:
            cmd.append(f"--{mode}")
        cmd.append(query)
        # first semantic search may build the embedding index
        return _run(cmd, timeout=300, cwd=directory)

    elif op == "within":
        conversation = args.get("conversation")
        query = args.get("query")
        if not conversation:
            return {"error": "'within' requires conversation"}
        if not query:
            return {"error": "'within' requires query"}
        cmd = ["claude-history", "agent", "within"]
        if args.get("top"):
            cmd.extend(["--top", str(args["top"])])
        if mode in _MODES:
            cmd.append(f"--{mode}")
        cmd.extend([conversation, query])
        return _run(cmd, timeout=300)

    elif op == "read":
        refs = args.get("refs") or (
            [args["conversation"]] if args.get("conversation") else None
        )
        if not refs:
            return {"error": "'read' requires refs"}
        cmd = ["claude-history", "agent", "read", *_read_flags(args)]
        if args.get("focus"):
            cmd.extend(["--focus", args["focus"]])
        cmd.extend(refs)
        return _run(cmd)

    elif op == "outline":
        conversation = args.get("conversation")
        if not conversation:
            return {"error": "'outline' requires conversation"}
        cmd = ["claude-history", "agent", "outline", *_read_flags(args)]
        cmd.append(conversation)
        return _run(cmd)

    else:
        return {"error": f"unknown operation '{op}' — use list, search, within, read, or outline"}
