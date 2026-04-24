"""
Gotify push notification tool.
Reads GOTIFY_TOKEN (required) and GOTIFY_URL (optional) from the environment.
"""

import os

import requests as _requests

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "notify",
        "description": (
            "Send a push notification via Gotify. "
            "Use to alert the user when a long task finishes or something needs their attention."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Notification title",
                },
                "message": {
                    "type": "string",
                    "description": "Notification body",
                },
                "priority": {
                    "type": "integer",
                    "description": "Gotify priority 1–10 (default 5; higher = more urgent)",
                },
            },
            "required": ["title", "message"],
        },
    },
}


def execute(args: dict) -> dict:
    token = os.environ.get("GOTIFY_TOKEN")
    if not token:
        return {"error": "GOTIFY_TOKEN environment variable is not set"}

    base_url = os.environ.get("GOTIFY_URL", "http://gotify").rstrip("/")
    title = args.get("title", "").strip()
    message = args.get("message", "").strip()
    priority = int(args.get("priority", 5))

    if not title:
        return {"error": "title is required"}
    if not message:
        return {"error": "message is required"}

    try:
        resp = _requests.post(
            f"{base_url}/message",
            params={"token": token},
            data={"title": title, "message": message, "priority": priority},
            timeout=10,
        )
        resp.raise_for_status()
        return {"sent": True, "status": resp.status_code}
    except _requests.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except _requests.RequestException as e:
        return {"error": str(e)}
