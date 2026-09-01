"""Case tools. US1 exposes the two read paths; writes arrive with US2/US3."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context, FastMCP
from google.cloud.support_v2.types import case as case_types
from google.cloud.support_v2.types import case_service
from google.cloud.support_v2.types import escalation as escalation_types
from google.protobuf import field_mask_pb2
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from ..confirm import request_confirmation
from ..errors import custom, from_grpc, to_tool_error
from ..fanout import CursorError, fanout_list
from ..models import (
    CaseDetail,
    CasePriority,
    CaseStateFilter,
    CaseSummary,
    ErrorKind,
    EscalationReason,
    ListEnvelope,
)
from ..serializers import to_case_detail, to_case_summary
from ..settings import Settings
from .classifications import classification_catalog

__all__ = ["build_query", "register"]


def build_query(
    state: CaseStateFilter | None,
    priorities: list[CasePriority] | None,
    creator_email: str | None,
    updated_after: str | None,
    text: str | None,
) -> str:
    """Compose the v2 search grammar.

    An empty query returns everything under the parent, which is what makes a
    plain listing a mode of this tool rather than a separate RPC.
    """
    clauses: list[str] = []
    if state is not None:
        clauses.append(f"state={state.value}")
    if priorities:
        # Parenthesised on purpose: `AND priority=P0 OR priority=P1` would bind wrong.
        joined = " OR ".join(f"priority={p.value}" for p in priorities)
        clauses.append(f"({joined})" if len(priorities) > 1 else joined)
    if creator_email:
        clauses.append(f'creator.email="{creator_email}"')
    if updated_after:
        # update_time only supports the greater-than operator.
        clauses.append(f'update_time>"{updated_after}"')
    query = " AND ".join(clauses)
    if text:
        query = f'"{text}" {query}'.strip() if query else f'"{text}"'
    return query


def register(mcp: FastMCP, settings: Settings, get_clients) -> None:
    @mcp.tool(
        tags={"cases", "read"},
        annotations=ToolAnnotations(
            title="Search support cases", read_only_hint=True, open_world_hint=True
        ),
    )
    async def search_cases(
        parents: Annotated[
            list[str] | None,
            Field(description="Scopes to search; defaults to GOOGLE_CLOUD_SUPPORT_MCP_PARENTS"),
        ] = None,
        state: Annotated[
            CaseStateFilter | None,
            Field(description="OPEN or CLOSED. Note the response uses a richer vocabulary."),
        ] = None,
        priorities: Annotated[
            list[CasePriority] | None, Field(description="P0 is most urgent, P4 least")
        ] = None,
        creator_email: str | None = None,
        updated_after: Annotated[
            str | None, Field(description="ISO-8601; only cases updated after this")
        ] = None,
        text: Annotated[
            str | None, Field(description="Free text across title, description, and comments")
        ] = None,
        page_size: int | None = None,
        cursor: Annotated[
            str | None, Field(description="Opaque token from a previous next_cursor")
        ] = None,
    ) -> ListEnvelope[CaseSummary]:
        """Find support cases across every configured project and organization.

        Returns results from every scope that answered. A scope that failed is
        reported in `scopes_failed` with what to do about it — one organization's
        permission error never hides another organization's cases.
        """
        scopes = parents or settings.parents
        if not scopes:
            raise to_tool_error(
                from_grpc(ValueError("no parents configured")).model_copy(
                    update={
                        "detail": (
                            "No scopes are configured. Set GOOGLE_CLOUD_SUPPORT_MCP_PARENTS to a JSON "
                            'list such as ["projects/my-project","organizations/123456789"], '
                            "or pass `parents` on this call."
                        )
                    }
                )
            )

        clients = get_clients()
        query = build_query(state, priorities, creator_email, updated_after, text)
        size = page_size or settings.default_page_size

        async def fetch(parent: str, token: str | None, limit: int):
            response = await clients.cases.search_cases(
                request=case_service.SearchCasesRequest(
                    parent=parent, query=query, page_size=limit, page_token=token or ""
                )
            )
            items = [to_case_summary(c) for c in response.cases]
            return items, (response.next_page_token or None)

        try:
            return await fanout_list(
                scopes,
                page_size=size,
                cursor=cursor,
                fetch=fetch,
                concurrency=settings.fanout_concurrency,
            )
        except CursorError as exc:
            raise to_tool_error(custom(ErrorKind.INVALID_ARGUMENT, str(exc))) from exc

    @mcp.tool(
        tags={"cases", "read"},
        annotations=ToolAnnotations(
            title="Get a support case",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_case(
        case_name: Annotated[
            str,
            Field(description="projects/{project}/cases/{id} or organizations/{org}/cases/{id}"),
        ],
    ):
        """Read one case in full, including its description and a console link."""
        clients = get_clients()
        try:
            proto = await clients.cases.get_case(
                request=case_service.GetCaseRequest(name=case_name)
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_case_detail(proto)

    # ----------------------------------------------------------------- write #

    @mcp.tool(
        tags={"cases", "write"},
        annotations=ToolAnnotations(
            title="Create a support case",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=True,
        ),
    )
    async def create_case(
        ctx: Context,
        parent: Annotated[str, Field(description="projects/{id} or organizations/{id}")],
        classification_id: Annotated[
            str, Field(description="An id returned by search_case_classifications")
        ],
        title: str,
        description: str,
        priority: Annotated[CasePriority, Field(description="P0 is most urgent, P4 least")],
        contact_email: str | None = None,
        subscriber_emails: list[str] | None = None,
        time_zone: Annotated[str | None, Field(description="e.g. +09:00")] = None,
        test_case: Annotated[
            bool,
            Field(description="Flag as a test case; it will not be routed to a support engineer"),
        ] = False,
    ) -> CaseDetail | InputRequiredResult:
        """Open a new Google Cloud support case.

        You will be shown the exact submission and asked to confirm before anything
        reaches Google. Declining creates nothing.
        """
        clients = get_clients()

        # Validate the classification *before* asking. Confirming an action that
        # cannot run wastes the user's decision (FR-009). There is no lookup-by-id
        # RPC, so this checks membership in the catalogue, which is cached.
        try:
            catalog = await classification_catalog(clients)
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        if classification_id not in catalog:
            hint = " ".join(title.split()[:3])
            near = [
                f"{cid} ({name})"
                for cid, name in catalog.items()
                if hint and hint.lower() in name.lower()
            ][:5]
            suggestion = (
                f" Closest matches for '{hint}': {', '.join(near)}."
                if near
                else " Run search_case_classifications to list valid ids."
            )
            raise to_tool_error(
                custom(
                    ErrorKind.INVALID_ARGUMENT,
                    f"'{classification_id}' is not a valid classification id. Nothing was "
                    f"created.{suggestion}",
                )
            )

        payload = {
            "parent": parent,
            "classification_id": classification_id,
            "title": title,
            "description": description,
            "priority": priority.value if hasattr(priority, "value") else str(priority),
            "contact_email": contact_email,
            "subscriber_emails": subscriber_emails or [],
            "time_zone": time_zone,
            "test_case": test_case,
        }
        flag = "TEST CASE (not routed to a support engineer)" if test_case else "REAL SUPPORT CASE"
        preview = (
            f"Create a {flag} under {parent}?\n\n"
            f"Title: {title}\n"
            f"Priority: {payload['priority']}\n"
            f"Classification: {classification_id}\n"
            f"Contact: {contact_email or '(default)'}\n\n"
            f"Description:\n{description}"
        )

        outcome = await request_confirmation(
            ctx, tool="create_case", preview=preview, payload=payload
        )
        if outcome.needs_input:
            return outcome.input_required

        approved = outcome.payload
        proto = case_types.Case(
            display_name=approved["title"],
            description=approved["description"],
            classification=case_types.CaseClassification(id=approved["classification_id"]),
            priority=approved["priority"],
            test_case=approved["test_case"],
        )
        if approved.get("contact_email"):
            proto.contact_email = approved["contact_email"]
        if approved.get("subscriber_emails"):
            proto.subscriber_email_addresses = approved["subscriber_emails"]
        if approved.get("time_zone"):
            proto.time_zone = approved["time_zone"]

        try:
            created = await clients.cases.create_case(
                request=case_service.CreateCaseRequest(parent=approved["parent"], case=proto)
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_case_detail(created)

    @mcp.tool(
        tags={"cases", "write"},
        annotations=ToolAnnotations(
            title="Update a support case",
            read_only_hint=False,
            destructive_hint=False,
            open_world_hint=True,
        ),
    )
    async def update_case(
        ctx: Context,
        case_name: str,
        title: str | None = None,
        description: str | None = None,
        priority: CasePriority | None = None,
        subscriber_emails: list[str] | None = None,
    ) -> CaseDetail | InputRequiredResult:
        """Change a case's attributes. You will see the before and after first."""
        changes = {
            "display_name": title,
            "description": description,
            "priority": priority.value if priority is not None else None,
            "subscriber_email_addresses": subscriber_emails,
        }
        supplied = {k: v for k, v in changes.items() if v is not None}
        if not supplied:
            raise to_tool_error(
                custom(
                    ErrorKind.INVALID_ARGUMENT,
                    "No field to change was supplied. Pass at least one of title, "
                    "description, priority, or subscriber_emails. Nothing was updated.",
                )
            )

        clients = get_clients()
        try:
            before = to_case_detail(
                await clients.cases.get_case(request=case_service.GetCaseRequest(name=case_name))
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc

        current = {
            "display_name": before.title,
            "description": before.description,
            "priority": before.priority.value,
            "subscriber_email_addresses": before.subscriber_emails,
        }
        lines = [f"Update {case_name}?", ""]
        lines += [
            f"  {field}: {current[field]!r}  ->  {value!r}" for field, value in supplied.items()
        ]
        preview = "\n".join(lines)

        outcome = await request_confirmation(
            ctx,
            tool="update_case",
            preview=preview,
            payload={"case_name": case_name, "changes": supplied},
        )
        if outcome.needs_input:
            return outcome.input_required

        approved = outcome.payload
        proto = case_types.Case(name=approved["case_name"], **approved["changes"])
        try:
            updated = await clients.cases.update_case(
                request=case_service.UpdateCaseRequest(
                    case=proto,
                    update_mask=field_mask_pb2.FieldMask(paths=list(approved["changes"])),
                )
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_case_detail(updated)

    @mcp.tool(
        tags={"cases", "write", "destructive"},
        annotations=ToolAnnotations(
            title="Close a support case",
            read_only_hint=False,
            destructive_hint=True,
            open_world_hint=True,
        ),
    )
    async def close_case(ctx: Context, case_name: str) -> CaseDetail | InputRequiredResult:
        """Close a case. This cannot be reopened from here."""
        preview = (
            f"Close {case_name}?\n\n"
            "A closed case cannot be reopened through this server — you would have to "
            "open a new case or contact support through the console."
        )
        outcome = await request_confirmation(
            ctx, tool="close_case", preview=preview, payload={"case_name": case_name}
        )
        if outcome.needs_input:
            return outcome.input_required

        clients = get_clients()
        try:
            closed = await clients.cases.close_case(
                request=case_service.CloseCaseRequest(name=outcome.payload["case_name"])
            )
        except Exception as exc:
            raise to_tool_error(from_grpc(exc)) from exc
        return to_case_detail(closed)

    if settings.enable_escalation:

        @mcp.tool(
            tags={"cases", "write", "destructive", "escalation"},
            annotations=ToolAnnotations(
                title="Escalate a support case",
                read_only_hint=False,
                destructive_hint=True,
                open_world_hint=True,
            ),
        )
        async def escalate_case(
            ctx: Context,
            case_name: str,
            reason: EscalationReason,
            justification: Annotated[
                str, Field(description="Why this needs escalation — required, and read by a human")
            ],
        ) -> CaseDetail | InputRequiredResult:
            """Escalate a case to Google's support organisation.

            The sharpest tool here: a human at Google reads and acts on this.
            """
            preview = (
                f"Escalate {case_name}?\n\n"
                "This is delivered directly to Google's support organisation and a "
                "support manager will act on it. It is not a local flag.\n\n"
                f"Reason: {reason.value}\n"
                f"Justification: {justification}"
            )
            outcome = await request_confirmation(
                ctx,
                tool="escalate_case",
                preview=preview,
                payload={
                    "case_name": case_name,
                    "reason": reason.value,
                    "justification": justification,
                },
            )
            if outcome.needs_input:
                return outcome.input_required

            approved = outcome.payload
            clients = get_clients()
            try:
                escalated = await clients.cases.escalate_case(
                    request=case_service.EscalateCaseRequest(
                        name=approved["case_name"],
                        escalation=escalation_types.Escalation(
                            reason=approved["reason"], justification=approved["justification"]
                        ),
                    )
                )
            except Exception as exc:
                raise to_tool_error(from_grpc(exc)) from exc
            return to_case_detail(escalated)
