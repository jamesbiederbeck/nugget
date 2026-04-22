import subprocess

APPROVAL = "ask"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Run a shell command and return its output. Use with caution.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 10)",
                },
            },
            "required": ["command"],
        },
    },
}


def execute(args: dict) -> dict:
    command = args.get("command", "")
    timeout = args.get("timeout", 10)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}
