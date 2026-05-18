"""
prompt — let the model ask the user for input mid-conversation.

Returns {"answer": str} or {"error": str} if no terminal is available
(e.g. called from a subagent or non-interactive session).
"""

import sys

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "prompt",
        "description": (
            "Ask the user a question mid-conversation and return their answer. "
            "Supports free-text or selection from a list of choices. "
            "Do not use in automated or non-interactive contexts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to present to the user.",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of choices. The user may select by number "
                        "or by typing (tab-completion supported). Omit for free-text."
                    ),
                },
            },
            "required": ["question"],
        },
    },
}


def execute(args: dict) -> dict:
    question = args.get("question", "").strip()
    if not question:
        return {"error": "question is required"}

    choices = args.get("choices") or None
    if choices is not None and not isinstance(choices, list):
        return {"error": "choices must be a list of strings"}

    if not sys.stdin.isatty():
        return {"error": "prompt tool requires an interactive terminal (stdin is not a tty)"}

    from .. import display
    try:
        answer = display.prompt_user(question, choices)
    except RuntimeError as e:
        return {"error": str(e)}

    return {"answer": answer}
