"""Both protocol eras reach a user (research.md R-003).

FastMCP 4 rejects `ctx.elicit()` on modern connections and `InputRequiredResult`
on handshake-era ones, so the branch is load-bearing rather than defensive.
"""

from __future__ import annotations

from fastmcp.server.context import MODERN_PROTOCOL_VERSIONS

from cloud_support_mcp.confirm import _is_modern


class _Ctx:
    def __init__(self, version):
        self.request_context = type("RC", (), {"protocol_version": version})()


def test_modern_era_is_recognised():
    assert _is_modern(_Ctx("2026-07-28")) is True
    assert "2026-07-28" in MODERN_PROTOCOL_VERSIONS


def test_handshake_eras_take_the_elicit_path():
    assert _is_modern(_Ctx("2025-11-25")) is False
    assert _is_modern(_Ctx("2025-06-18")) is False


def test_missing_request_context_falls_back_to_the_handshake_path():
    ctx = _Ctx(None)
    ctx.request_context = None
    assert _is_modern(ctx) is False
