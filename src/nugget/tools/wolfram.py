import os
import urllib.parse

import requests

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "wolfram",
        "description": (
            "Query Wolfram|Alpha for computed answers to math, science, geography, "
            "history, unit conversions, and other factual questions. "
            "Convert natural-language questions to concise keyword queries "
            "(e.g. 'France population' not 'how many people live in France'). "
            "Send queries in English only. "
            "Use named physical constants without numerical substitution. "
            "If the result is not relevant, retry with an 'assumption' value from the response."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Query string (English, single line, simplified keywords preferred)",
                },
                "assumption": {
                    "type": "string",
                    "description": "Assumption value from a previous response to steer interpretation",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters in the response (default 6800)",
                },
                "units": {
                    "type": "string",
                    "description": "'metric' or 'imperial'",
                },
            },
            "required": ["input"],
        },
    },
}

_BASE_URL = "https://www.wolframalpha.com/api/v1/llm-api"


def execute(args: dict) -> dict:
    app_id = os.environ.get("WOLFRAM_APP_ID", "")
    if not app_id:
        return {"error": "WOLFRAM_APP_ID environment variable is not set"}

    query = args.get("input", "").strip()
    if not query:
        return {"error": "input is required"}

    params: dict = {
        "input": query,
        "appid": app_id,
    }
    if "max_chars" in args:
        params["maxchars"] = int(args["max_chars"])
    if "assumption" in args:
        params["assumption"] = args["assumption"]
    if "units" in args:
        params["units"] = args["units"]

    try:
        resp = requests.get(_BASE_URL, params=params, timeout=20)
        if resp.status_code == 200:
            return {"result": resp.text, "query": query}
        if resp.status_code == 501:
            body = resp.text.strip()
            out: dict = {"error": "query not understood", "query": query}
            if body:
                out["suggestion"] = body
            return out
        return {"error": f"HTTP {resp.status_code}", "query": query, "detail": resp.text[:500]}
    except requests.exceptions.Timeout:
        return {"error": "request timed out after 20s", "query": query}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"connection error: {e}", "query": query}
    except Exception as e:
        return {"error": str(e), "query": query}
