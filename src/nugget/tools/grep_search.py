import subprocess

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "grep_search",
        "description": (
            "Search for a pattern across files using ripgrep. "
            "Returns matching lines with file paths and line numbers. "
            "Faster and safer than using shell for code search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (literal string or regex)",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (default: current working directory)",
                },
                "include": {
                    "type": "string",
                    "description": "Glob to restrict file types, e.g. '*.py' or '*.{ts,tsx}'",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "If false (default), search is case-insensitive",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default 50)",
                },
            },
            "required": ["pattern"],
        },
    },
}


def execute(args: dict) -> dict:
    pattern = args.get("pattern", "")
    if not pattern:
        return {"error": "pattern is required"}

    path = args.get("path", ".")
    include = args.get("include")
    case_sensitive = bool(args.get("case_sensitive", False))
    max_results = int(args.get("max_results", 50))

    cmd = ["rg", "--line-number", "--no-heading", "--max-count", str(max_results)]
    if not case_sensitive:
        cmd.append("--ignore-case")
    if include:
        cmd.extend(["--glob", include])
    cmd.extend(["--", pattern, path])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        # rg exit code 1 = no matches (not an error)
        if result.returncode not in (0, 1):
            return {
                "error": result.stderr.strip() or f"rg exited with code {result.returncode}",
                "pattern": pattern,
            }
        matches = [ln for ln in result.stdout.splitlines() if ln]
        return {
            "pattern": pattern,
            "path": path,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
        }
    except FileNotFoundError:
        return {"error": "ripgrep (rg) not found — install it or use the shell tool"}
    except subprocess.TimeoutExpired:
        return {"error": "search timed out after 15s", "pattern": pattern}
    except Exception as e:
        return {"error": str(e), "pattern": pattern}
