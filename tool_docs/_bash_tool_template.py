"""
Bash-wrapping tool template.

To create a new tool from this template:
  1. Copy this file to src/nugget/tools/your_tool_name.py
  2. Fill in the ── CONFIGURE ── section below.
  3. That's it — the tool is auto-discovered on next run.

The COMMAND string is a Python str.format() template.
Each key in ARGS must appear as {key} in COMMAND.

Example:
  TOOL_NAME = "ping_host"
  COMMAND    = "ping -c {count} {host}"
  ARGS = {
      "host":  {"type": "string",  "description": "Hostname or IP to ping", "required": True},
      "count": {"type": "integer", "description": "Number of packets",      "required": False, "default": 4},
  }
"""

import subprocess

# ── CONFIGURE ────────────────────────────────────────────────────────────────

TOOL_NAME   = "my_bash_tool"
DESCRIPTION = "One-sentence description shown to the model."
COMMAND     = "echo {message}"          # use {arg_name} placeholders
TIMEOUT     = 10                        # seconds; None = no limit
APPROVAL    = "allow"                   # "allow" | "deny" | "ask"

# Each key must match a {placeholder} in COMMAND.
# Fields:
#   type        — JSON Schema type: "string" | "integer" | "number" | "boolean"
#   description — shown to the model
#   required    — if False, 'default' is substituted when the model omits the arg
#   default     — only used when required=False
ARGS: dict[str, dict] = {
    "message": {
        "type": "string",
        "description": "The message to echo",
        "required": True,
    },
    # "count": {
    #     "type": "integer",
    #     "description": "How many times",
    #     "required": False,
    #     "default": 1,
    # },
}

# ── END CONFIGURE — nothing below should need editing ─────────────────────────

# ---------------------------------------------------------------------------
# Build SCHEMA from the variables above
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# execute() — called by the tool registry
# ---------------------------------------------------------------------------

def execute(args: dict) -> dict:
    # Apply defaults for optional args the model didn't supply.
    filled: dict = {}
    for name, spec in ARGS.items():
        if name in args:
            filled[name] = args[name]
        elif not spec.get("required", True):
            filled[name] = spec["default"]
        else:
            return {"error": f"missing required argument: '{name}'"}

    # Render the command.
    try:
        cmd = COMMAND.format(**filled)
    except KeyError as e:
        return {"error": f"COMMAND template references unknown placeholder: {e}"}

    # Run it.
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
