"""redaction.py — support data must not reach logs (FR-022).

The default logging middleware records message content, and here that content is
customer support data, so scrubbing is not optional.
"""

import logging

from google_cloud_support_mcp.redaction import REDACTED, RedactionFilter, redact

SECRET_BODY = "Our API key AKIA-EXAMPLE stopped working at 02:00"


class TestRedact:
    def test_scrubs_case_body_fields(self):
        out = redact({"name": "projects/p/cases/1", "description": SECRET_BODY})
        assert out["name"] == "projects/p/cases/1", "식별자는 진단에 필요하므로 남긴다"
        assert out["description"] == REDACTED

    def test_scrubs_comment_body_and_filename(self):
        out = redact({"body": SECRET_BODY, "filename": "customer-dump.sql"})
        assert out["body"] == REDACTED
        assert out["filename"] == REDACTED

    def test_recurses_into_nested_structures(self):
        out = redact({"items": [{"body": SECRET_BODY}, {"description": SECRET_BODY}]})
        assert out["items"][0]["body"] == REDACTED
        assert out["items"][1]["description"] == REDACTED

    def test_leaves_non_sensitive_values_intact(self):
        out = redact({"state": "CLOSED", "priority": "P1", "size_bytes": 10})
        assert out == {"state": "CLOSED", "priority": "P1", "size_bytes": 10}


def test_logging_filter_scrubs_records(caplog):
    logger = logging.getLogger("google_cloud_support_mcp.test")
    logger.addFilter(RedactionFilter())
    with caplog.at_level(logging.DEBUG, logger="google_cloud_support_mcp.test"):
        logger.info("case payload: %s", {"body": SECRET_BODY})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET_BODY not in text
    assert REDACTED in text


async def test_middleware_does_not_mutate_the_request():
    """Scrubbing what a tool receives would post "[redacted]" to Google Support."""
    from google_cloud_support_mcp.redaction import RedactionMiddleware

    class Message:
        def __init__(self) -> None:
            self.name = "add_comment"
            self.arguments = {"case_name": "projects/p/cases/1", "body": SECRET_BODY}

    class Ctx:
        def __init__(self) -> None:
            self.message = Message()

    ctx = Ctx()

    async def call_next(c):
        return c.message.arguments

    passed = await RedactionMiddleware().on_call_tool(ctx, call_next)
    assert passed["body"] == SECRET_BODY, "미들웨어가 요청을 변조했다"
    assert ctx.message.arguments["body"] == SECRET_BODY
