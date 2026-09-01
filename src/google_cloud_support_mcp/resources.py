"""A case as addressable read-only context (data belongs in resources, actions in tools)."""

from __future__ import annotations

import re

from fastmcp import FastMCP
from google.cloud.support_v2.types import case_service, comment_service

from .errors import from_grpc, to_tool_error
from .serializers import to_case_detail, to_comment
from .settings import Settings

__all__ = ["register_resources"]

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.]*$")


def register_resources(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.resource("case://{parent_type}/{parent_id}/{case_id}")
    async def case_resource(parent_type: str, parent_id: str, case_id: str) -> str:
        """A support case with its recent conversation, as readable text."""
        if parent_type not in ("projects", "organizations"):
            raise ValueError("parent_type must be 'projects' or 'organizations'")
        # Both segments are validated rather than trusted: a resource URI is
        # user-supplied input that becomes part of an upstream resource name.
        if not _SEGMENT.match(parent_id) or not _SEGMENT.match(case_id):
            raise ValueError("Invalid resource identifier")

        name = f"{parent_type}/{parent_id}/cases/{case_id}"
        clients = get_clients()
        try:
            detail = to_case_detail(
                await clients.cases.get_case(request=case_service.GetCaseRequest(name=name))
            )
            comments = await clients.comments.list_comments(
                request=comment_service.ListCommentsRequest(parent=name, page_size=10)
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        lines = [
            f"# {detail.title}",
            f"State: {detail.state} | Priority: {detail.priority} | Escalated: {detail.escalated}",
            f"Console: {detail.ref.console_url or detail.ref.name}",
            "",
            detail.description,
            "",
            "## Recent comments",
        ]
        for proto in comments.comments:
            comment = to_comment(proto)
            lines.append(f"- [{comment.author_side}] {comment.create_time}: {comment.body}")
        return "\n".join(lines)
