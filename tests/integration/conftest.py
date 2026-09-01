"""Integration-test guards.

Two gates, because "I turned on integration tests and it filed support tickets"
is a failure mode worth designing against:

  * GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT enables integration tests at all.
  * GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1 is additionally required for anything
    that writes.

And one enforcement that does not rely on anyone remembering: every CreateCase
request is asserted to carry test_case=True before it is allowed to leave.
A case without that flag becomes a real ticket routed to a support engineer.
"""

from __future__ import annotations

import os

import pytest

IT_PARENT = os.environ.get("GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT")
ALLOW_WRITES = os.environ.get("GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES") == "1"

requires_api = pytest.mark.skipif(
    not IT_PARENT, reason="set GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT to run integration tests"
)
requires_write_optin = pytest.mark.skipif(
    not (IT_PARENT and ALLOW_WRITES),
    reason="writing tests need GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1 as well",
)


def assert_test_case_only(request) -> None:
    """Refuse to let a CreateCase go out without test_case=True."""
    case = getattr(request, "case", None)
    if case is None or not getattr(case, "test_case", False):
        raise AssertionError(
            "Refusing to create a support case without test_case=True — it would become "
            "a real ticket routed to a Google support engineer."
        )


@pytest.fixture
def it_parent() -> str:
    if not IT_PARENT:
        pytest.skip("GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT not set")
    return IT_PARENT
