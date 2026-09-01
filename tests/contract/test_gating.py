"""Tag gating mechanism (FR-018). Real tool inventory is asserted in Phase 6."""

import pytest
from fastmcp import FastMCP
from fastmcp.client import Client


async def _tool_names(server: FastMCP) -> set[str]:
    async with Client(server) as client:
        return {t.name for t in await client.list_tools()}


@pytest.fixture
def tagged_server() -> FastMCP:
    mcp = FastMCP(name="gating-probe")

    @mcp.tool(tags={"cases", "read"})
    def reader() -> str:
        return "r"

    @mcp.tool(tags={"cases", "write"})
    def writer() -> str:
        return "w"

    @mcp.tool(tags={"cases", "write", "escalation"})
    def escalator() -> str:
        return "e"

    return mcp


async def test_all_tools_visible_by_default(tagged_server):
    assert await _tool_names(tagged_server) == {"reader", "writer", "escalator"}


async def test_disable_by_tag_removes_from_list(tagged_server):
    tagged_server.disable(tags={"escalation"})
    assert await _tool_names(tagged_server) == {"reader", "writer"}


async def test_disabling_write_removes_every_write_tool(tagged_server):
    tagged_server.disable(tags={"write"})
    assert await _tool_names(tagged_server) == {"reader"}
