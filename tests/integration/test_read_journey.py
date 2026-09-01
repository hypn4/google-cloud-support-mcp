"""US1 against the real API. Read-only — nothing here can create a case."""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from google_cloud_support_mcp.server import build_server
from google_cloud_support_mcp.settings import Settings

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


async def test_a_listed_scope_is_usable_verbatim(it_parent):
    """US2 round trip — the scenario that decides whether the feature works.

    `list_scopes` returning something plausible is not enough. A project *number*
    satisfies the parent regex, addresses a real project, and would pass every
    mock-based test in the suite while being the wrong thing to show a user. The
    only check that catches it is feeding the string straight back.
    """
    server = build_server(Settings(parents=[]))
    async with Client(server) as client:
        scopes = (await client.call_tool("list_scopes", {})).structured_content
        if not scopes["items"]:
            pytest.skip("these credentials can reach no scopes")

        for scope in scopes["items"]:
            assert scope["parent"].startswith(("projects/", "organizations/"))
            if scope["kind"] == "project":
                ident = scope["parent"].removeprefix("projects/")
                assert not ident.isdigit(), f"프로젝트 번호가 반환됐다: {scope['parent']}"

        parent = scopes["items"][0]["parent"]
        listing = (
            await client.call_tool("search_cases", {"parents": [parent], "page_size": 1})
        ).structured_content
        assert listing["scopes_queried"] == [parent]


async def test_filtering_is_the_same_for_both_classes(it_parent):
    """A prefix implementation passes with a leading fragment and fails here."""
    server = build_server(Settings(parents=[]))
    async with Client(server) as client:
        everything = (await client.call_tool("list_scopes", {})).structured_content
        if not everything["items"]:
            pytest.skip("these credentials can reach no scopes")

        target = everything["items"][0]
        name = target["display_name"] or target["parent"]
        if len(name) < 4:
            pytest.skip("no scope name long enough to take a mid-name fragment from")

        fragment = name[1:4]
        narrowed = (
            await client.call_tool("list_scopes", {"name_contains": fragment})
        ).structured_content
        assert any(i["parent"] == target["parent"] for i in narrowed["items"]), (
            f"중간 토막 '{fragment}' 로 {target['parent']} 를 찾지 못했다 — "
            "서버 측 접두 매칭이 되살아났을 가능성"
        )
