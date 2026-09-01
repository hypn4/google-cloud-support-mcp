"""FR-023: every case reference carries a console link, or fails gracefully."""

from __future__ import annotations

from fastmcp.client import Client

from google_cloud_support_mcp.serializers import parse_resource_ref

from ..conftest import make_case


async def test_summaries_and_details_carry_a_link(fake_clients, mcp_server):
    async with Client(mcp_server) as client:
        listing = (await client.call_tool("search_cases", {})).structured_content
        detail = (
            await client.call_tool("get_case", {"case_name": "projects/p/cases/1"})
        ).structured_content
    assert listing["items"][0]["ref"]["console_url"].startswith("https://console.cloud.google.com")
    assert detail["ref"]["console_url"].startswith("https://console.cloud.google.com")


async def test_an_unparseable_name_does_not_fail_the_call(fake_clients):
    """A link we cannot build must not take the lookup down with it."""
    from google_cloud_support_mcp.server import build_server
    from google_cloud_support_mcp.settings import Settings

    fake_clients.cases.cases = [make_case(name="totally/unexpected/shape")]
    server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
    async with Client(server) as client:
        listing = (await client.call_tool("search_cases", {})).structured_content

    ref = listing["items"][0]["ref"]
    assert ref["console_url"] is None
    assert ref["name"] == "totally/unexpected/shape"


def test_organization_links_use_organization_id():
    ref = parse_resource_ref("organizations/123/cases/9")
    assert "organizationId=123" in ref.console_url
