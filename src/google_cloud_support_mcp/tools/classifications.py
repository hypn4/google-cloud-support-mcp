"""Problem classification lookup — the required first step before creating a case.

The `query` field is a **filter expression**, not free text. Passing a user's
keywords straight through fails with "Function operators are not supported."
Confirmed against the live API on 2026-09-01:

    ""                              -> everything (2,878 entries)
    display_name:"Compute Engine"   -> 0 results (exact match on a full path)
    display_name:"*Compute Engine*" -> matches, case-insensitively

Display names are hierarchical paths like
`Compute Engine > Create a VM`, so a substring glob is the only useful form.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from google.cloud.support_v2.types import case_service
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import from_grpc, to_tool_error
from ..models import Classification, ListEnvelope
from ..serializers import to_classification
from ..settings import Settings

__all__ = ["build_classification_query", "classification_catalog", "register", "search"]

_CATALOG_PAGE_SIZE = 500
_CATALOG_MAX_PAGES = 20

_catalog_cache: dict[str, str] | None = None
_catalog_lock = asyncio.Lock()


def build_classification_query(keywords: str) -> str:
    """Wrap free-text keywords into the filter expression the API accepts.

    An empty input returns everything, which is what the API does with an empty
    query — so it stays empty rather than becoming a match-nothing glob.
    """
    cleaned = " ".join(keywords.split())
    if not cleaned:
        return ""
    escaped = cleaned.replace('"', "")
    return f'display_name:"*{escaped}*"'


async def search(clients, keywords: str, limit: int) -> list[Classification]:
    response = await clients.cases.search_case_classifications(
        request=case_service.SearchCaseClassificationsRequest(
            query=build_classification_query(keywords), page_size=limit
        )
    )
    return [to_classification(c) for c in response.case_classifications]


async def classification_catalog(clients) -> dict[str, str]:
    """Every valid classification id mapped to its display name.

    There is no lookup-by-id RPC, so validating an id means knowing the catalog.
    It is a global, slow-moving list (~2,900 entries, six pages, a few seconds),
    so it is fetched once per process and reused.
    """
    global _catalog_cache
    async with _catalog_lock:
        if _catalog_cache is not None:
            return _catalog_cache

        catalog: dict[str, str] = {}
        token = ""
        for _ in range(_CATALOG_MAX_PAGES):
            response = await clients.cases.search_case_classifications(
                request=case_service.SearchCaseClassificationsRequest(
                    query="", page_size=_CATALOG_PAGE_SIZE, page_token=token
                )
            )
            for proto in response.case_classifications:
                catalog[proto.id] = proto.display_name
            token = response.next_page_token
            if not token:
                break
        _catalog_cache = catalog
        return catalog


def register(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.tool(
        tags={"classifications", "read"},
        annotations=ToolAnnotations(
            title="Search problem classifications", read_only_hint=True, open_world_hint=True
        ),
    )
    async def search_case_classifications(
        query: Annotated[
            str,
            Field(
                description=(
                    "Product name or symptom keywords, e.g. 'Compute Engine'. "
                    "Matched as a substring of the classification's display name; "
                    "an empty string returns the full catalogue."
                )
            ),
        ] = "",
        page_size: int | None = None,
    ) -> ListEnvelope[Classification]:
        """Find a valid problem classification for a new case.

        Case creation requires one of these ids, so this is the step before
        create_case rather than an optional lookup. The search is global — it
        takes no parent. Display names are hierarchical, like
        'Compute Engine > Create a VM'.
        """
        clients = get_clients()
        try:
            items = await search(clients, query, page_size or settings.default_page_size)
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return ListEnvelope[Classification](items=items, scopes_queried=[])
