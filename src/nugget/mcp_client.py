"""
MCP client — dynamically loads tools from external MCP servers configured
under the "mcp_servers" config key, and exposes them through the same
schemas()/execute()/gate() shape as nugget's own tool registry so the CLI
and web server can merge them into a turn's active tool set.

Deliberately NOT wired into `nugget.tools` — tools loaded here are never
visible to `nugget.mcp_server` (nugget's own MCP-server exposure). Callers
that assemble a turn's tool set (src/nugget/__main__.py, src/nugget/server.py)
are responsible for appending `schemas(cfg)` to `tool_registry.schemas(...)`
and routing execute()/gate() through `owns(name)`.

Config shape:
  "mcp_servers": {
    "<server-name>": {
      "transport": "stdio" | "http",
      # stdio:
      "command": "npx", "args": ["-y", "some-mcp-server"], "env": {...},
      # http:
      "url": "http://localhost:9000/mcp",
      "include_tools": [...],     # optional, filters this server's tools
      "exclude_tools": [...],     # optional, cannot combine with include_tools
      "approval_default": "ask",  # optional, default gate for this server's tools
    }
  }

Tools are namespaced `mcp__<server>__<tool>` to avoid collisions and to read
consistently with the mcp__<connector>__<tool> naming already used elsewhere.
"""

import asyncio
import json
import threading
from contextlib import AsyncExitStack
from typing import Any

_NAME_SEP = "__"
_PREFIX = "mcp" + _NAME_SEP


class MCPClientError(RuntimeError):
    pass


class _MCPClientManager:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}       # server name -> ClientSession
        self._schemas: dict[str, dict] = {}        # qualified tool name -> SCHEMA
        self._owner: dict[str, str] = {}            # qualified tool name -> server name
        self._remote_name: dict[str, str] = {}      # qualified tool name -> remote tool name
        self._approval_default: dict[str, str] = {}  # server name -> default gate
        self._config_key: str | None = None
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="nugget-mcp-client", daemon=True)
        self._thread.start()
        ready.wait()

    def _run(self, coro, timeout: float = 60.0):
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def ensure_loaded(self, mcp_servers: dict) -> None:
        key = json.dumps(mcp_servers, sort_keys=True)
        with self._lock:
            if key == self._config_key:
                return
            self._teardown_locked()
            self._config_key = key
            if not mcp_servers:
                return
            self._ensure_thread()
            self._run(self._connect_all(mcp_servers), timeout=60.0)

    def _teardown_locked(self) -> None:
        if self._stack is not None and self._loop is not None:
            try:
                self._run(self._stack.aclose(), timeout=30.0)
            except Exception:
                pass
        self._stack = None
        self._sessions.clear()
        self._schemas.clear()
        self._owner.clear()
        self._remote_name.clear()
        self._approval_default.clear()

    async def _connect_all(self, mcp_servers: dict) -> None:
        import mcp.types as types
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        for server_name, server_cfg in mcp_servers.items():
            transport = server_cfg.get("transport", "stdio")
            if transport == "stdio":
                params = StdioServerParameters(
                    command=server_cfg["command"],
                    args=server_cfg.get("args", []),
                    env=server_cfg.get("env"),
                )
                read, write = await self._stack.enter_async_context(stdio_client(params))
            elif transport == "http":
                read, write, _ = await self._stack.enter_async_context(
                    streamablehttp_client(server_cfg["url"])
                )
            else:
                raise MCPClientError(f"unknown mcp transport {transport!r} for server {server_name!r}")

            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[server_name] = session
            self._approval_default[server_name] = server_cfg.get("approval_default", "ask")

            include = server_cfg.get("include_tools")
            exclude = server_cfg.get("exclude_tools")
            result = await session.list_tools()
            for tool in result.tools:
                if include is not None and tool.name not in include:
                    continue
                if exclude is not None and tool.name in exclude:
                    continue
                qualified = f"{_PREFIX}{server_name}{_NAME_SEP}{tool.name}"
                self._schemas[qualified] = {
                    "type": "function",
                    "function": {
                        "name": qualified,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
                self._owner[qualified] = server_name
                self._remote_name[qualified] = tool.name

    # ── query surface ────────────────────────────────────────────────────

    def schemas(self) -> list[dict]:
        return list(self._schemas.values())

    def owns(self, name: str) -> bool:
        return name in self._schemas

    def gate(self, name: str) -> str | None:
        server_name = self._owner.get(name)
        if server_name is None:
            return None
        return self._approval_default.get(server_name, "ask")

    def execute(self, name: str, args: dict) -> object:
        server_name = self._owner.get(name)
        if server_name is None:
            return {"error": f"unknown mcp tool: {name}"}
        session = self._sessions[server_name]
        remote_name = self._remote_name[name]
        try:
            result = self._run(session.call_tool(remote_name, args), timeout=120.0)
        except Exception as e:
            return {"error": str(e)}
        return _convert_result(result)


def _convert_result(result) -> object:
    if getattr(result, "isError", False):
        texts = [c.text for c in result.content if getattr(c, "text", None)]
        return {"error": "; ".join(texts) or "mcp tool call failed"}
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except (json.JSONDecodeError, TypeError):
            return {"result": texts[0]}
    return {"result": texts}


_manager = _MCPClientManager()


def schemas(cfg) -> list[dict]:
    mcp_servers = cfg.get("mcp_servers") or {}
    if not mcp_servers:
        return []
    _manager.ensure_loaded(mcp_servers)
    return _manager.schemas()


def owns(name: str) -> bool:
    return _manager.owns(name)


def gate(name: str) -> str | None:
    return _manager.gate(name)


def execute(name: str, args: dict) -> object:
    return _manager.execute(name, args)
