"""Cross-org fan-out: query every configured scope in parallel and merge.

Neither v2 nor v2beta can search more than one parent per call — the query
grammar's OR only combines values within a single field, never scope identifiers
(research.md R-004). So cross-org lives here, on the client, and three
consequences follow from that:

  * Google's page tokens are per-parent, so a merged result needs a composite
    cursor rather than a passthrough token.
  * Partial failure is the normal case, not an exception: with N parents one may
    lack permission and another may lack a support plan. A single 403 must not
    hide the parents that succeeded.
  * Concurrency multiplies rate-limit exposure, so it is bounded.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from .errors import from_grpc
from .models import ListEnvelope, ScopeFailure

__all__ = ["CursorError", "decode_cursor", "encode_cursor", "fanout_list"]

_CURSOR_VERSION = 1

# One page fetch for a single parent: (items, next_page_token or None).
FetchPage = Callable[[str, str | None, int], Awaitable[tuple[list[Any], str | None]]]


class CursorError(ValueError):
    """Raised for a cursor this server did not issue, or that no longer fits the request."""


def encode_cursor(cursors: dict[str, str | None]) -> str | None:
    """Pack per-parent page tokens into one opaque string.

    Returns None when every parent is exhausted — there is nothing left to page.
    """
    if all(token is None for token in cursors.values()):
        return None
    payload = json.dumps(
        {"v": _CURSOR_VERSION, "cursors": cursors}, separators=(",", ":"), sort_keys=True
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str, expected_parents: Iterable[str]) -> dict[str, str | None]:
    """Unpack a cursor, rejecting anything that would silently skew results."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise CursorError(
            "The cursor is not one this server issued. Drop it and start from the first page."
        ) from exc

    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise CursorError(
            "The cursor uses an unsupported format version. Start from the first page."
        )

    cursors = payload.get("cursors")
    if not isinstance(cursors, dict):
        raise CursorError("The cursor is malformed. Start from the first page.")

    # A cursor is only meaningful for the scope set it was issued against. If the
    # caller changed `parents` mid-pagination, continuing would quietly drop or
    # duplicate results, so refuse instead.
    if set(cursors) != set(expected_parents):
        raise CursorError(
            "The cursor was issued for a different set of parents than this request uses. "
            "Either repeat the original parents, or omit the cursor to start over."
        )
    return cursors


async def fanout_list(
    parents: Sequence[str],
    *,
    page_size: int,
    cursor: str | None,
    fetch: FetchPage,
    concurrency: int = 5,
) -> ListEnvelope[Any]:
    """Fetch one page from each live parent concurrently and merge the results.

    A parent that fails contributes a ScopeFailure rather than aborting the call.
    """
    parent_list = list(parents)
    tokens: dict[str, str | None] = (
        decode_cursor(cursor, parent_list) if cursor else dict.fromkeys(parent_list)
    )

    # Parents whose token is None *and* that we have paged before are exhausted.
    # On the first page every token is None, so everything is live.
    live = parent_list if cursor is None else [p for p in parent_list if tokens[p] is not None]

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(parent: str) -> tuple[str, list[Any], str | None, Exception | None]:
        async with semaphore:
            try:
                items, next_token = await fetch(parent, tokens[parent], page_size)
            except Exception as exc:
                # Deliberately Exception, not BaseException: asyncio.CancelledError
                # must propagate so a cancelled request stops instead of being
                # recorded as a per-parent failure.
                return parent, [], None, exc
            return parent, items, next_token, None

    results = await asyncio.gather(*(run(p) for p in live))

    items: list[Any] = []
    failures: list[ScopeFailure] = []
    next_tokens: dict[str, str | None] = dict.fromkeys(parent_list)

    for parent, page_items, next_token, exc in results:
        if exc is not None:
            info = from_grpc(exc)
            failures.append(
                ScopeFailure(
                    parent=parent,
                    reason=info.kind,
                    detail=info.detail,
                    retryable=info.retryable,
                )
            )
            continue
        items.extend(page_items)
        next_tokens[parent] = next_token

    next_cursor = encode_cursor(next_tokens)
    return ListEnvelope[Any](
        items=items,
        scopes_queried=parent_list,
        scopes_failed=failures,
        next_cursor=next_cursor,
        truncated=next_cursor is not None,
    )
