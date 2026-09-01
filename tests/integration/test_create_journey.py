"""US2 against the real API — creates a case, so it is gated twice.

Every case here carries test_case=True, which keeps it out of a support
engineer's queue. The guard in conftest refuses anything else.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client
from fastmcp.client.elicitation import ElicitResult

from cloud_support_mcp.server import build_server
from cloud_support_mcp.settings import Settings

from .conftest import requires_write_optin

pytestmark = [pytest.mark.integration, requires_write_optin]


async def _approve(message, response_type, params, ctx):
    return ElicitResult(action="accept", content=response_type(approve=True))


@pytest.fixture
def server(it_parent):
    return build_server(Settings(parents=[it_parent]))


async def test_classify_create_comment_then_close(server, it_parent):
    async with Client(server, elicitation_handler=_approve) as client:
        found = (
            await client.call_tool("search_case_classifications", {"query": "Compute Engine"})
        ).structured_content
        if not found["items"]:
            pytest.skip("no classifications returned for the probe query")

        created = (
            await client.call_tool(
                "create_case",
                {
                    "parent": it_parent,
                    "classification_id": found["items"][0]["id"],
                    "title": "[automated test] please ignore",
                    "description": "Created by the cloud-support-mcp integration suite.",
                    "priority": "P4",
                    # Without this the case becomes a real ticket routed to a human.
                    "test_case": True,
                },
            )
        ).structured_content
        assert created["test_case"] is True
        name = created["ref"]["name"]

        try:
            await client.call_tool(
                "add_comment", {"case_name": name, "body": "Integration test comment."}
            )
            comments = (
                await client.call_tool("list_comments", {"case_name": name})
            ).structured_content
            assert any(c["body"] == "Integration test comment." for c in comments["items"])
        finally:
            await client.call_tool("close_case", {"case_name": name})
