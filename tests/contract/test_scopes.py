"""US2/US3: enumerating the scopes a caller can reach.

The filter is the part worth guarding. An earlier design filtered projects with a
server-side prefix query and organizations locally, which made one argument mean
two things: `billing` found `Acme Billing` and missed `my-billing-project`, with
no error to notice. The tests here assert the symmetric behaviour that replaced
it, and they use mid-name fragments on purpose — a prefix implementation passes
every easy case.
"""

import pytest
from fastmcp.client import Client
from google.api_core import exceptions as gexc

from google_cloud_support_mcp.settings import Settings
from tests.conftest import make_org, make_project


def _server(fake_clients, **kw):
    from google_cloud_support_mcp.server import build_server

    return build_server(Settings(parents=[], **kw), clients=fake_clients)


async def _call(fake_clients, args=None, **kw):
    async with Client(_server(fake_clients, **kw)) as client:
        result = await client.call_tool("list_scopes", args or {})
    return result.structured_content


class TestEnumeration:
    async def test_both_classes_come_back_with_usable_identifiers(self, fake_clients):
        body = await _call(fake_clients)
        parents = {i["parent"] for i in body["items"]}
        assert "organizations/123456789" in parents
        assert "projects/my-billing-project" in parents
        assert body["scopes_queried"] == ["organizations", "projects"]
        assert body["next_cursor"] is None

    async def test_a_project_is_addressed_by_id_not_number(self, fake_clients):
        """The number addresses the right project and reads as noise in a list."""
        body = await _call(fake_clients)
        for item in body["items"]:
            if item["kind"] == "project":
                assert not item["parent"].removeprefix("projects/").isdigit(), item

    async def test_either_class_can_be_switched_off(self, fake_clients):
        only_orgs = await _call(fake_clients, {"include_projects": False})
        assert {i["kind"] for i in only_orgs["items"]} == {"organization"}
        assert only_orgs["scopes_queried"] == ["organizations"]

        only_projects = await _call(fake_clients, {"include_organizations": False})
        assert {i["kind"] for i in only_projects["items"]} == {"project"}

    async def test_an_account_with_no_organizations_is_normal(self, fake_clients):
        """An individual account sees no organizations. That is an answer, not an error.

        Nothing in the code treats an empty class as a failure today, and this
        exists so that stays true: "returned nothing" and "could not be read" are
        different states, and collapsing them would tell a personal-account user
        their permissions are broken.
        """
        fake_clients.organizations.items = []
        body = await _call(fake_clients)

        assert [i["kind"] for i in body["items"]] == ["project"] * len(body["items"])
        assert body["items"], "프로젝트는 나와야 한다"
        assert body["scopes_failed"] == [], "빈 목록이 실패로 보고됐다"
        assert body["scopes_queried"] == ["organizations", "projects"], (
            "조회한 클래스 목록은 결과가 비었다고 줄어들면 안 된다"
        )

    async def test_asking_for_nothing_returns_nothing_rather_than_failing(self, fake_clients):
        body = await _call(
            fake_clients, {"include_projects": False, "include_organizations": False}
        )
        assert body["items"] == []
        assert body["scopes_failed"] == []


class TestFilter:
    async def test_a_mid_name_fragment_matches_a_project(self, fake_clients):
        """`billing`, not `my-bill` — this is the case prefix matching fails."""
        body = await _call(fake_clients, {"name_contains": "billing"})
        assert [i["parent"] for i in body["items"]] == ["projects/my-billing-project"]

    async def test_the_same_fragment_rule_applies_to_organizations(self, fake_clients):
        """Symmetry is the requirement. One matcher, no branch on kind."""
        fake_clients.organizations.items = [make_org("1", "Contoso Billing Group")]
        body = await _call(fake_clients, {"name_contains": "billing"})
        kinds = {i["kind"] for i in body["items"]}
        assert kinds == {"project", "organization"}, body["items"]

    async def test_matching_is_case_insensitive(self, fake_clients):
        body = await _call(fake_clients, {"name_contains": "BILLING"})
        assert body["items"]

    async def test_the_identifier_is_searched_as_well_as_the_name(self, fake_clients):
        fake_clients.projects.items = [make_project("acct-9912", display_name="Ledger")]
        body = await _call(fake_clients, {"name_contains": "9912"})
        assert [i["parent"] for i in body["items"]] == ["projects/acct-9912"]

    async def test_no_match_is_an_empty_list_not_an_error(self, fake_clients):
        body = await _call(fake_clients, {"name_contains": "no-such-scope-anywhere"})
        assert body["items"] == []
        assert body["scopes_failed"] == []


class TestPagingAndTruncation:
    async def test_a_filtered_search_looks_past_the_first_page(self, fake_clients):
        """A match on page two must not come back as "not reachable"."""
        fake_clients.projects.items = [
            make_project("alpha"),
            make_project("bravo"),
            make_project("charlie"),
            make_project("target-billing"),
        ]
        fake_clients.projects.page_items = 2
        body = await _call(fake_clients, {"name_contains": "target"})
        assert [i["parent"] for i in body["items"]] == ["projects/target-billing"]
        assert body["truncated"] is False

    async def test_an_unfiltered_listing_stops_at_one_page_and_says_so(self, fake_clients):
        fake_clients.projects.items = [make_project(f"p{n}") for n in range(6)]
        fake_clients.projects.page_items = 2
        body = await _call(fake_clients)
        assert len([i for i in body["items"] if i["kind"] == "project"]) == 2
        assert body["truncated"] is True

    async def test_an_unfiltered_listing_is_conversation_sized(self, fake_clients):
        """The fetch size while searching must not decide how many rows a listing shows.

        One constant doing both jobs is how a listing ends up returning a hundred
        rows into a chat window — the exact thing DEFAULT_PAGE_SIZE exists to stop.
        """
        fake_clients.projects.items = [make_project(f"p{n}") for n in range(50)]
        fake_clients.projects.page_items = 50
        async with Client(_server(fake_clients, default_page_size=5)) as client:
            body = (await client.call_tool("list_scopes", {})).structured_content
        requested = [
            r.page_size for name, r in fake_clients.projects.calls if name == "search_projects"
        ]
        assert requested == [5], f"목록 조회가 설정된 페이지 크기를 쓰지 않았다: {requested}"
        assert len([i for i in body["items"] if i["kind"] == "project"]) <= 5

    async def test_a_filtered_search_asks_for_bigger_pages(self, fake_clients):
        """Searching wants fewer round trips; the same number would be wrong here."""
        from google_cloud_support_mcp.tools import scopes

        async with Client(_server(fake_clients, default_page_size=5)) as client:
            await client.call_tool("list_scopes", {"name_contains": "billing"})
        requested = [
            r.page_size for name, r in fake_clients.projects.calls if name == "search_projects"
        ]
        assert requested[0] == scopes._SCOPE_SEARCH_PAGE_SIZE, requested

    async def test_hitting_the_bound_is_reported(self, fake_clients, monkeypatch):
        """The bound is a safety limit, so tests shrink it rather than build 1000 rows."""
        from google_cloud_support_mcp.tools import scopes

        monkeypatch.setattr(scopes, "_SCOPE_SEARCH_LIMIT", 3)
        fake_clients.projects.items = [make_project(f"p{n}") for n in range(10)]
        fake_clients.projects.page_items = 2
        body = await _call(fake_clients, {"name_contains": "zzz-no-match"})
        assert body["truncated"] is True, "상한에 걸렸는데 불완전하다고 말하지 않았다"


class TestNeverSelectsForYou:
    async def test_every_match_is_returned(self, fake_clients):
        """FR-009a: narrowing several matches to one is the assistant's call."""
        fake_clients.projects.items = [
            make_project("billing-eu"),
            make_project("billing-us"),
        ]
        body = await _call(fake_clients, {"name_contains": "billing"})
        assert len([i for i in body["items"] if i["kind"] == "project"]) == 2


class TestGuidanceIsPartOfTheContract:
    """FR-009b: the description is the only lever the server has.

    Choosing between several matching scopes belongs to the assistant, so the
    server can only influence it by saying so where the assistant will read it.
    That makes the wording contract rather than prose — and contract that nothing
    tests is contract that disappears the next time someone tightens a docstring.
    """

    async def _description(self, fake_clients) -> str:
        async with Client(_server(fake_clients)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        return tools["list_scopes"].description or ""

    async def test_it_tells_the_assistant_to_ask_when_several_match(self, fake_clients):
        assert "ask the user which one" in (await self._description(fake_clients)).lower()

    async def test_it_tells_the_assistant_what_to_do_when_nothing_matches(self, fake_clients):
        assert "call again without the filter" in (await self._description(fake_clients)).lower()

    async def test_it_explains_when_truncated_actually_matters(self, fake_clients):
        """On a large account every filtered lookup is truncated.

        Unqualified, the caveat turns into a hedge on every answer including the
        ones that found exactly what was asked for.
        """
        description = (await self._description(fake_clients)).lower()
        assert "truncated" in description
        assert "do not hedge an answer you actually found" in description


class TestPartialVisibility:
    async def test_one_unreadable_class_does_not_fail_the_call(self, fake_clients):
        """The common real split: projects.get granted, organizations.get not."""
        fake_clients.organizations.error = gexc.PermissionDenied(
            "Permission 'resourcemanager.organizations.get' denied."
        )
        body = await _call(fake_clients)
        assert [i["kind"] for i in body["items"]] == ["project"] * len(body["items"])
        assert body["items"], "읽을 수 있었던 클래스가 비었다"
        failed = body["scopes_failed"]
        assert [f["parent"] for f in failed] == ["organizations"]
        assert failed[0]["reason"] == "permission_denied"
        assert body["scopes_queried"] == ["organizations", "projects"]

    async def test_both_unreadable_fails_the_call(self, fake_clients):
        denied = gexc.PermissionDenied("denied")
        fake_clients.organizations.error = denied
        fake_clients.projects.error = denied
        with pytest.raises(Exception) as exc:
            await _call(fake_clients)
        message = str(exc.value)
        assert "organizations" in message and "projects" in message, message

    async def test_a_disabled_api_is_not_reported_as_a_permission_problem(self, fake_clients):
        """Asking for a role you already have wastes the user's time."""
        fake_clients.organizations.error = gexc.PermissionDenied(
            "Cloud Resource Manager API has not been used in project my-project "
            "before or it is disabled."
        )
        body = await _call(fake_clients)
        assert body["scopes_failed"][0]["reason"] == "api_not_enabled"
