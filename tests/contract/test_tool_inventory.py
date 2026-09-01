"""The published surface, asserted against contracts/tools.md.

Also asserts what is *absent*: event subscriptions went out of scope in
spec.md Clarifications 2026-09-01, and a regression there would be silent.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from cloud_support_mcp.clients import SupportClients
from cloud_support_mcp.server import build_server
from cloud_support_mcp.settings import Settings

READ = {
    "search_cases",
    "get_case",
    "search_case_classifications",
    "list_comments",
    "get_comment",
    "list_attachments",
    "get_attachment",
    "download_attachment",
}
WRITE = {
    "create_case",
    "update_case",
    "close_case",
    "escalate_case",
    "add_comment",
    "upload_attachment",
}
DESTRUCTIVE = {"close_case", "escalate_case"}


def _server(**kw):
    return build_server(
        Settings(parents=["projects/p"], **kw),
        clients=SupportClients(None, None, None, None, None),
    )


async def _names(server) -> set[str]:
    async with Client(server) as client:
        return {t.name for t in await client.list_tools()}


class TestInventory:
    async def test_fourteen_tools_when_everything_is_enabled(self):
        assert await _names(_server(enable_escalation=True)) == READ | WRITE

    async def test_annotations_match_the_contract(self):
        async with Client(_server(enable_escalation=True)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        for name in READ:
            assert tools[name].annotations.read_only_hint is True, name
        for name in WRITE:
            assert tools[name].annotations.read_only_hint is not True, name
        for name in DESTRUCTIVE:
            assert tools[name].annotations.destructive_hint is True, name
        for name in (READ | WRITE) - DESTRUCTIVE:
            assert tools[name].annotations.destructive_hint is not True, name

    async def test_no_subscription_tools_exist(self):
        """spec.md Clarifications 2026-09-01 put SupportEventSubscriptionService out of scope."""
        names = await _names(_server(enable_escalation=True, enable_writes=True))
        assert not [n for n in names if "subscription" in n], names

    async def test_resource_template_and_prompts(self):
        async with Client(_server()) as client:
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()
        assert [t.uri_template for t in templates] == ["case://{parent_type}/{parent_id}/{case_id}"]
        assert {p.name for p in prompts} == {"triage_open_cases", "draft_case_from_incident"}


class TestGatedExposure:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({}, 13),
            ({"enable_escalation": True}, 14),
            ({"enable_writes": False}, 8),
        ],
    )
    async def test_counts(self, kwargs, expected):
        assert len(await _names(_server(**kwargs))) == expected

    async def test_escalation_is_hidden_by_default(self):
        assert "escalate_case" not in await _names(_server())
