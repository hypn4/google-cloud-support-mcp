"""US1 read tools: names, schemas, annotations, and fan-out behaviour."""

import pytest
from fastmcp.client import Client
from google.api_core import exceptions as gexc

from google_cloud_support_mcp.fanout import decode_cursor
from google_cloud_support_mcp.settings import Settings

READ_TOOLS = {
    "search_cases",
    "get_case",
    "list_comments",
    "get_comment",
    "list_attachments",
    "get_attachment",
}


async def _tools(server):
    async with Client(server) as client:
        return {t.name: t for t in await client.list_tools()}


async def test_all_six_read_tools_registered(mcp_server):
    assert set(await _tools(mcp_server)) >= READ_TOOLS


async def test_read_tools_are_marked_read_only(mcp_server):
    tools = await _tools(mcp_server)
    for name in READ_TOOLS:
        ann = tools[name].annotations
        assert ann is not None and ann.read_only_hint is True, f"{name} 에 readOnlyHint 없음"


async def test_get_tools_are_idempotent(mcp_server):
    tools = await _tools(mcp_server)
    for name in ("get_case", "get_comment", "get_attachment"):
        assert tools[name].annotations.idempotent_hint is True


async def test_search_cases_returns_envelope(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("search_cases", {})
    data = result.structured_content
    assert data["scopes_queried"] == ["projects/p"]
    assert data["scopes_failed"] == []
    assert len(data["items"]) == 1
    assert data["items"][0]["ref"]["console_url"].startswith("https://console.cloud.google.com")


async def test_get_case_returns_detail_with_console_url(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_case", {"case_name": "projects/p/cases/1"})
    assert result.structured_content["description"]
    assert result.structured_content["ref"]["console_url"] is not None


async def test_comments_expose_author_side(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_comments", {"case_name": "projects/p/cases/1"})
    assert result.structured_content["items"][0]["author_side"] == "google_support"


async def test_attachments_carry_no_bytes(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_attachments", {"case_name": "projects/p/cases/1"})
    item = result.structured_content["items"][0]
    assert item["size_bytes"] == 12
    assert "body" not in item and "content" not in item


class TestFanoutPartialFailure:
    """R-004b: one denied scope must not hide the scopes that worked."""

    async def test_one_denied_parent_still_returns_others(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        fake_clients.cases.errors_by_parent = {
            "organizations/9": gexc.PermissionDenied("Permission denied on resource.")
        }
        server = build_server(
            Settings(parents=["projects/p", "organizations/9", "projects/q"]),
            clients=fake_clients,
        )
        async with Client(server) as client:
            result = await client.call_tool("search_cases", {})

        data = result.structured_content
        assert len(data["items"]) == 2, "실패한 parent 하나가 나머지를 죽였다"
        assert [f["parent"] for f in data["scopes_failed"]] == ["organizations/9"]
        assert data["scopes_failed"][0]["reason"] == "permission_denied"
        assert data["scopes_failed"][0]["retryable"] is False
        assert set(data["scopes_queried"]) == {"projects/p", "organizations/9", "projects/q"}

    async def test_support_plan_403_is_classified_separately(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        fake_clients.cases.errors_by_parent = {
            "projects/q": gexc.PermissionDenied("The caller has no Google Cloud support plan.")
        }
        server = build_server(Settings(parents=["projects/p", "projects/q"]), clients=fake_clients)
        async with Client(server) as client:
            result = await client.call_tool("search_cases", {})
        assert result.structured_content["scopes_failed"][0]["reason"] == "support_plan_required"


class TestPagination:
    async def test_cursor_is_issued_when_more_remains(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        class Paged(type(fake_clients.cases)):
            pass

        fake_clients.cases.next_token = "tok"
        original = fake_clients.cases.search_cases

        async def paged(request=None, **kw):
            page = await original(request=request, **kw)
            page.next_page_token = "tok"
            return page

        fake_clients.cases.search_cases = paged
        server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
        async with Client(server) as client:
            result = await client.call_tool("search_cases", {"page_size": 1})

        assert result.structured_content["truncated"] is True
        assert decode_cursor(result.structured_content["next_cursor"], {"projects/p"}) == {
            "projects/p": "tok"
        }

    async def test_cursor_from_a_different_parent_set_is_rejected(self, fake_clients):
        from google_cloud_support_mcp.fanout import encode_cursor
        from google_cloud_support_mcp.server import build_server

        stale = encode_cursor({"projects/other": "tok"})
        server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
        async with Client(server) as client:
            with pytest.raises(Exception) as exc:
                await client.call_tool("search_cases", {"cursor": stale})
        assert "cursor" in str(exc.value).lower()
