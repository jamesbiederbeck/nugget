"""
MCP server — exposes nugget's own (native) tools to external MCP clients
when running nugget-server, gated by the active profile's approval policy.

Scope for this pass (see planning/backlog.md NUG-023 for the deferred
follow-up): there is no interactive approval-prompt channel for MCP calls.
Instead, only tools whose approval *statically* resolves to "allow" are ever
listed or served:

  - Tools with a dynamic (callable) APPROVAL gate are excluded outright —
    a callable gate's result depends on args we don't have yet, so "allow"
    can't be proven for every possible call.
  - Tools that resolve to "ask" or "deny" (via config rules, the tool's own
    gate, or the config default) for empty args are excluded too.

Approval is re-resolved (never re-prompted — this path never touches stdin)
at call time as a backstop: if the actual call args resolve to anything
other than "allow", the call is refused with a plain error, never blocked
waiting on a human.

Tools loaded via nugget's own MCP *client* (src/nugget/mcp_client.py) are
never exposed here — this module only ever reads from `nugget.tools`.
"""

import contextlib
from typing import AsyncIterator

from . import tools as tool_registry
from . import approval as approval_mod
from .config import Config


def exposable_schemas(cfg: Config) -> list[dict]:
    """Native tool schemas whose approval resolves to a plain "allow"."""
    schemas = tool_registry.schemas(
        include=cfg.get("include_tools"), exclude=cfg.get("exclude_tools")
    )
    approval_cfg = cfg.approval_config()
    out = []
    for schema in schemas:
        name = schema["function"]["name"]
        gate = tool_registry.gate(name)
        if callable(gate):
            continue
        action = approval_mod._resolve_action(name, {}, gate, approval_cfg)
        if action == "allow":
            out.append(schema)
    return out


def build_server(cfg: Config):
    from mcp.server.lowlevel import Server
    import mcp.types as types

    server = Server("nugget")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=schema["function"]["name"],
                description=schema["function"].get("description", ""),
                inputSchema=schema["function"].get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            )
            for schema in exposable_schemas(cfg)
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> dict:
        exposed = {s["function"]["name"] for s in exposable_schemas(cfg)}
        if name not in exposed:
            raise ValueError(f"tool '{name}' is not exposed")
        # Re-resolve (never prompt) against the real call args as a backstop.
        action = approval_mod._resolve_action(
            name, arguments, tool_registry.gate(name), cfg.approval_config()
        )
        if action != "allow":
            raise ValueError(f"tool '{name}' blocked by approval policy")
        result = tool_registry.execute(name, arguments)
        return result if isinstance(result, dict) else {"result": result}

    return server


class _ASGIEndpoint:
    """Wraps a raw (scope, receive, send) callable so Starlette's `Route`
    treats it as an ASGI app rather than a `func(request) -> response`
    endpoint — `Route.__init__` only makes that distinction for endpoints
    that aren't a plain function/method, hence the tiny class wrapper."""

    def __init__(self, session_manager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def build_asgi_app(cfg: Config):
    """Returns (asgi_endpoint, lifespan_cm). `asgi_endpoint` must be mounted
    as an exact-path `starlette.routing.Route` (not `Mount` — Mount's path
    regex requires a trailing path segment, so it never matches the bare
    endpoint path itself). `lifespan_cm` is an async context manager that
    must be held open for the app's lifetime — wire it into the parent
    FastAPI app's lifespan."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    server = build_server(cfg)
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)
    asgi_endpoint = _ASGIEndpoint(session_manager)

    @contextlib.asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        """Matches Starlette's Router.lifespan_context signature: Callable[[Any],
        AsyncContextManager] — assign directly to `app.router.lifespan_context`."""
        async with session_manager.run():
            yield

    return asgi_endpoint, lifespan
