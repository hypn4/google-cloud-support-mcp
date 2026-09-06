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

import asyncio
import json
from pathlib import Path

from .errors import ErrorKind, custom, from_http, to_tool_error

__all__ = [
    "download_attachment_bytes",
    "safe_filename",
    "unique_path",
    "upload_attachment_file",
]

# Windows' forbidden set, applied on every platform on purpose. The name comes
# from Google's API, not from the local filesystem, so the same attachment
# should land in the same place wherever it is downloaded — and a name that is
# one inert file on POSIX is a traversal on Windows: "..\\..\\x" is a single
# odd filename under ext4 and three levels up under NTFS. Note this set contains
# both separators and the drive colon, which is what defuses "C:evil" too.
_ILLEGAL = set('<>:"/\\|?*')

# Windows refuses these whatever the extension, so "CON.txt" is unusable there
# and harmless here. Handled everywhere for the same reason as above.
_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_FALLBACK = "attachment"

# Filesystem limits are ~255 *bytes*, not characters — a name of accented or
# CJK characters reaches the ceiling two to three times sooner than its length
# suggests. 200 leaves room for the "-1".."-999" collision suffix below.
_MAX_NAME_BYTES = 200


def safe_filename(raw: str | None) -> str:
    """Reduce a server-supplied filename to one harmless path component.

    `Attachment.filename` is remote input: it arrives from the Cloud Support API
    and nothing upstream promises it is a bare name. Joined to a directory
    unchecked it is a write primitive — `directory / "/etc/passwd"` discards the
    directory outright, because joining an absolute path replaces the base, and
    `../../x` walks out of it.

    Awkward names are repaired rather than rejected: an attachment someone
    uploaded with a strange name should still download.
    """
    name = raw or ""

    # Split before filtering, not after. `_ILLEGAL` contains both separators, so
    # filtering first would collapse "a/b" into the single name "ab" instead of
    # yielding "b". Both conventions are honoured regardless of host OS, because
    # the string came from Google rather than from this machine.
    for separator in ("/", "\\"):
        name = name.rsplit(separator, 1)[-1]

    # Control characters (NUL included) and the forbidden set. Deliberately
    # narrow — everything else, non-ASCII included, is left alone so that
    # "rapport-final.pdf" or a CJK filename survives intact.
    name = "".join(ch for ch in name if ch >= " " and ch not in _ILLEGAL)

    # Windows silently drops trailing dots and spaces, so "x. " and "x" would be
    # the same file there. It also reduces "." and ".." to nothing, which is
    # precisely what should happen to them.
    name = name.rstrip(". ")

    if not name:
        return _FALLBACK

    if name.partition(".")[0].upper() in _RESERVED:
        name = f"{_FALLBACK}-{name}"

    return _truncate(name)


def _truncate(name: str) -> str:
    """Cap the name at a length every common filesystem accepts, keeping the extension."""
    if len(name.encode()) <= _MAX_NAME_BYTES:
        return name

    stem, dot, suffix = name.rpartition(".")
    if not dot or len(suffix.encode()) > 20:
        # No extension, or something too long to be one — treat it all as stem.
        stem, dot, suffix = name, "", ""

    room = _MAX_NAME_BYTES - len(f"{dot}{suffix}".encode())
    # Truncating bytes can split a multi-byte character; drop the fragment.
    clipped = stem.encode()[:room].decode(errors="ignore").rstrip(". ")
    return f"{clipped}{dot}{suffix}" if clipped else _FALLBACK


def unique_path(directory: Path, filename: str) -> Path:
    """Never clobber a file already on disk — add a suffix instead.

    `filename` is remote input and is reduced to a single component first; see
    `safe_filename`.
    """
    base = directory.resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / safe_filename(filename)

    # `safe_filename` cannot return a separator, so this cannot fire today. It is
    # asserted rather than assumed because it is the boundary that keeps a
    # download inside the directory the caller named: if that function is ever
    # loosened, this is what notices instead of the filesystem.
    if not candidate.is_relative_to(base):
        raise to_tool_error(
            custom(
                ErrorKind.INVALID_ARGUMENT,
                f"Refusing to write outside {base}. Nothing was downloaded.",
            )
        )

    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    # Derived from an already-sanitised name, so this needs no second check.
    for index in range(1, 1000):
        alternative = base / f"{stem}-{index}{suffix}"
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

    # Outside the block above on purpose: that one classifies *Google's* failures,
    # and a local disk error is not one. Left unguarded, ENOSPC or an unwritable
    # destination_dir escaped as a raw OSError rather than a tool error.
    #
    # In a thread because this is the whole attachment: a synchronous write here
    # stalls the event loop for as long as the disk takes, and this server runs
    # concurrent scope fan-out beside it. The write is what moves the bytes, so
    # it is the one that matters, not the stat calls around it.
    try:
        await asyncio.to_thread(destination.write_bytes, response.content)
    except OSError as exc:
        raise to_tool_error(
            custom(
                ErrorKind.INVALID_ARGUMENT,
                f"Fetched {len(response.content):,} bytes but could not write them to "
                f"{destination}: {exc.strerror or exc}. Check that the directory is "
                "writable and has free space, or pass a different destination_dir.",
            )
        ) from exc
    return destination, len(response.content), response.headers.get("content-type")


async def upload_attachment_file(clients, case_name: str, path: Path, filename: str) -> dict:
    """Upload a local file to a case via the media Upload URI.

    The filename travels in the `attachment` object of the request body, not as a
    query parameter — the official reference is explicit about this, and the
    summary that said otherwise was wrong.
    """
    headers = await clients.credentials.bearer_headers()
    metadata = json.dumps({"attachment": {"filename": filename}})
    # In a thread for the same reason as the download write, and read before the
    # request is built rather than inline in the dict: a file that vanished
    # between the confirmation and here is now a classified error instead of a
    # raw OSError, and it is reported without a wasted round trip to Google.
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        raise to_tool_error(
            custom(
                ErrorKind.INVALID_ARGUMENT,
                f"Could not read {path}: {exc.strerror or exc}. Nothing was sent.",
            )
        ) from exc
    files = {
        "metadata": (None, metadata, "application/json"),
        "file": (filename, content, "application/octet-stream"),
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
