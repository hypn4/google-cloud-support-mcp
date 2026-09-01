"""The confirmation gate is where FR-016 and FR-017 actually live.

What matters is not that a case gets created — it is that *nothing leaves* until
the user says so, and that what leaves is byte-identical to what they were shown.
Both are only observable by counting upstream calls, so these are mock tests.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client
from fastmcp.client.elicitation import ElicitResult
from mcp.shared.exceptions import MCPError

from google_cloud_support_mcp.settings import Settings

CREATE_ARGS = {
    "parent": "projects/p",
    "classification_id": "100H",
    "title": "Disk pressure on node pool",
    "description": "Nodes report DiskPressure since 02:00 UTC.",
    "priority": "P1",
    "test_case": True,
}


def _classified_server(fake_clients, **settings_kw):
    from google.cloud.support_v2.types import case

    from google_cloud_support_mcp.server import build_server

    fake_clients.cases.classifications = [
        case.CaseClassification(id="100H", display_name="Compute/GKE")
    ]
    return build_server(Settings(parents=["projects/p"], **settings_kw), clients=fake_clients)


def _upstream(fake_clients, name: str) -> int:
    return sum(1 for call, _ in fake_clients.cases.calls if call == name)


async def _handler(decision: bool):
    async def handler(message, response_type, params, ctx):
        return ElicitResult(action="accept", content=response_type(approve=decision))

    return handler


class TestReadToolsNeverAsk:
    """FR-010: `list_scopes` changes nothing, so it must not spend a confirmation.

    `readOnlyHint` is swept elsewhere, but the annotation is advisory — it is a
    label, not a guarantee. This asserts the behaviour: a client that offers no
    way to prompt still gets an answer, which is only true if nothing asked.
    """

    async def test_list_scopes_answers_without_prompting(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        asked: list[str] = []

        async def refuse(message, response_type, params, ctx):
            asked.append(message)
            raise AssertionError("읽기 도구가 확인을 요구했다")

        server = build_server(Settings(parents=[]), clients=fake_clients)
        async with Client(server, elicitation_handler=refuse) as client:
            result = await client.call_tool("list_scopes", {})

        assert asked == []
        assert result.structured_content["items"]


class TestCreateCaseConfirmation:
    async def test_round_one_shows_the_payload_before_sending_anything(self, fake_clients):
        """FR-016: the user sees the exact submission before it exists anywhere."""
        seen: list[str] = []

        async def capture(message, response_type, params, ctx):
            seen.append(message)
            return ElicitResult(action="decline", content=None)

        server = _classified_server(fake_clients)
        async with Client(server, elicitation_handler=capture) as client:
            with pytest.raises(MCPError):
                await client.call_tool("create_case", CREATE_ARGS)

        assert _upstream(fake_clients, "create_case") == 0
        preview = seen[0]
        assert CREATE_ARGS["title"] in preview
        assert CREATE_ARGS["description"] in preview
        assert "100H" in preview
        assert "TEST CASE" in preview, "테스트 케이스 여부가 미리보기에 드러나야 한다"

    async def test_declining_sends_nothing(self, fake_clients):
        """FR-017: cancelling leaves no trace upstream."""
        server = _classified_server(fake_clients)
        async with Client(server, elicitation_handler=await _handler(False)) as client:
            with pytest.raises(MCPError, match="Cancelled"):
                await client.call_tool("create_case", CREATE_ARGS)
        assert _upstream(fake_clients, "create_case") == 0

    async def test_accepting_sends_exactly_what_was_previewed(self, fake_clients):
        """FR-016: round two replays the sealed payload rather than rebuilding it."""
        server = _classified_server(fake_clients)
        async with Client(server, elicitation_handler=await _handler(True)) as client:
            await client.call_tool("create_case", CREATE_ARGS)

        assert _upstream(fake_clients, "create_case") == 1
        _, request = next(c for c in fake_clients.cases.calls if c[0] == "create_case")
        assert request.parent == CREATE_ARGS["parent"]
        assert request.case.display_name == CREATE_ARGS["title"]
        assert request.case.description == CREATE_ARGS["description"]
        assert request.case.classification.id == CREATE_ARGS["classification_id"]
        assert request.case.test_case is True


class TestClassificationValidation:
    async def test_invalid_classification_is_rejected_without_asking(self, fake_clients):
        """FR-009: never ask a user to confirm an action that cannot run."""
        server = _classified_server(fake_clients)
        args = {**CREATE_ARGS, "classification_id": "NOT-A-REAL-ID"}
        async with Client(server) as client:
            with pytest.raises(MCPError) as exc:
                await client.call_tool("create_case", args)

        assert _upstream(fake_clients, "create_case") == 0
        assert "Nothing was created" in str(exc.value)
        assert "search_case_classifications" in str(exc.value), "다음 조치를 안내해야 한다"


class TestAddCommentConfirmation:
    async def test_body_is_sent_verbatim_after_approval(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        body = "Attaching the node describe output; DiskPressure since 02:00 UTC."
        server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
        async with Client(server, elicitation_handler=await _handler(True)) as client:
            await client.call_tool("add_comment", {"case_name": "projects/p/cases/1", "body": body})

        calls = [c for c in fake_clients.comments.calls if c[0] == "create_comment"]
        assert len(calls) == 1
        assert calls[0][1].comment.body == body

    async def test_declining_posts_nothing(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
        async with Client(server, elicitation_handler=await _handler(False)) as client:
            with pytest.raises(MCPError, match="Cancelled"):
                await client.call_tool(
                    "add_comment", {"case_name": "projects/p/cases/1", "body": "no"}
                )
        assert not [c for c in fake_clients.comments.calls if c[0] == "create_comment"]

    async def test_body_over_the_proto_limit_is_rejected_before_asking(self, fake_clients):
        from google_cloud_support_mcp.server import build_server

        server = build_server(Settings(parents=["projects/p"]), clients=fake_clients)
        async with Client(server) as client:
            with pytest.raises(MCPError, match="12,800"):
                await client.call_tool(
                    "add_comment", {"case_name": "projects/p/cases/1", "body": "x" * 12_801}
                )
        assert not [c for c in fake_clients.comments.calls if c[0] == "create_comment"]


class TestNoElicitationClient:
    async def test_write_refuses_when_the_client_cannot_prompt(self, fake_clients):
        """FR-019: change nothing, and say why it could not run.

        The tool still returns its InputRequiredResult; the client then reports it
        cannot fulfil it. What matters is that no case was created either way.
        """
        server = _classified_server(fake_clients)
        async with Client(server) as client:  # no elicitation_handler
            with pytest.raises(MCPError, match=r"[Ee]licitation"):
                await client.call_tool("create_case", CREATE_ARGS)

        assert _upstream(fake_clients, "create_case") == 0
