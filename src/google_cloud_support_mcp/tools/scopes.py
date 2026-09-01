"""Which projects and organizations this caller can reach.

Support cases hang off a project or an organization, and the API wants that scope
as `projects/{id}` or `organizations/{number}`. A person says "the Acme org". The
number is not something anyone remembers, so without this tool the only way to
address an organization is to configure it in advance — which is the whole
complaint this feature answers.

Two decisions here are easy to undo by accident:

**The filter never reaches the API.** Resource Manager can filter projects by
name, but only by *prefix* (`name:how*`), and it cannot filter organizations by
display name at all. Using the server-side query would make one argument mean two
things — `billing` finding `Acme Billing` and missing `my-billing-project`, with
no error to notice. So the query is always empty and matching happens here, once,
for both classes (002 research R-102, R-103, R-111).

**Paging is conditional on filtering.** Filtering one page locally would be worse
than the prefix bug it replaces: a match on page two would come back as "not
reachable", indistinguishable from a permissions problem. So a search pages and a
listing does not, and `truncated` says when we stopped early.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Protocol

from fastmcp import FastMCP
from google.cloud.resourcemanager_v3.types import (
    SearchOrganizationsRequest,
    SearchProjectsRequest,
)
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import custom, from_grpc, to_tool_error
from ..models import ListEnvelope, ScopeFailure, ScopeRef
from ..serializers import to_scope_ref
from ..settings import Settings

__all__ = ["register"]

# How many scopes one class may be paged through before we stop looking. A bound
# in *scopes* rather than pages on purpose: neither SearchProjectsRequest nor
# SearchOrganizationsRequest documents a maximum page_size, and both say the
# server may return fewer than asked, so a page count bounds an unknown quantity.
# Per class, not shared — the two run concurrently, and a shared counter would
# make the cut-off depend on which response arrived first.
_SCOPE_SEARCH_LIMIT = 1000

# How many to ask for per round trip *while searching*, where bigger is better:
# fewer calls to walk the same ground. Requested, not guaranteed — see above.
#
# Deliberately not reused for an unfiltered listing. That path returns what it
# fetched, so its page size decides how many rows land in the conversation, and
# 100 is the same "swamp the conversation" problem DEFAULT_PAGE_SIZE=20 exists to
# avoid. Listing pages at the configured size; searching pages at this one.
_SCOPE_SEARCH_PAGE_SIZE = 100


class _ScopePage(Protocol):
    """What both search responses have in common, for the paging loop's purposes."""

    next_page_token: str


# One page fetch, given a page token. Returns whichever response type the class uses.
FetchPage = Callable[[str], Awaitable[Any]]
# Pulls the scope rows out of that response — `.projects` or `.organizations`.
ItemsOf = Callable[[Any], Sequence[Any]]


def _matches(scope: ScopeRef, needle: str) -> bool:
    """One matcher for both classes. The absence of a branch here is the design."""
    lowered = needle.lower()
    return lowered in scope.display_name.lower() or lowered in scope.parent.lower()


async def _collect(
    fetch: FetchPage,
    items_of: ItemsOf,
    *,
    name_contains: str | None,
) -> tuple[list[ScopeRef], bool]:
    """Page one class and convert it. Returns the scopes and whether we stopped early.

    Without a filter this takes the first page and reports the rest as truncated:
    someone asking "what can I see?" does not want eight hundred rows in a
    conversation. With a filter it keeps going, because it is searching.
    """
    found: list[ScopeRef] = []
    examined = 0
    token = ""

    while True:
        response = await fetch(token)
        page = [to_scope_ref(raw) for raw in items_of(response)]
        examined += len(page)
        found.extend(s for s in page if name_contains is None or _matches(s, name_contains))

        token = response.next_page_token or ""
        if not token:
            return found, False
        if name_contains is None:
            return found, True
        if examined >= _SCOPE_SEARCH_LIMIT:
            return found, True


def register(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.tool(
        tags={"scopes", "read"},
        annotations=ToolAnnotations(
            title="List reachable scopes", read_only_hint=True, open_world_hint=True
        ),
    )
    async def list_scopes(
        name_contains: Annotated[
            str | None,
            Field(
                description=(
                    "Narrow to scopes whose name or identifier contains this, "
                    "case-insensitively. Matches the same way for projects and "
                    "organizations."
                )
            ),
        ] = None,
        include_projects: bool = True,
        include_organizations: bool = True,
    ) -> ListEnvelope[ScopeRef]:
        """Find the projects and organizations these credentials can reach.

        Use this when the user names a scope you cannot turn into an identifier —
        especially an organization, which is addressed by a number nobody
        remembers. Each result's `parent` goes straight into `search_cases` or
        `create_case` with no editing.

        If several scopes match, ask the user which one; this deliberately does
        not choose for you. If nothing matches, call again without the filter and
        show them what is reachable.

        `truncated` means the search stopped before reaching the end, which on a
        large account is the normal outcome of any filtered lookup. It matters
        when the user might be missing something — nothing matched, or none of
        the matches looks like what they asked for. It does not matter when the
        thing they named came back: do not hedge an answer you actually found.

        Listing scopes needs `resourcemanager.projects.get` and, for
        organizations, `resourcemanager.organizations.get`. Holding one and not
        the other is normal: the class that could not be read is reported in
        `scopes_failed` and the other still answers.
        """
        clients = get_clients()

        # Searching wants big pages; listing wants a conversation-sized answer.
        page_size = _SCOPE_SEARCH_PAGE_SIZE if name_contains else settings.default_page_size

        async def projects() -> tuple[list[ScopeRef], bool]:
            async def fetch(token: str) -> _ScopePage:
                return await clients.projects.search_projects(
                    request=SearchProjectsRequest(query="", page_size=page_size, page_token=token)
                )

            return await _collect(fetch, lambda r: r.projects, name_contains=name_contains)

        async def organizations() -> tuple[list[ScopeRef], bool]:
            async def fetch(token: str) -> _ScopePage:
                return await clients.organizations.search_organizations(
                    request=SearchOrganizationsRequest(
                        query="", page_size=page_size, page_token=token
                    )
                )

            return await _collect(fetch, lambda r: r.organizations, name_contains=name_contains)

        planned: list[tuple[str, Any]] = []
        if include_organizations:
            planned.append(("organizations", organizations))
        if include_projects:
            planned.append(("projects", projects))

        results = await asyncio.gather(*(run() for _, run in planned), return_exceptions=True)

        items: list[ScopeRef] = []
        failures: list[ScopeFailure] = []
        truncated = False

        for (label, _), outcome in zip(planned, results, strict=True):
            if isinstance(outcome, BaseException):
                info = from_grpc(outcome)
                # `parent` holds the class rather than one scope: what failed is a
                # whole class of scope. ScopeFailure's contract already says its
                # presence does not fail the call.
                failures.append(
                    ScopeFailure(
                        parent=label,
                        reason=info.kind,
                        detail=info.detail,
                        retryable=info.retryable,
                    )
                )
                continue
            found, stopped_early = outcome
            items.extend(found)
            truncated = truncated or stopped_early

        if planned and len(failures) == len(planned):
            raise to_tool_error(
                custom(
                    failures[0].reason,
                    "No scopes could be listed. "
                    + " ".join(f"{f.parent}: {f.detail}" for f in failures),
                )
            )

        return ListEnvelope[ScopeRef](
            items=items,
            # Every class attempted, including the ones that failed — a failure
            # entry is uninterpretable without knowing what was tried.
            scopes_queried=[label for label, _ in planned],
            scopes_failed=failures,
            truncated=truncated,
        )
