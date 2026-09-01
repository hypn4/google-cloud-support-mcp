"""US1 against the real API. Read-only — nothing here can create a case."""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from cloud_support_mcp.server import build_server
from cloud_support_mcp.settings import Settings

from .conftest import requires_api

pytestmark = [pytest.mark.integration, requires_api]


@pytest.fixture
def server(it_parent):
    return build_server(Settings(parents=[it_parent]))


async def test_search_then_detail_then_comments(server, it_parent):
    async with Client(server) as client:
        listing = (await client.call_tool("search_cases", {"page_size": 5})).structured_content
        assert listing["scopes_queried"] == [it_parent]
        if not listing["items"]:
            pytest.skip("no support cases under this parent to inspect")

        name = listing["items"][0]["ref"]["name"]
        detail = (await client.call_tool("get_case", {"case_name": name})).structured_content
        assert detail["ref"]["console_url"]

        comments = (await client.call_tool("list_comments", {"case_name": name})).structured_content
        for item in comments["items"]:
            assert item["author_side"] in ("customer", "google_support")

        attachments = (
            await client.call_tool("list_attachments", {"case_name": name})
        ).structured_content
        for item in attachments["items"]:
            assert "body" not in item
