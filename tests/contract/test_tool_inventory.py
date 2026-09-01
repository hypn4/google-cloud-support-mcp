"""The published surface, asserted against contracts/tools.md.

Also asserts what is *absent*: event subscriptions went out of scope in
spec.md Clarifications 2026-09-01, and a regression there would be silent.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from google_cloud_support_mcp.clients import SupportClients
from google_cloud_support_mcp.server import build_server
from google_cloud_support_mcp.settings import Settings

READ = {
    "list_scopes",
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
        clients=SupportClients(None, None, None, None, None, None, None),
    )


async def _names(server) -> set[str]:
    async with Client(server) as client:
        return {t.name for t in await client.list_tools()}


class TestInventory:
    async def test_fifteen_tools_when_everything_is_enabled(self):
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
            ({}, 14),
            ({"enable_escalation": True}, 15),
            ({"enable_writes": False}, 9),
        ],
    )
    async def test_counts(self, kwargs, expected):
        assert len(await _names(_server(**kwargs))) == expected

    async def test_escalation_is_hidden_by_default(self):
        assert "escalate_case" not in await _names(_server())


async def test_server_reports_its_own_version_not_fastmcp_s():
    """serverInfo.version must identify this release, not the framework's."""
    from importlib.metadata import version

    from google_cloud_support_mcp.server import _package_version

    ours = _package_version()
    assert ours != version("fastmcp"), "FastMCP 버전이 우리 버전으로 보고되고 있다"
    assert ours[0].isdigit()


def test_distribution_name_still_resolves():
    """server.py 의 DISTRIBUTION_NAME 과 pyproject 의 project.name 이 붙어 있는지.

    둘이 어긋나면 예외가 아니라 UNKNOWN_VERSION 으로 조용히 떨어진다. 그 값도
    'FastMCP 버전과 다르고 숫자로 시작한다'를 만족하므로 위 테스트를 그냥 통과한다.
    이름을 바꿀 때 한쪽만 고치는 것이 정확히 그 경로다.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    from google_cloud_support_mcp.server import DISTRIBUTION_NAME, UNKNOWN_VERSION, _package_version

    try:
        distribution(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        raise AssertionError(
            f"설치 메타데이터에 '{DISTRIBUTION_NAME}' 가 없다. "
            "server.py 의 DISTRIBUTION_NAME 과 pyproject.toml 의 project.name 이 "
            "어긋났거나 패키지가 설치되지 않았다."
        ) from None

    assert _package_version() != UNKNOWN_VERSION, "설치되어 있는데도 폴백 버전이 반환됐다"
