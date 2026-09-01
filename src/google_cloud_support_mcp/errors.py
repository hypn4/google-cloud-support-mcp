"""Normalise failures from both transports into one vocabulary.

The server talks to the same Google service over two protocols — gRPC for the
thirteen GAPIC RPCs and HTTP for the two media endpoints that the SDK does not
generate. That means two exception families, and a user must not receive a
different shape of guidance depending on which one they happened to hit.

Every mapping goes through `_info`, so the guidance text for a given kind is
identical on both paths by construction rather than by convention.
"""

from __future__ import annotations

import httpx
from fastmcp.exceptions import ToolError
from google.api_core import exceptions as gexc
from pydantic import BaseModel

from .models import ErrorKind

__all__ = ["ErrorInfo", "ErrorKind", "custom", "from_grpc", "from_http", "to_tool_error"]


class ErrorInfo(BaseModel):
    kind: ErrorKind
    detail: str
    retryable: bool


# Guidance is written as the user's *next step*, never as a restatement of the
# failure. `UNKNOWN` carries real guidance too: FR-021 and SC-006 are all-inclusive,
# so an empty or passthrough message there is a miss, not a default.
_GUIDANCE: dict[ErrorKind, tuple[str, bool]] = {
    ErrorKind.PERMISSION_DENIED: (
        "Access denied. Grant roles/cloudsupport.techSupportViewer (read) or "
        "techSupportEditor (write) on this project, folder, or organization. "
        "Organization-level scopes additionally need resourcemanager.organizations.get. "
        "If the roles are already granted, verify the resource is covered by a paid support plan.",
        False,
    ),
    ErrorKind.API_NOT_ENABLED: (
        "The Cloud Support API is not enabled on this project. Run "
        "'gcloud services enable cloudsupport.googleapis.com --project=PROJECT_ID' "
        "(use the quota project when the target is an organization), then wait a "
        "minute for it to propagate and retry. This is not a permissions problem.",
        False,
    ),
    ErrorKind.SUPPORT_PLAN_REQUIRED: (
        "This resource is not eligible to use the Cloud Support API — it has no paid "
        "support plan. Standard, Enhanced, or Premium Support is required. Attach a "
        "support plan to this project or organization (or use a project that already "
        "has one), then retry. Reading may work where creating does not, so this can "
        "appear only when you try to open a case.",
        False,
    ),
    ErrorKind.UNAUTHENTICATED: (
        "No usable credentials. Run 'gcloud auth application-default login', or set "
        "GOOGLE_APPLICATION_CREDENTIALS to a service account key. If you already did, "
        "the credentials may have expired — re-run the login.",
        False,
    ),
    ErrorKind.NOT_FOUND: (
        "No such resource. Check the name format: cases are "
        "'projects/{project}/cases/{id}' or 'organizations/{org}/cases/{id}'. "
        "Also confirm the case lives under a parent you configured in "
        "GOOGLE_CLOUD_SUPPORT_MCP_PARENTS.",
        False,
    ),
    ErrorKind.INVALID_ARGUMENT: (
        "The request was rejected as malformed. Check required fields and value "
        "formats — classification ids come from search_case_classifications, and "
        "timestamps must be ISO-8601.",
        False,
    ),
    ErrorKind.FAILED_PRECONDITION: (
        "The resource is not in a state that allows this operation — for example, "
        "closing or escalating a case that is already closed. Fetch the case with "
        "get_case to see its current state.",
        False,
    ),
    ErrorKind.RATE_LIMITED: (
        "Google is rate limiting these requests. Wait a few seconds and retry. If it "
        "persists, lower GOOGLE_CLOUD_SUPPORT_MCP_FANOUT_CONCURRENCY so fewer scopes are "
        "queried at once.",
        True,
    ),
    ErrorKind.UNAVAILABLE: (
        "The Cloud Support API is temporarily unreachable or the request timed out. "
        "This is retryable — try again shortly.",
        True,
    ),
    ErrorKind.UNKNOWN: (
        "The request failed for a reason this server does not recognise. Retry once; "
        "if it repeats, verify credentials with 'gcloud auth application-default login' "
        "and confirm the Cloud Support API is enabled on the quota project "
        "('gcloud services enable cloudsupport.googleapis.com').",
        False,
    ),
}

# Substrings that mean the blocker is the support contract rather than IAM or state.
#
# "not eligible ... with this channel" was observed verbatim from a live 400 on
# 2026-09-01 when creating a case on a project without a paid plan. Note the
# status: the plan blocker arrives as FailedPrecondition(400), *not* the 403 the
# design assumed. Without this branch the user is told their case is "already
# closed", which is nonsense for a create.
_PLAN_SIGNATURES = (
    "support plan",
    "support account",
    "not entitled",
    "no entitlement",
    "not eligible",
    "with this channel",
)

# ...and when the API itself was never turned on. Observed verbatim from a live
# 403: "Google Cloud Support API has not been used in project X before or it is
# disabled." That reads as a permissions failure and is not one, so it is checked
# first — the fix is `gcloud services enable`, not an IAM grant.
_DISABLED_SIGNATURES = (
    "has not been used in project",
    "it is disabled",
    "api is not enabled",
    "serviceusage",
)


def _info(kind: ErrorKind) -> ErrorInfo:
    detail, retryable = _GUIDANCE[kind]
    return ErrorInfo(kind=kind, detail=detail, retryable=retryable)


def _is_plan_blocked(message: str) -> bool:
    lowered = message.lower()
    return any(sig in lowered for sig in _PLAN_SIGNATURES)


def _classify_403(message: str) -> ErrorKind:
    lowered = message.lower()
    if any(sig in lowered for sig in _DISABLED_SIGNATURES):
        return ErrorKind.API_NOT_ENABLED
    if _is_plan_blocked(lowered):
        return ErrorKind.SUPPORT_PLAN_REQUIRED
    # Fall back to the permission reading, whose guidance also tells the user to
    # check the support plan — so an unrecognised 403 still points more than one way.
    return ErrorKind.PERMISSION_DENIED


_GRPC_MAP: tuple[tuple[type[BaseException], ErrorKind], ...] = (
    (gexc.Unauthenticated, ErrorKind.UNAUTHENTICATED),
    (gexc.NotFound, ErrorKind.NOT_FOUND),
    (gexc.InvalidArgument, ErrorKind.INVALID_ARGUMENT),
    (gexc.FailedPrecondition, ErrorKind.FAILED_PRECONDITION),
    (gexc.ResourceExhausted, ErrorKind.RATE_LIMITED),
    (gexc.ServiceUnavailable, ErrorKind.UNAVAILABLE),
    (gexc.DeadlineExceeded, ErrorKind.UNAVAILABLE),
    # Google returns a bare 500 for some malformed scopes (observed live for a
    # project that does not exist). The HTTP path already maps 500 to UNAVAILABLE,
    # so the gRPC path must too or the two transports disagree.
    (gexc.InternalServerError, ErrorKind.UNAVAILABLE),
    (gexc.GatewayTimeout, ErrorKind.UNAVAILABLE),
)

_HTTP_MAP: dict[int, ErrorKind] = {
    400: ErrorKind.INVALID_ARGUMENT,
    401: ErrorKind.UNAUTHENTICATED,
    404: ErrorKind.NOT_FOUND,
    409: ErrorKind.FAILED_PRECONDITION,
    412: ErrorKind.FAILED_PRECONDITION,
    429: ErrorKind.RATE_LIMITED,
    500: ErrorKind.UNAVAILABLE,
    502: ErrorKind.UNAVAILABLE,
    503: ErrorKind.UNAVAILABLE,
    504: ErrorKind.UNAVAILABLE,
}


def from_grpc(exc: BaseException) -> ErrorInfo:
    """Classify an exception raised by the GAPIC async clients."""
    if isinstance(exc, gexc.PermissionDenied):
        return _info(_classify_403(str(exc)))
    # The support-plan blocker does not always arrive as 403: creating a case on a
    # project without a plan returns FailedPrecondition. Checked before the generic
    # state-conflict reading, which would otherwise give badly wrong guidance.
    if isinstance(exc, gexc.FailedPrecondition) and _is_plan_blocked(str(exc)):
        return _info(ErrorKind.SUPPORT_PLAN_REQUIRED)
    for exc_type, kind in _GRPC_MAP:
        if isinstance(exc, exc_type):
            return _info(kind)
    return _info(ErrorKind.UNKNOWN)


def from_http(exc: BaseException) -> ErrorInfo:
    """Classify an exception raised by the media REST path.

    Returns the same ErrorInfo a gRPC failure with the equivalent status would.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text or ""
        if status == 403:
            return _info(_classify_403(body))
        if status == 400 and _is_plan_blocked(body):
            return _info(ErrorKind.SUPPORT_PLAN_REQUIRED)
        kind = _HTTP_MAP.get(status)
        if kind is not None:
            return _info(kind)
        return _info(ErrorKind.UNKNOWN)
    if isinstance(exc, httpx.TimeoutException):
        return _info(ErrorKind.UNAVAILABLE)
    if isinstance(exc, httpx.TransportError):
        return _info(ErrorKind.UNAVAILABLE)
    return _info(ErrorKind.UNKNOWN)


def custom(kind: ErrorKind, detail: str, *, retryable: bool = False) -> ErrorInfo:
    """Classify a failure this server detected itself, before any upstream call.

    Used where the guidance is more specific than the table's generic text — an
    unusable cursor, or no scopes configured.
    """
    return ErrorInfo(kind=kind, detail=detail, retryable=retryable)


def to_tool_error(info: ErrorInfo) -> ToolError:
    """Wrap classified information for the client.

    `mask_error_details=True` on the server means only ToolError text reaches a
    client, so anything that skips this function leaks nothing.
    """
    suffix = " (retryable)" if info.retryable else ""
    return ToolError(f"[{info.kind.value}]{suffix} {info.detail}")
