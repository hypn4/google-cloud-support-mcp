"""US3 against the real API. Escalation is never called — see the write policy.

Escalation reaches Google's support organisation regardless of whether the case
is flagged as a test, so it is verified by contract test only.
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
def server(it_parent, tmp_path):
    return build_server(Settings(parents=[it_parent], download_dir=tmp_path))


async def test_update_attach_download_then_close(server, it_parent, tmp_path):
    async with Client(server, elicitation_handler=_approve) as client:
        classes = (
            await client.call_tool("search_case_classifications", {"query": "Compute Engine"})
        ).structured_content
        if not classes["items"]:
            pytest.skip("no classifications returned for the probe query")

        created = (
            await client.call_tool(
                "create_case",
                {
                    "parent": it_parent,
                    "classification_id": classes["items"][0]["id"],
                    "title": "[automated test] lifecycle, please ignore",
                    "description": "Created by the cloud-support-mcp integration suite.",
                    "priority": "P4",
                    "test_case": True,
                },
            )
        ).structured_content
        assert created["test_case"] is True
        name = created["ref"]["name"]

        try:
            updated = (
                await client.call_tool("update_case", {"case_name": name, "priority": "P3"})
            ).structured_content
            assert updated["priority"] == "P3"

            source = tmp_path / "diag.log"
            source.write_text("integration test attachment\n")
            await client.call_tool(
                "upload_attachment", {"case_name": name, "file_path": str(source)}
            )

            listed = (
                await client.call_tool("list_attachments", {"case_name": name})
            ).structured_content
            assert listed["items"], "업로드한 첨부가 목록에 없다"

            got = (
                await client.call_tool(
                    "download_attachment",
                    {"attachment_name": listed["items"][0]["name"]},
                )
            ).structured_content
            assert "content" not in got
            assert got["size_bytes"] > 0
        finally:
            await client.call_tool("close_case", {"case_name": name})
