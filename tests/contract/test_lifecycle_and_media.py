"""US3: lifecycle writes and the media path the SDK does not generate."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp.client import Client
from fastmcp.client.elicitation import ElicitResult
from google.api_core import exceptions as gexc
from mcp.shared.exceptions import MCPError

from cloud_support_mcp.settings import Settings

CASE = "projects/p/cases/1"


async def _approve(message, response_type, params, ctx):
    return ElicitResult(action="accept", content=response_type(approve=True))


def _server(fake_clients, **kw):
    from cloud_support_mcp.server import build_server

    return build_server(Settings(parents=["projects/p"], **kw), clients=fake_clients)


class TestUpdateCase:
    async def test_preview_shows_before_and_after(self, fake_clients):
        seen: list[str] = []

        async def capture(message, response_type, params, ctx):
            seen.append(message)
            return ElicitResult(action="accept", content=response_type(approve=True))

        async with Client(_server(fake_clients), elicitation_handler=capture) as client:
            await client.call_tool("update_case", {"case_name": CASE, "priority": "P0"})

        assert "P2" in seen[0] and "P0" in seen[0], "변경 전/후가 나란히 보여야 한다"

    async def test_update_mask_covers_only_supplied_fields(self, fake_clients):
        async with Client(_server(fake_clients), elicitation_handler=_approve) as client:
            await client.call_tool("update_case", {"case_name": CASE, "priority": "P0"})

        _, request = next(c for c in fake_clients.cases.calls if c[0] == "update_case")
        assert set(request.update_mask.paths) == {"priority"}

    async def test_nothing_to_change_is_rejected(self, fake_clients):
        async with Client(_server(fake_clients)) as client:
            with pytest.raises(MCPError, match=r"[Nn]o field"):
                await client.call_tool("update_case", {"case_name": CASE})
        assert not [c for c in fake_clients.cases.calls if c[0] == "update_case"]


class TestCloseCase:
    async def test_preview_says_it_cannot_be_undone(self, fake_clients):
        seen: list[str] = []

        async def capture(message, response_type, params, ctx):
            seen.append(message)
            return ElicitResult(action="accept", content=response_type(approve=True))

        async with Client(_server(fake_clients), elicitation_handler=capture) as client:
            await client.call_tool("close_case", {"case_name": CASE})
        assert "cannot be reopened" in seen[0].lower() or "undone" in seen[0].lower()

    async def test_marked_destructive(self, fake_clients):
        async with Client(_server(fake_clients)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        assert tools["close_case"].annotations.destructive_hint is True

    async def test_already_closed_surfaces_failed_precondition(self, fake_clients):
        fake_clients.cases.search_error = None

        async def boom(request=None, **kw):
            fake_clients.cases.calls.append(("close_case", request))
            raise gexc.FailedPrecondition("case already closed")

        fake_clients.cases.close_case = boom
        async with Client(_server(fake_clients), elicitation_handler=_approve) as client:
            with pytest.raises(MCPError, match="failed_precondition"):
                await client.call_tool("close_case", {"case_name": CASE})


class TestEscalateCase:
    async def test_absent_by_default(self, fake_clients):
        async with Client(_server(fake_clients)) as client:
            names = {t.name for t in await client.list_tools()}
        assert "escalate_case" not in names, "에스컬레이션은 기본 비활성이어야 한다 (FR-018)"

    async def test_present_and_destructive_when_enabled(self, fake_clients):
        async with Client(_server(fake_clients, enable_escalation=True)) as client:
            tools = {t.name: t for t in await client.list_tools()}
        assert tools["escalate_case"].annotations.destructive_hint is True

    async def test_preview_names_the_real_consequence(self, fake_clients):
        seen: list[str] = []

        async def capture(message, response_type, params, ctx):
            seen.append(message)
            return ElicitResult(action="decline", content=None)

        server = _server(fake_clients, enable_escalation=True)
        async with Client(server, elicitation_handler=capture) as client:
            with pytest.raises(MCPError):
                await client.call_tool(
                    "escalate_case",
                    {
                        "case_name": CASE,
                        "reason": "RESOLUTION_TIME",
                        "justification": "No response for 48 hours.",
                    },
                )
        assert "support organi" in seen[0].lower() or "support team" in seen[0].lower()
        assert not [c for c in fake_clients.cases.calls if c[0] == "escalate_case"]


class TestAttachmentMedia:
    async def test_download_returns_a_path_not_bytes(self, fake_clients, tmp_path, respx_mock):
        respx_mock.get(
            "https://cloudsupport.googleapis.com/v2/projects/p/cases/1/attachments/1:download"
        ).respond(200, content=b"log line one\n", headers={"content-type": "text/plain"})

        server = _server(fake_clients, download_dir=tmp_path)
        async with Client(server) as client:
            result = await client.call_tool(
                "download_attachment",
                {"attachment_name": "projects/p/cases/1/attachments/1"},
            )

        data = result.structured_content
        assert "content" not in data and "body" not in data
        written = Path(data["local_path"])
        assert written.exists() and written.read_bytes() == b"log line one\n"

    async def test_download_does_not_overwrite_an_existing_file(
        self, fake_clients, tmp_path, respx_mock
    ):
        (tmp_path / "diag.log").write_bytes(b"pre-existing")
        respx_mock.get(
            "https://cloudsupport.googleapis.com/v2/projects/p/cases/1/attachments/1:download"
        ).respond(200, content=b"new content")

        server = _server(fake_clients, download_dir=tmp_path)
        async with Client(server) as client:
            result = await client.call_tool(
                "download_attachment",
                {"attachment_name": "projects/p/cases/1/attachments/1"},
            )
        assert Path(result.structured_content["local_path"]).name != "diag.log"
        assert (tmp_path / "diag.log").read_bytes() == b"pre-existing"

    async def test_upload_is_size_checked_before_asking(self, fake_clients, tmp_path):
        big = tmp_path / "huge.bin"
        big.write_bytes(b"x" * 2048)
        server = _server(fake_clients, max_upload_bytes=1024)
        async with Client(server) as client:
            with pytest.raises(MCPError, match=r"too large|exceeds"):
                await client.call_tool(
                    "upload_attachment", {"case_name": CASE, "file_path": str(big)}
                )

    async def test_upload_preview_omits_file_contents(self, fake_clients, tmp_path, respx_mock):
        secret = tmp_path / "diag.log"
        secret.write_text("CUSTOMER SECRET PAYLOAD")
        seen: list[str] = []

        async def capture(message, response_type, params, ctx):
            seen.append(message)
            return ElicitResult(action="decline", content=None)

        server = _server(fake_clients, download_dir=tmp_path)
        async with Client(server, elicitation_handler=capture) as client:
            with pytest.raises(MCPError):
                await client.call_tool(
                    "upload_attachment", {"case_name": CASE, "file_path": str(secret)}
                )
        assert "diag.log" in seen[0]
        assert "CUSTOMER SECRET PAYLOAD" not in seen[0], "미리보기에 파일 내용이 들어가면 안 된다"
