"""Convert Google's proto messages into the declared output models.

Two rules drive everything here. Protos never leak through — enums become their
string names and timestamps become ISO-8601 text, so a client is never handed
`{"state": 3}` to interpret. And every case reference carries a console link
(FR-023), because the answer to "show me this case" is often "open it".
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .models import (
    Attachment,
    CaseDetail,
    CasePriority,
    CaseState,
    CaseSummary,
    Classification,
    Comment,
    ResourceRef,
)

__all__ = [
    "parse_resource_ref",
    "to_attachment",
    "to_case_detail",
    "to_case_summary",
    "to_classification",
    "to_comment",
]

_CONSOLE = "https://console.cloud.google.com/support/cases/detail"
_CASE_NAME = re.compile(r"^(?P<kind>projects|organizations)/(?P<pid>[^/]+)/cases/(?P<cid>[^/]+)$")


def _iso(ts: Any) -> str | None:
    """Timestamp -> ISO-8601 text, or None when unset.

    proto-plus surfaces a `Timestamp` field as `DatetimeWithNanoseconds`
    (a datetime subclass) and leaves it None when unset — verified against the
    installed 0.5.3 wheel — so datetime is the primary path. The raw pb2 branch
    is a fallback for callers that hand us an unconverted message.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    seconds = getattr(ts, "seconds", 0)
    nanos = getattr(ts, "nanos", 0)
    if not seconds and not nanos:
        return None
    return ts.ToDatetime(tzinfo=UTC).isoformat()


def _enum_name(value: Any, enum_type: type, default: Any) -> Any:
    """Proto enum -> our StrEnum, tolerating values we do not know."""
    try:
        return enum_type(value.name if hasattr(value, "name") else str(value))
    except ValueError, AttributeError:
        return default


def parse_resource_ref(name: str) -> ResourceRef:
    """Build addressing info for a case resource name.

    A name we cannot parse still yields a usable ref: the name survives and
    `console_url` is None. Failing to build a link must never fail the lookup.
    """
    match = _CASE_NAME.match(name or "")
    if match is None:
        return ResourceRef(name=name)

    kind, pid, cid = match["kind"], match["pid"], match["cid"]
    if kind == "projects":
        parent_type, url = "project", f"{_CONSOLE}/{cid}?project={pid}"
    else:
        parent_type, url = "organization", f"{_CONSOLE}/{cid}?organizationId={pid}"
    return ResourceRef(
        name=name,
        parent=f"{kind}/{pid}",
        parent_type=parent_type,
        case_id=cid,
        console_url=url,
    )


def to_case_summary(proto: Any) -> CaseSummary:
    creator = getattr(proto, "creator", None)
    classification = getattr(proto, "classification", None)
    return CaseSummary(
        ref=parse_resource_ref(proto.name),
        title=proto.display_name or "",
        state=_enum_name(proto.state, CaseState, CaseState.STATE_UNSPECIFIED),
        priority=_enum_name(proto.priority, CasePriority, CasePriority.PRIORITY_UNSPECIFIED),
        escalated=bool(proto.escalated),
        create_time=_iso(proto.create_time),
        update_time=_iso(proto.update_time),
        creator_email=(creator.email or None) if creator else None,
        classification=(classification.display_name or None) if classification else None,
        test_case=bool(proto.test_case),
    )


def to_case_detail(proto: Any) -> CaseDetail:
    summary = to_case_summary(proto)
    classification = getattr(proto, "classification", None)
    return CaseDetail(
        **summary.model_dump(),
        description=proto.description or "",
        classification_id=(classification.id or None) if classification else None,
        contact_email=proto.contact_email or None,
        subscriber_emails=list(proto.subscriber_email_addresses),
        time_zone=proto.time_zone or None,
        language_code=proto.language_code or None,
    )


def to_comment(proto: Any) -> Comment:
    """`plain_text_body` is never read — the proto marks it DEPRECATED. DO NOT USE."""
    creator = getattr(proto, "creator", None)
    is_support = bool(creator.google_support) if creator else False
    return Comment(
        name=proto.name,
        create_time=_iso(proto.create_time),
        author_display_name=(creator.display_name or None) if creator else None,
        author_email=(creator.email or None) if creator else None,
        author_side="google_support" if is_support else "customer",
        body=proto.body or "",
    )


def to_attachment(proto: Any) -> Attachment:
    creator = getattr(proto, "creator", None)
    return Attachment(
        name=proto.name,
        filename=proto.filename or "",
        mime_type=proto.mime_type or None,
        size_bytes=int(proto.size_bytes or 0),
        create_time=_iso(proto.create_time),
        creator_display_name=(creator.display_name or None) if creator else None,
    )


def to_classification(proto: Any) -> Classification:
    return Classification(id=proto.id, display_name=proto.display_name or "")
