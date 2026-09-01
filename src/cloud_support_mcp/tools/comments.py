"""Comment tools — the conversation between the customer and Google Support."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context, FastMCP
from google.cloud.support_v2.types import comment as comment_types
from google.cloud.support_v2.types import comment_service
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from ..confirm import request_confirmation
from ..errors import custom, from_grpc, to_tool_error
from ..models import Comment, ErrorKind, ListEnvelope
from ..serializers import to_comment
from ..settings import Settings

__all__ = ["MAX_COMMENT_CHARS", "register"]

# The proto documents "Maximum of 12800 characters" on Comment.body.
MAX_COMMENT_CHARS = 12_800


def register(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.tool(
        tags={"comments", "read"},
        annotations=ToolAnnotations(
            title="List case comments", read_only_hint=True, open_world_hint=True
        ),
    )
    async def list_comments(
        case_name: str,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> ListEnvelope[Comment]:
        """Read a case's conversation in order, with each message attributed.

        `author_side` distinguishes the customer from Google Support, which is
        usually the first thing you need to know when catching up on a case.
        """
        clients = get_clients()
        try:
            response = await clients.comments.list_comments(
                request=comment_service.ListCommentsRequest(
                    parent=case_name,
                    page_size=page_size or settings.default_page_size,
                    page_token=cursor or "",
                )
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        token = response.next_page_token or None
        return ListEnvelope[Comment](
            items=[to_comment(c) for c in response.comments],
            scopes_queried=[case_name],
            next_cursor=token,
            truncated=token is not None,
        )

    @mcp.tool(
        tags={"comments", "read"},
        annotations=ToolAnnotations(
            title="Get a comment", read_only_hint=True, idempotent_hint=True, open_world_hint=True
        ),
    )
    async def get_comment(
        comment_name: Annotated[str, Field(description="…/cases/{id}/comments/{comment_id}")],
    ) -> Comment:
        """Read one comment by name."""
        clients = get_clients()
        try:
            proto = await clients.comments.get_comment(
                request=comment_service.GetCommentRequest(name=comment_name)
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_comment(proto)

    @mcp.tool(
        tags={"comments", "write"},
        annotations=ToolAnnotations(
            title="Add a comment",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=True,
        ),
    )
    async def add_comment(
        ctx: Context,
        case_name: str,
        body: Annotated[str, Field(description="Comment text, up to 12,800 characters")],
    ) -> Comment | InputRequiredResult:
        """Post a comment to a case, after showing you exactly what will be sent."""
        if len(body) > MAX_COMMENT_CHARS:
            raise to_tool_error(
                custom(
                    ErrorKind.INVALID_ARGUMENT,
                    f"The comment is {len(body):,} characters; the API accepts at most "
                    f"{MAX_COMMENT_CHARS:,}. Nothing was posted. Shorten it, or attach the "
                    "detail as a file with upload_attachment.",
                )
            )

        preview = f"Post this comment to {case_name}?\n\n{body}"
        outcome = await request_confirmation(
            ctx, tool="add_comment", preview=preview, payload={"case_name": case_name, "body": body}
        )
        if outcome.needs_input:
            return outcome.input_required

        approved = outcome.payload
        clients = get_clients()
        try:
            created = await clients.comments.create_comment(
                request=comment_service.CreateCommentRequest(
                    parent=approved["case_name"],
                    comment=comment_types.Comment(body=approved["body"]),
                )
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_comment(created)
