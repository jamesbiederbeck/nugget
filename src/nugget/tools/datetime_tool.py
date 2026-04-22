from datetime import datetime, timezone
import zoneinfo

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_datetime",
        "description": "Get the current date and time, optionally in a specific timezone",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone string, e.g. 'UTC', 'America/New_York', 'Europe/London'. Defaults to UTC.",
                }
            },
            "required": [],
        },
    },
}


def execute(args: dict) -> dict:
    tz_name = args.get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return {"error": f"unknown timezone: {tz_name!r}"}
    now = datetime.now(tz)
    return {
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": tz_name,
        "weekday": now.strftime("%A"),
    }
