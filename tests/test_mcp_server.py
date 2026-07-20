import asyncio

import pytest

pytest.importorskip("mcp")

from nugget.config import Config
from nugget import mcp_server


def _cfg(**overrides) -> Config:
    cfg = Config()
    cfg._data.update(overrides)
    return cfg


def test_exposable_schemas_excludes_dynamic_gates():
    cfg = _cfg()
    names = {s["function"]["name"] for s in mcp_server.exposable_schemas(cfg)}
    # filebrowser/http_fetch/memory/tasks all have callable APPROVAL gates
    for dynamic_tool in ("filebrowser", "http_fetch", "memory", "tasks"):
        assert dynamic_tool not in names


def test_exposable_schemas_excludes_ask_gated_tools():
    cfg = _cfg()
    names = {s["function"]["name"] for s in mcp_server.exposable_schemas(cfg)}
    assert "shell" not in names       # APPROVAL = "ask"
    assert "spawn_agent" not in names  # APPROVAL = "ask"


def test_exposable_schemas_respects_config_deny_rule():
    cfg = _cfg(approval={"default": "allow", "rules": [{"tool": "calculator", "action": "deny"}]})
    names = {s["function"]["name"] for s in mcp_server.exposable_schemas(cfg)}
    assert "calculator" not in names


def test_exposable_schemas_includes_static_allow_tools():
    cfg = _cfg()
    names = {s["function"]["name"] for s in mcp_server.exposable_schemas(cfg)}
    assert "calculator" in names
    assert "get_datetime" in names


def test_call_tool_allows_exposed_tool():
    from mcp.shared.memory import create_connected_server_and_client_session

    cfg = _cfg()
    server = mcp_server.build_server(cfg)

    async def run():
        async with create_connected_server_and_client_session(server) as session:
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "shell" not in names
            assert "calculator" in names

            result = await session.call_tool("calculator", {"expression": "2 + 2"})
            assert not result.isError

    asyncio.run(run())


def test_call_tool_denies_unexposed_tool():
    from mcp.shared.memory import create_connected_server_and_client_session

    cfg = _cfg()
    server = mcp_server.build_server(cfg)

    async def run():
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("shell", {"command": "echo hi"})
            assert result.isError

    asyncio.run(run())


def test_call_tool_reresolves_approval_for_real_args():
    """A tool that's statically "allow" for {} but whose config rule targets
    specific args must still be blocked at call time for those args."""
    from mcp.shared.memory import create_connected_server_and_client_session

    cfg = _cfg(approval={
        "default": "allow",
        "rules": [{"tool": "calculator", "args": {"expression": "shutdown"}, "action": "deny"}],
    })
    server = mcp_server.build_server(cfg)

    async def run():
        async with create_connected_server_and_client_session(server) as session:
            tools = await session.list_tools()
            assert "calculator" in {t.name for t in tools.tools}

            ok = await session.call_tool("calculator", {"expression": "2 + 2"})
            assert not ok.isError

            blocked = await session.call_tool("calculator", {"expression": "shutdown"})
            assert blocked.isError

    asyncio.run(run())


def test_no_mcp_client_tools_leak_into_exposure(monkeypatch):
    """mcp_server must only ever read from the native tool registry — tools
    loaded via mcp_client (external MCP servers nugget consumes) must never
    appear in nugget's own exposed tool list."""
    from nugget import mcp_client

    monkeypatch.setattr(mcp_client, "schemas", lambda cfg: [
        {"type": "function", "function": {"name": "mcp__other__leaked", "parameters": {}}}
    ])
    cfg = _cfg()
    names = {s["function"]["name"] for s in mcp_server.exposable_schemas(cfg)}
    assert "mcp__other__leaked" not in names
