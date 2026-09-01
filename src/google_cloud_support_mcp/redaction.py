"""Keep support data out of logs (FR-022).

Case bodies, comments, and attachment filenames routinely carry customer data
and sometimes credentials. FastMCP's stock logging middleware records message
content, so without this the diagnostic output becomes the leak.

Identifiers survive scrubbing on purpose — a log saying "get_case on
projects/p/cases/1 failed" is diagnosable; one saying "a call failed" is not.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

__all__ = ["REDACTED", "RedactionFilter", "RedactionMiddleware", "redact"]

REDACTED = "[redacted]"

# Field names that carry support content rather than addressing information.
_SENSITIVE_KEYS = frozenset(
    {
        "body",
        "plain_text_body",
        "description",
        "filename",
        "preview",
        "justification",
        "contact_email",
        "creator_email",
        "author_email",
        "subscriber_emails",
        "subscriber_email_addresses",
        "incident_notes",
        "text",
    }
)

_MAX_DEPTH = 12


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy with sensitive values replaced, leaving identifiers intact."""
    if _depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (REDACTED if key in _SENSITIVE_KEYS else redact(item, _depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(item, _depth + 1) for item in value)
    return value


class RedactionFilter(logging.Filter):
    """Scrub structured arguments before a record is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(arg) for arg in record.args)
        return True


class RedactionMiddleware(Middleware):
    """Log a scrubbed view of each tool call, and pass the call through untouched.

    The request is deliberately **not** mutated. Scrubbing what a tool receives
    would corrupt the payload — a comment body would be posted to Google as
    "[redacted]". FR-022 is about diagnostic output, so the scrubbing belongs on
    the logging path and nowhere else.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("google_cloud_support_mcp.calls")

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        message = getattr(context, "message", None)
        name = getattr(message, "name", "<unknown>")
        arguments = getattr(message, "arguments", None)
        if isinstance(arguments, dict):
            self._logger.debug("tool call %s args=%s", name, redact(arguments))
        return await call_next(context)


def install_log_redaction(logger_name: str = "") -> None:
    """Attach the filter to a logger and every handler already on it."""
    logger = logging.getLogger(logger_name)
    log_filter = RedactionFilter()
    logger.addFilter(log_filter)
    for handler in logger.handlers:
        handler.addFilter(log_filter)
