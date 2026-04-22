import os
from pathlib import Path

SCHEMA = {
    "type": "function",
    "function": {
        "name": "filebrowser",
        "description": (
            "Browse the local filesystem. "
            "Operations: 'cwd' returns the current working directory; "
            "'ls' lists files in a directory (defaults to cwd); "
            "'cat' reads the contents of a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of: 'cwd', 'ls', 'cat'",
                },
                "path": {
                    "type": "string",
                    "description": "Path for 'ls' (directory) or 'cat' (file). Omit for 'cwd'.",
                },
            },
            "required": ["operation"],
        },
    },
}


def execute(args: dict) -> dict:
    op = args.get("operation", "").strip().lower()
    path_arg = args.get("path")

    if op == "cwd":
        return {"cwd": os.getcwd()}

    if op == "ls":
        target = Path(path_arg) if path_arg else Path.cwd()
        try:
            target = target.expanduser().resolve()
            if not target.exists():
                return {"error": f"path not found: {target}"}
            if not target.is_dir():
                return {"error": f"not a directory: {target}"}
            entries = []
            for p in sorted(target.iterdir()):
                stat = p.stat()
                entries.append({
                    "name": p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": stat.st_size,
                })
            return {"path": str(target), "entries": entries}
        except PermissionError:
            return {"error": f"permission denied: {target}"}

    if op == "cat":
        if not path_arg:
            return {"error": "'cat' requires a path"}
        target = Path(path_arg).expanduser().resolve()
        try:
            if not target.exists():
                return {"error": f"file not found: {target}"}
            if target.is_dir():
                return {"error": f"is a directory: {target}"}
            content = target.read_text(errors="replace")
            return {"path": str(target), "content": content, "size": target.stat().st_size}
        except PermissionError:
            return {"error": f"permission denied: {target}"}

    return {"error": f"unknown operation: {op!r}. Use 'cwd', 'ls', or 'cat'"}
