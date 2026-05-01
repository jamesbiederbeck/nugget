import requests


def APPROVAL(args: dict) -> str:
    return "allow" if args.get("method", "GET").upper() in ("GET", "HEAD") else "ask"


SCHEMA = {
    "type": "function",
    "function": {
        "name": "http_fetch",
        "description": (
            "Fetch a URL and return the response body as text or parsed JSON. "
            "GET/HEAD are auto-allowed; other methods require approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (default: GET)",
                },
                "headers": {
                    "type": "object",
                    "description": "Additional request headers as key-value pairs",
                },
                "body": {
                    "type": "string",
                    "description": "Request body string (for POST/PUT)",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Truncate text response to this many characters (default 8000)",
                },
                "as_json": {
                    "type": "boolean",
                    "description": "If true, parse response body as JSON and return under 'json' key",
                },
            },
            "required": ["url"],
        },
    },
}


def execute(args: dict) -> dict:
    url = args.get("url", "").strip()
    if not url:
        return {"error": "url is required"}

    method = args.get("method", "GET").upper()
    headers = args.get("headers") or {}
    body = args.get("body")
    max_chars = int(args.get("max_chars", 8000))
    as_json = bool(args.get("as_json", False))

    try:
        resp = requests.request(
            method,
            url,
            headers=headers,
            data=body,
            timeout=15,
            allow_redirects=True,
        )
        out: dict = {
            "status": resp.status_code,
            "url": str(resp.url),
        }
        if as_json:
            try:
                out["json"] = resp.json()
            except Exception:
                out["error"] = "response is not valid JSON"
                out["content"] = resp.text[:max_chars]
                out["truncated"] = len(resp.text) > max_chars
        else:
            text = resp.text
            out["content"] = text[:max_chars]
            out["truncated"] = len(text) > max_chars
        return out
    except requests.exceptions.Timeout:
        return {"error": "request timed out after 15s", "url": url}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"connection error: {e}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}
