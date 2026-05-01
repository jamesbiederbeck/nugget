import os
import time
import json
import requests

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "wallabag",
        "description": "Manage a Wallabag reading list. Operations: 'list', 'search', 'post', 'get'.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "One of: 'list', 'search', 'post', 'get'"
                },
                "url": {
                    "type": "string",
                    "description": "The URL to save (required for 'post' unless content is provided)"
                },
                "title": {
                    "type": "string",
                    "description": "Article title (optional for 'post')"
                },
                "content": {
                    "type": "string",
                    "description": "Raw article HTML/text to save directly (optional for 'post'; use with a placeholder url if no real URL exists)"
                },
                "query": {
                    "type": "string",
                    "description": "Search term (required for 'search')"
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (used in 'post' and 'search')"
                },
                "id": {
                    "type": "integer",
                    "description": "Article ID (required for 'get')"
                },
                "per_page": {
                    "type": "integer",
                    "description": "Number of results to return for 'list' and 'search' (default 10)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of article content to return for 'get' (default 2000)"
                }
            },
            "required": ["operation"]
        }
    }
}

_TOKEN_CACHE_FILE = "/tmp/.wallabag_token"

def _get_token(base_url: str) -> str:
    client_id = os.getenv("WALLABAG_CLIENT_ID")
    client_secret = os.getenv("WALLABAG_CLIENT_SECRET")
    username = os.getenv("WALLABAG_USERNAME")
    password = os.getenv("WALLABAG_PASSWORD")

    if not all([client_id, client_secret, username, password]):
        raise RuntimeError("WALLABAG_CLIENT_ID, WALLABAG_CLIENT_SECRET, WALLABAG_USERNAME, and WALLABAG_PASSWORD must all be set")

    # Return cached token if still valid (with 60s buffer)
    try:
        cached = json.loads(open(_TOKEN_CACHE_FILE).read())
        if cached.get("expires_at", 0) > time.time() + 60:
            return cached["access_token"]
    except Exception:
        pass

    r = requests.post(f"{base_url}/oauth/v2/token", data={
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
    }, timeout=15)
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)

    try:
        with open(_TOKEN_CACHE_FILE, "w") as f:
            json.dump({"access_token": token, "expires_at": time.time() + expires_in}, f)
    except Exception:
        pass

    return token


def execute(args: dict) -> dict:
    operation = args.get("operation")
    if not operation:
        return {"error": "missing required argument: 'operation'"}

    base_url = os.getenv("WALLABAG_BASE_URL")
    if not base_url:
        return {"error": "WALLABAG_BASE_URL environment variable is not set"}
    base_url = base_url.rstrip("/")

    try:
        token = _get_token(base_url)
    except Exception as e:
        return {"error": f"failed to obtain token: {e}"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    try:
        if operation == "list":
            params = {"perPage": args.get("per_page", 10)}
            r = requests.get(f"{base_url}/api/entries.json", headers=headers, params=params, timeout=15)
            r.raise_for_status()
            items = r.json().get("_embedded", {}).get("items", [])
            return {
                "items": [{"id": i["id"], "title": i.get("title"), "url": i.get("url")} for i in items]
            }

        elif operation == "search":
            if "query" not in args:
                return {"error": "missing required argument: 'query' for search"}
            params = {"search": args["query"], "perPage": args.get("per_page", 10)}
            if "tags" in args:
                params["tags"] = args["tags"]
            r = requests.get(f"{base_url}/api/entries.json", headers=headers, params=params, timeout=15)
            r.raise_for_status()
            items = r.json().get("_embedded", {}).get("items", [])
            return {
                "items": [{"id": i["id"], "title": i.get("title"), "url": i.get("url")} for i in items]
            }

        elif operation == "post":
            if "url" not in args and "content" not in args:
                return {"error": "missing required argument: 'url' or 'content' for post"}
            payload = {"url": args.get("url", "https://nugget.local/article")}
            if "title" in args:
                payload["title"] = args["title"]
            if "content" in args:
                payload["content"] = args["content"]
            if "tags" in args:
                payload["tags"] = args["tags"]
            r = requests.post(f"{base_url}/api/entries.json", headers=headers, data=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            # Wallabag API returns the entry ID. The actual view URL is typically /articles/<id>
            return {
                "id": data.get("id"),
                "url": f"{base_url}/articles/{data.get('id')}",
                "source_url": args["url"],
                "status": "saved"
            }

        elif operation == "get":
            if "id" not in args:
                return {"error": "missing required argument: 'id' for get"}
            r = requests.get(f"{base_url}/api/entries/{args['id']}.json", headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            max_chars = args.get("max_chars", 2000)
            return {
                "id": data.get("id"),
                "title": data.get("title"),
                "url": data.get("url"),
                "content": data.get("content", "")[:max_chars]
            }

        else:
            return {"error": f"unknown operation: '{operation}'"}

    except requests.exceptions.Timeout:
        return {"error": "Wallabag API request timed out"}
    except Exception as e:
        return {"error": str(e)}
