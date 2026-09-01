"""Output models and enumerations — the source of every tool's output schema.

Nothing is exposed to a client unless it appears here. Proto values never leak
through: enums become their string names and timestamps become ISO-8601 text
(see specs/001-gcp-support-mcp/data-model.md).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .settings import _PARENT

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class CaseState(StrEnum):
    """Vocabulary of the `state` field on a returned case."""

    STATE_UNSPECIFIED = "STATE_UNSPECIFIED"
    NEW = "NEW"
    IN_PROGRESS_GOOGLE_SUPPORT = "IN_PROGRESS_GOOGLE_SUPPORT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    SOLUTION_PROVIDED = "SOLUTION_PROVIDED"
    CLOSED = "CLOSED"


class CaseStateFilter(StrEnum):
    """Vocabulary accepted by the search query — deliberately narrower than CaseState.

    The API's query grammar only understands OPEN and CLOSED. OPEN covers every
    state that is not CLOSED.
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CasePriority(StrEnum):
    """P0 is the most urgent and P4 the least — the numbering runs opposite to intuition."""

    PRIORITY_UNSPECIFIED = "PRIORITY_UNSPECIFIED"
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class EscalationReason(StrEnum):
    """Values confirmed against support_v2/types/escalation.py."""

    RESOLUTION_TIME = "RESOLUTION_TIME"
    TECHNICAL_EXPERTISE = "TECHNICAL_EXPERTISE"
    BUSINESS_IMPACT = "BUSINESS_IMPACT"


class ErrorKind(StrEnum):
    """One vocabulary for both transports (gRPC and the media REST path).

    Three kinds arrive as HTTP 403 and are deliberately kept apart, because the
    user's next step differs completely: grant a role, buy a support plan, or
    enable the API. Collapsing them sends people down the wrong path — the
    API-not-enabled case in particular reads as a permissions problem and is not.
    """

    PERMISSION_DENIED = "permission_denied"
    SUPPORT_PLAN_REQUIRED = "support_plan_required"
    API_NOT_ENABLED = "api_not_enabled"
    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    INVALID_ARGUMENT = "invalid_argument"
    FAILED_PRECONDITION = "failed_precondition"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Core entities
# --------------------------------------------------------------------------- #


class ResourceRef(BaseModel):
    """Address information carried by every case reference."""

    name: str = Field(description="Google resource name, e.g. projects/p/cases/123")
    parent: str | None = Field(default=None, description="projects/{id} or organizations/{id}")
    parent_type: Literal["project", "organization"] | None = None
    case_id: str | None = None
    console_url: str | None = Field(
        default=None,
        description="Direct Cloud Console link; None when the resource name could not be parsed",
    )


class CaseSummary(BaseModel):
    """List/search element. Deliberately omits `description` — 20 full bodies drown a conversation."""

    ref: ResourceRef
    title: str = ""
    state: CaseState = CaseState.STATE_UNSPECIFIED
    priority: CasePriority = CasePriority.PRIORITY_UNSPECIFIED
    escalated: bool = False
    create_time: str | None = None
    update_time: str | None = None
    creator_email: str | None = None
    classification: str | None = None
    test_case: bool = False


class CaseDetail(CaseSummary):
    """Single-case response — the only place a full description is returned."""

    description: str = ""
    classification_id: str | None = None
    contact_email: str | None = None
    subscriber_emails: list[str] = Field(default_factory=list)
    time_zone: str | None = None
    language_code: str | None = None


class Comment(BaseModel):
    """`plain_text_body` is never read — the proto marks it DEPRECATED. DO NOT USE."""

    name: str
    create_time: str | None = None
    author_display_name: str | None = None
    author_email: str | None = None
    author_side: Literal["customer", "google_support"] = "customer"
    body: str = ""


class Attachment(BaseModel):
    """Metadata only — bytes never travel through a tool result."""

    name: str
    filename: str = ""
    mime_type: str | None = None
    size_bytes: int = 0
    create_time: str | None = None
    creator_display_name: str | None = None


class DownloadedAttachment(BaseModel):
    attachment_name: str
    local_path: str = Field(description="Absolute path the file was written to")
    size_bytes: int
    mime_type: str | None = None


class Classification(BaseModel):
    id: str
    display_name: str = ""


class ScopeRef(BaseModel):
    """A project or organization that can hold support cases.

    `parent` is the whole point: it is the string the caller passes straight back
    as a scope, with no editing. For a project that means `projects/{project_id}`
    and never the project *number* the API returns in `Project.name` — the number
    addresses the same project and reads as noise in a list someone is scanning
    for a name they half-remember.
    """

    parent: str
    kind: Literal["project", "organization"]
    display_name: str = ""
    state: str = ""

    @field_validator("parent")
    @classmethod
    def _parent_is_addressable(cls, value: str) -> str:
        """Enforce the same shape the settings validator enforces.

        The point of this model is that `parent` can be handed straight back as a
        scope. A value the settings validator would reject looks usable and is
        not, so the check lives here rather than in a test of one construction
        site. The pattern is imported rather than restated — two regexes for one
        shape is how they drift.
        """
        if not _PARENT.match(value):
            raise ValueError(
                f"{value!r} is not addressable as a scope; "
                "expected projects/{id} or organizations/{id}"
            )
        return value


# --------------------------------------------------------------------------- #
# Fan-out envelope
# --------------------------------------------------------------------------- #


class ScopeFailure(BaseModel):
    """One parent that could not be queried. Its presence does not fail the call."""

    parent: str
    reason: ErrorKind
    detail: str
    retryable: bool


class ListEnvelope[T](BaseModel):
    """Shared shape for every list response, fan-out or not.

    `scopes_failed` being non-empty is still a successful call: one organization's
    permission error must not hide another organization's results.
    """

    items: list[T] = Field(default_factory=list)
    scopes_queried: list[str] = Field(default_factory=list)
    scopes_failed: list[ScopeFailure] = Field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
