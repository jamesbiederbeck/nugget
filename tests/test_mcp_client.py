"""
Tests for the MCP client (src/nugget/mcp_client.py) — dynamic loading of
tools from external MCP servers. Uses a trivial stdio MCP server spawned as
a real subprocess (this file, invoked with `--serve-stub`) so the tests
exercise the real connect/list_tools/call_tool round trip, not mocks.
"""

import sys

import pytest

pytest.importorskip("mcp")

from nugget.config import Config
from nugget import mcp_client
from nugget import tools as tool_registry


def _run_stub_server() -> None:
    import asyncio
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    server = Server("stub")

    @server.list_tools()
    async def _list() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="echoes text back",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ]

    @server.call_tool()
    async def _call(name: str, args: dict):
        if name != "echo":
            raise ValueError(f"unknown tool {name}")
        return {"echoed": args["text"]}

    async def main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(main())


if __name__ == "__main__" and "--serve-stub" in sys.argv:
    _run_stub_server()
    sys.exit(0)


@pytest.fixture
def stub_cfg():
    cfg = Config()
    cfg._data["mcp_servers"] = {
        "stub": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [__file__, "--serve-stub"],
        }
    }
    yield cfg
    mcp_client._manager._teardown_locked()
    mcp_client._manager._config_key = None


def test_schemas_namespaced_and_loaded(stub_cfg):
    schemas = mcp_client.schemas(stub_cfg)
    names = [s["function"]["name"] for s in schemas]
    assert names == ["mcp__stub__echo"]


def test_owns_and_gate(stub_cfg):
    mcp_client.schemas(stub_cfg)
    assert mcp_client.owns("mcp__stub__echo")
    assert not mcp_client.owns("calculator")
    assert mcp_client.gate("mcp__stub__echo") == "ask"  # default gate


def test_gate_overridable_per_server(stub_cfg):
    stub_cfg._data["mcp_servers"]["stub"]["approval_default"] = "allow"
    mcp_client.schemas(stub_cfg)
    assert mcp_client.gate("mcp__stub__echo") == "allow"


def test_execute_round_trip(stub_cfg):
    mcp_client.schemas(stub_cfg)
    result = mcp_client.execute("mcp__stub__echo", {"text": "hello"})
    assert result == {"echoed": "hello"}


def test_native_registry_untouched(stub_cfg):
    before = set(tool_registry.list_names())
    mcp_client.schemas(stub_cfg)
    after = set(tool_registry.list_names())
    assert before == after
    assert "mcp__stub__echo" not in after


def test_include_tools_filters_server(stub_cfg):
    stub_cfg._data["mcp_servers"]["stub"]["include_tools"] = ["nonexistent"]
    schemas = mcp_client.schemas(stub_cfg)
    assert schemas == []


def test_no_servers_returns_empty():
    cfg = Config()
    assert mcp_client.schemas(cfg) == []
