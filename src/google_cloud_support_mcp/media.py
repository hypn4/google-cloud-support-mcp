"""Attachment bytes over HTTP — the gap the SDK does not cover.

`CaseAttachmentService` generates only GetAttachment and ListAttachments, both
metadata. The bytes live behind two HTTP media endpoints that GAPIC codegen does
not model, verified against the 0.5.3 wheel (research.md R-002):

    GET  /v2/{name}:download?alt=media
    POST /upload/v2/{parent}/attachments      body: {"attachment": {...}}

`google-auth`'s AuthorizedSession is blocking, so credentials are used only to
mint a bearer token and httpx does the transport.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import from_http, to_tool_error

__all__ = ["download_attachment_bytes", "unique_path", "upload_attachment_file"]


def unique_path(directory: Path, filename: str) -> Path:
    """Never clobber a file already on disk — add a suffix instead."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / (filename or "attachment")
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        alternative = directory / f"{stem}-{index}{suffix}"
        if not alternative.exists():
            return alternative
    raise to_tool_error(from_http(RuntimeError("cannot find a free filename")))


async def download_attachment_bytes(
    clients, attachment_name: str, destination: Path
) -> tuple[Path, int, str | None]:
    """Stream an attachment to disk and return where it landed.

    Bytes are never returned to the caller: they would fight FR-022 and swamp the
    conversation. The path is the deliverable.
    """
    headers = await clients.credentials.bearer_headers()
    url = f"/v2/{attachment_name}:download"
    try:
        response = await clients.http.get(url, params={"alt": "media"}, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        raise to_tool_error(from_http(exc)) from exc

    destination.write_bytes(response.content)
    return destination, len(response.content), response.headers.get("content-type")


async def upload_attachment_file(clients, case_name: str, path: Path, filename: str) -> dict:
    """Upload a local file to a case via the media Upload URI.

    The filename travels in the `attachment` object of the request body, not as a
    query parameter — the official reference is explicit about this, and the
    summary that said otherwise was wrong.
    """
    headers = await clients.credentials.bearer_headers()
    metadata = json.dumps({"attachment": {"filename": filename}})
    files = {
        "metadata": (None, metadata, "application/json"),
        "file": (filename, path.read_bytes(), "application/octet-stream"),
    }
    try:
        response = await clients.http.post(
            f"/upload/v2/{case_name}/attachments",
            params={"uploadType": "multipart"},
            headers=headers,
            files=files,
        )
        response.raise_for_status()
    except Exception as exc:
        raise to_tool_error(from_http(exc)) from exc
    return response.json()
