"""Attachment tools. Metadata only in US1 — bytes never travel in a tool result."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context, FastMCP
from google.cloud.support_v2.types import attachment_service
from mcp.types import InputRequiredResult, ToolAnnotations

from ..confirm import request_confirmation
from ..errors import custom, from_grpc, to_tool_error
from ..media import download_attachment_bytes, unique_path, upload_attachment_file
from ..models import Attachment, DownloadedAttachment, ErrorKind, ListEnvelope
from ..serializers import to_attachment
from ..settings import Settings

__all__ = ["register"]


def register(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.tool(
        tags={"attachments", "read"},
        annotations=ToolAnnotations(
            title="List case attachments", read_only_hint=True, open_world_hint=True
        ),
    )
    async def list_attachments(
        case_name: str,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> ListEnvelope[Attachment]:
        """List the files attached to a case — names and sizes, not contents."""
        clients = get_clients()
        try:
            response = await clients.attachments.list_attachments(
                request=attachment_service.ListAttachmentsRequest(
                    parent=case_name,
                    page_size=page_size or settings.default_page_size,
                    page_token=cursor or "",
                )
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        token = response.next_page_token or None
        return ListEnvelope[Attachment](
            items=[to_attachment(a) for a in response.attachments],
            scopes_queried=[case_name],
            next_cursor=token,
            truncated=token is not None,
        )

    @mcp.tool(
        tags={"attachments", "read"},
        annotations=ToolAnnotations(
            title="Get attachment metadata",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_attachment(attachment_name: str) -> Attachment:
        """Read one attachment's metadata. Use download_attachment for the file itself."""
        clients = get_clients()
        try:
            proto = await clients.attachments.get_attachment(
                request=attachment_service.GetAttachmentRequest(name=attachment_name)
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_attachment(proto)

    @mcp.tool(
        tags={"attachments", "read"},
        annotations=ToolAnnotations(
            title="Download an attachment", read_only_hint=True, open_world_hint=True
        ),
    )
    async def download_attachment(
        attachment_name: str,
        destination_dir: str | None = None,
    ) -> DownloadedAttachment:
        """Save a case attachment to disk and return where it landed.

        The file contents are never returned through this tool — they would end up
        in the conversation and in logs. Read the file from the path instead.

        Marked read-only because it changes nothing at Google; the local write is
        exactly what was asked for, so no confirmation is needed.
        """
        clients = get_clients()
        try:
            meta = to_attachment(
                await clients.attachments.get_attachment(
                    request=attachment_service.GetAttachmentRequest(name=attachment_name)
                )
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        directory = Path(destination_dir) if destination_dir else settings.download_dir
        target = unique_path(directory, meta.filename or "attachment")
        path, size, mime = await download_attachment_bytes(clients, attachment_name, target)
        return DownloadedAttachment(
            attachment_name=attachment_name,
            local_path=str(path.resolve()),
            size_bytes=size,
            mime_type=mime or meta.mime_type,
        )

    @mcp.tool(
        tags={"attachments", "write"},
        annotations=ToolAnnotations(
            title="Attach a file to a case",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=True,
        ),
    )
    async def upload_attachment(
        ctx: Context,
        case_name: str,
        file_path: str,
        filename: str | None = None,
    ) -> Attachment | InputRequiredResult:
        """Attach a local file to a case, after confirming what will be sent."""
        source = Path(file_path).expanduser()
        if not source.is_file():
            raise to_tool_error(
                custom(ErrorKind.INVALID_ARGUMENT, f"No such file: {file_path}. Nothing was sent.")
            )
        size = source.stat().st_size
        if size > settings.max_upload_bytes:
            raise to_tool_error(
                custom(
                    ErrorKind.INVALID_ARGUMENT,
                    f"'{source.name}' is {size:,} bytes, which exceeds the configured limit of "
                    f"{settings.max_upload_bytes:,} (GOOGLE_CLOUD_SUPPORT_MCP_MAX_UPLOAD_BYTES). "
                    "Nothing was sent.",
                )
            )

        name = filename or source.name
        # The preview names the file and its size but never its contents: the
        # sealed token travels through the client, so it carries a path, not bytes.
        preview = (
            f"Attach a file to {case_name}?\n\nFile: {name}\nSize: {size:,} bytes\nSource: {source}"
        )
        outcome = await request_confirmation(
            ctx,
            tool="upload_attachment",
            preview=preview,
            payload={"case_name": case_name, "file_path": str(source), "filename": name},
        )
        if outcome.needs_input:
            return outcome.input_required

        approved = outcome.payload
        clients = get_clients()
        created = await upload_attachment_file(
            clients, approved["case_name"], Path(approved["file_path"]), approved["filename"]
        )
        return Attachment(
            name=created.get("name", ""),
            filename=created.get("filename", approved["filename"]),
            mime_type=created.get("mimeType"),
            size_bytes=int(created.get("sizeBytes", size) or size),
            create_time=created.get("createTime"),
        )
