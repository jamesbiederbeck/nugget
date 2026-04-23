"""
ping_host — example bash-wrapped tool built from _bash_tool_template.py.

Copy to src/nugget/tools/ping_host.py to activate.
"""

import subprocess

# ── CONFIGURE ────────────────────────────────────────────────────────────────

TOOL_NAME   = "ping_host"
DESCRIPTION = "Ping a host and return packet loss and round-trip statistics."
COMMAND     = "ping -c {count} -W {wait} {host}"
TIMEOUT     = 30
APPROVAL    = "allow"

ARGS: dict[str, dict] = {
    "host": {
        "type": "string",
        "description": "Hostname or IP address to ping",
        "required": True,
    },
    "count": {
        "type": "integer",
        "description": "Number of ICMP packets to send",
        "required": False,
        "default": 4,
    },
    "wait": {
        "type": "integer",
        "description": "Seconds to wait for each reply before timing out",
        "required": False,
        "default": 1,
    },
}

# ── END CONFIGURE — nothing below should need editing ─────────────────────────

SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                name: {
                    "type": spec["type"],
                    "description": spec["description"],
                }
                for name, spec in ARGS.items()
            },
            "required": [name for name, spec in ARGS.items() if spec.get("required", True)],
        },
    },
}


def execute(args: dict) -> dict:
    filled: dict = {}
    for name, spec in ARGS.items():
        if name in args:
            filled[name] = args[name]
        elif not spec.get("required", True):
            filled[name] = spec["default"]
        else:
            return {"error": f"missing required argument: '{name}'"}

    try:
        cmd = COMMAND.format(**filled)
    except KeyError as e:
        return {"error": f"COMMAND template references unknown placeholder: {e}"}

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return {
            "stdout":     result.stdout.strip(),
            "stderr":     result.stderr.strip(),
            "returncode": result.returncode,
            "command":    cmd,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"command timed out after {TIMEOUT}s", "command": cmd}
    except Exception as e:
        return {"error": str(e), "command": cmd}
