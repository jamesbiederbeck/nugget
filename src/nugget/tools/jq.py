import json

import jmespath
import jmespath.exceptions

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "jq",
        "description": (
            "Apply a JMESPath query to JSON data. "
            "Accepts a raw JSON string or an already-decoded object (e.g. from a $var binding). "
            "Use this to slice, filter, or transform large tool payloads before displaying them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "JSON string to query, or a variable reference like $var",
                },
                "query": {
                    "type": "string",
                    "description": "JMESPath expression, e.g. 'items[?status==`open`].id'",
                },
            },
            "required": ["data", "query"],
        },
    },
}


def execute(args: dict) -> dict:
    raw = args.get("data")
    query = args.get("query", "").strip()

    if raw is None:
        return {"error": "data is required"}
    if not query:
        return {"error": "query is required"}

    # data may be a pre-decoded dict/list (from $var binding) or a JSON string
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return {"error": f"data is not valid JSON: {e}", "query": query}
    else:
        data = raw

    try:
        result = jmespath.search(query, data)
    except jmespath.exceptions.JMESPathError as e:
        return {"error": f"invalid JMESPath: {e}", "query": query}

    return {"result": result, "query": query}
