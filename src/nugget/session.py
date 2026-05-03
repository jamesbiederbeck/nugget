import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Session:
    def __init__(self, session_id: str, sessions_dir: Path):
        self.id = session_id
        self.path = sessions_dir / f"{session_id}.json"
        self.messages: list[dict[str, Any]] = []
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at

    @classmethod
    def new(cls, sessions_dir: Path) -> "Session":
        return cls(str(uuid.uuid4())[:8], sessions_dir)

    @classmethod
    def load(cls, session_id: str, sessions_dir: Path) -> "Session":
        s = cls(session_id, sessions_dir)
        if s.path.exists():
            with open(s.path) as f:
                data = json.load(f)
            s.messages = data.get("messages", [])
            s.created_at = data.get("created_at", s.created_at)
            s.updated_at = data.get("updated_at", s.updated_at)
        return s

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(
        self,
        content: str,
        thinking: str | None = None,
        tool_calls: list[dict] | None = None,
    ) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if thinking:
            msg["thinking"] = thinking
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(
                {
                    "id": self.id,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                    "messages": self.messages,
                },
                f,
                indent=2,
            )

    @staticmethod
    def load_subagents(parent_id: str, sessions_dir: Path) -> list[dict]:
        """Return all persisted subagent call transcripts for a parent session."""
        subdir = sessions_dir / parent_id / "subagents"
        if not subdir.exists():
            return []
        results = []
        for p in sorted(subdir.glob("*.json")):
            try:
                results.append(json.loads(p.read_text()))
            except Exception:
                pass
        return results

    @staticmethod
    def list_sessions(sessions_dir: Path) -> list[dict]:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for p in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(p) as f:
                    data = json.load(f)
                n_turns = sum(1 for m in data.get("messages", []) if m["role"] == "user")
                first = next(
                    (m["content"][:60] for m in data.get("messages", []) if m["role"] == "user"),
                    "(empty)",
                )
                results.append(
                    {
                        "id": data.get("id", p.stem),
                        "updated_at": data.get("updated_at", ""),
                        "turns": n_turns,
                        "preview": first,
                    }
                )
            except Exception:
                pass
        return results
