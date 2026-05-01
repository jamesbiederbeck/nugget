import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = {
    "type": "function",
    "function": {
        "name": "filebrowser",
        "description": (
            "Browse and edit the local filesystem. "
            "Operations: 'cwd', 'ls', 'cat', 'read_lines', 'stat', 'glob', "
            "'write', 'append', 'replace', 'mkdir', 'move', 'backup', 'restore_backup'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": (
                        "One of: 'cwd', 'ls', 'cat', 'read_lines', 'stat', 'glob', "
                        "'write', 'append', 'replace', 'mkdir', 'move', 'backup', 'restore_backup'"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Path for most operations. Omit for 'cwd'.",
                },
                "content": {
                    "type": "string",
                    "description": "Text to write or append (required for 'write' and 'append').",
                },
                "old": {
                    "type": "string",
                    "description": "Literal string to find (required for 'replace'). May not be empty.",
                },
                "new": {
                    "type": "string",
                    "description": "Replacement string (required for 'replace').",
                },
                "count": {
                    "type": "integer",
                    "description": "Max replacements for 'replace'. Default 1; -1 = all occurrences.",
                },
                "start": {
                    "type": "integer",
                    "description": "1-indexed first line to read (required for 'read_lines').",
                },
                "end": {
                    "type": "integer",
                    "description": "1-indexed last line to read, inclusive (optional for 'read_lines'; defaults to EOF).",
                },
                "dest": {
                    "type": "string",
                    "description": "Destination path for 'backup' (auto-generated if omitted) or 'move' (required).",
                },
                "backup_path": {
                    "type": "string",
                    "description": "Backup file to restore from (required for 'restore_backup').",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (required for 'glob').",
                },
                "parents": {
                    "type": "boolean",
                    "description": "If true, 'mkdir' creates intermediate directories. Default false.",
                },
            },
            "required": ["operation"],
        },
    },
}

_READ_OPS = {"cwd", "ls", "cat", "read_lines", "stat", "glob"}


def APPROVAL(args: dict) -> str:
    return "allow" if args.get("operation", "") in _READ_OPS else "ask"


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

    if op == "read_lines":
        if not path_arg:
            return {"error": "'read_lines' requires a path"}
        start = args.get("start")
        if start is None:
            return {"error": "'read_lines' requires 'start'"}
        if not isinstance(start, int) or start < 1:
            return {"error": "'start' must be a positive integer"}
        target = Path(path_arg).expanduser().resolve()
        if not target.exists():
            return {"error": f"file not found: {target}"}
        if target.is_dir():
            return {"error": f"is a directory: {target}"}
        all_lines = target.read_text(errors="replace").splitlines(keepends=True)
        total = len(all_lines)
        end = args.get("end", total)
        if not isinstance(end, int) or end < 1:
            return {"error": "'end' must be a positive integer"}
        end = min(end, total)
        if start > total:
            return {"path": str(target), "lines": [], "start": start, "end": start, "total_lines": total}
        if end < start:
            return {"error": f"'end' ({end}) is less than 'start' ({start})"}
        return {
            "path": str(target),
            "lines": all_lines[start - 1:end],
            "start": start,
            "end": end,
            "total_lines": total,
        }

    if op == "stat":
        if not path_arg:
            return {"error": "'stat' requires a path"}
        target = Path(path_arg).expanduser().resolve()
        if not target.exists():
            return {"error": f"path not found: {target}"}
        s = target.stat()
        mtime = datetime.fromtimestamp(s.st_mtime, tz=timezone.utc).isoformat()
        return {
            "path": str(target),
            "size": s.st_size,
            "mtime_iso": mtime,
            "is_file": target.is_file(),
            "is_dir": target.is_dir(),
            "is_symlink": target.is_symlink(),
            "permissions_octal": oct(s.st_mode),
        }

    if op == "glob":
        pattern = args.get("pattern")
        if not pattern:
            return {"error": "'glob' requires a 'pattern'"}
        base = Path(path_arg).expanduser().resolve() if path_arg else Path.cwd()
        if not base.exists():
            return {"error": f"path not found: {base}"}
        if not base.is_dir():
            return {"error": f"not a directory: {base}"}
        raw = sorted(base.glob(pattern))
        truncated = len(raw) > 500
        matches = [
            {"path": str(p), "type": "dir" if p.is_dir() else "file", "size": p.stat().st_size}
            for p in raw[:500]
        ]
        return {"base": str(base), "pattern": pattern, "matches": matches, "truncated": truncated}

    if op == "write":
        if not path_arg:
            return {"error": "'write' requires a path"}
        if "content" not in args:
            return {"error": "'write' requires 'content'"}
        target = Path(path_arg).expanduser().resolve()
        if not target.parent.exists():
            return {"error": f"parent directory does not exist: {target.parent}"}
        created = not target.exists()
        target.write_text(args["content"])
        return {"path": str(target), "size": target.stat().st_size, "created": created}

    if op == "append":
        if not path_arg:
            return {"error": "'append' requires a path"}
        if "content" not in args:
            return {"error": "'append' requires 'content'"}
        target = Path(path_arg).expanduser().resolve()
        if not target.parent.exists():
            return {"error": f"parent directory does not exist: {target.parent}"}
        with target.open("a") as f:
            f.write(args["content"])
        return {"path": str(target), "size": target.stat().st_size}

    if op == "replace":
        if not path_arg:
            return {"error": "'replace' requires a path"}
        old = args.get("old")
        if old is None:
            return {"error": "'replace' requires 'old'"}
        if old == "":
            return {"error": "'old' must not be empty"}
        if "new" not in args:
            return {"error": "'replace' requires 'new'"}
        new = args["new"]
        count = args.get("count", 1)
        if not isinstance(count, int) or count == 0:
            return {"error": "'count' must be a non-zero integer or -1 for all"}
        target = Path(path_arg).expanduser().resolve()
        if not target.exists():
            return {"error": f"file not found: {target}"}
        if target.is_dir():
            return {"error": f"is a directory: {target}"}
        content = target.read_text(errors="replace")
        n_found = content.count(old)
        if n_found == 0:
            return {"error": f"'old' string not found in {target}"}
        if count == -1:
            new_content = content.replace(old, new)
            n_replaced = n_found
        else:
            new_content = content.replace(old, new, count)
            n_replaced = min(n_found, count)
        target.write_text(new_content, errors="replace")
        return {"path": str(target), "replacements": n_replaced}

    if op == "mkdir":
        if not path_arg:
            return {"error": "'mkdir' requires a path"}
        target = Path(path_arg).expanduser().resolve()
        created = not target.exists()
        parents = args.get("parents", False)
        try:
            target.mkdir(parents=parents, exist_ok=True)
        except FileNotFoundError:
            return {"error": f"parent directory does not exist (use parents=true): {target.parent}"}
        return {"path": str(target), "created": created}

    if op == "move":
        if not path_arg:
            return {"error": "'move' requires a path"}
        dest_arg = args.get("dest")
        if not dest_arg:
            return {"error": "'move' requires 'dest'"}
        target = Path(path_arg).expanduser().resolve()
        dest = Path(dest_arg).expanduser().resolve()
        if not target.exists():
            return {"error": f"source not found: {target}"}
        if not dest.parent.exists():
            return {"error": f"destination parent does not exist: {dest.parent}"}
        shutil.move(str(target), str(dest))
        return {"path": str(target), "dest": str(dest)}

    if op == "backup":
        if not path_arg:
            return {"error": "'backup' requires a path"}
        target = Path(path_arg).expanduser().resolve()
        if not target.exists():
            return {"error": f"file not found: {target}"}
        if target.is_dir():
            return {"error": f"is a directory: {target}"}
        dest_arg = args.get("dest")
        if dest_arg:
            backup_path = Path(dest_arg).expanduser().resolve()
        else:
            ts = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
            backup_path = Path(f"/tmp/nugget/backups/{target.name}.{ts}.bak")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(target), str(backup_path))
        return {"path": str(target), "backup_path": str(backup_path)}

    if op == "restore_backup":
        if not path_arg:
            return {"error": "'restore_backup' requires a path"}
        backup_arg = args.get("backup_path")
        if not backup_arg:
            return {"error": "'restore_backup' requires 'backup_path'"}
        dest = Path(path_arg).expanduser().resolve()
        backup = Path(backup_arg).expanduser().resolve()
        if not backup.exists():
            return {"error": f"backup not found: {backup}"}
        if backup.is_dir():
            return {"error": f"backup path is a directory: {backup}"}
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(backup), str(dest))
        return {"path": str(dest), "restored_from": str(backup)}

    return {"error": f"unknown operation: {op!r}"}
