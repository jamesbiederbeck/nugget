SCHEMA = {
    "type": "function",
    "function": {
        "name": "render_output",
        "description": (
            "Call any tool and send its output somewhere. "
            "Use this when you want to display a tool's result to the user, "
            "save it to a file, or bind it to a variable — "
            "instead of calling the tool directly and receiving the result inline. "
            "Specify the destination with the output argument."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to call, e.g. 'wallabag' or 'shell'",
                },
                "tool_args": {
                    "type": "object",
                    "description": "Arguments to pass to the tool",
                },
            },
            "required": ["tool_name", "tool_args"],
        },
    },
}

APPROVAL = "allow"


def execute(args: dict) -> dict:
    raise NotImplementedError("render_output is not yet implemented")
