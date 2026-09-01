"""User confirmation for anything that leaves this machine (FR-016, FR-017).

FastMCP 4 removed `ctx.elicit()` on modern connections and rejects
`InputRequiredResult` on handshake-era ones, so branching on the negotiated
protocol version is required, not optional.

The design point worth keeping: round one seals the *entire outgoing payload*
into `request_state`, and round two executes that payload verbatim instead of
rebuilding it. The framework signs and verifies that token, so "what the user
approved is what gets sent" is enforced by the framework rather than by
convention. A `confirm: bool` parameter cannot do this — the model fills that in,
not the user.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.context import MODERN_PROTOCOL_VERSIONS
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

__all__ = ["NO_ELICITATION_MESSAGE", "ConfirmationOutcome", "request_confirmation"]

_KEY = "confirm"
_FIELD = "approve"

NO_ELICITATION_MESSAGE = (
    "This action needs your explicit confirmation before anything is sent to Google "
    "Support, but this client cannot prompt you (no elicitation support). Nothing was "
    "changed. Use a client that supports elicitation, or perform this action in the "
    "Cloud Console."
)

DECLINED_MESSAGE = "Cancelled — nothing was sent to Google Support and no change was made."


@dataclass(slots=True)
class ConfirmationOutcome:
    """Either 'ask the user' (return `input_required`) or 'go ahead' (use `payload`)."""

    input_required: InputRequiredResult | None = None
    payload: dict[str, Any] | None = None

    @property
    def needs_input(self) -> bool:
        return self.input_required is not None


def _seal(tool: str, preview: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "tool": tool,
            "payload": payload,
            "preview": preview,
            "issued_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _unseal(tool: str, raw: str | None) -> dict[str, Any]:
    if not raw:
        raise ToolError(
            "The confirmation token was lost between rounds. Nothing was sent. Retry the action."
        )
    try:
        state = json.loads(raw)
    except ValueError as exc:
        raise ToolError("The confirmation token is unreadable. Nothing was sent.") from exc

    # A token issued for one tool must not be redeemable by another.
    if state.get("tool") != tool:
        raise ToolError(
            f"The confirmation token was issued for '{state.get('tool')}', not '{tool}'. "
            "Nothing was sent."
        )
    payload = state.get("payload")
    if not isinstance(payload, dict):
        raise ToolError("The confirmation token carries no payload. Nothing was sent.")
    return payload


def _ask(preview: str, request_state: str) -> InputRequiredResult:
    params = ElicitRequestFormParams(
        message=preview,
        requested_schema={
            "type": "object",
            "properties": {
                _FIELD: {
                    "type": "boolean",
                    "description": "Send this to Google Support?",
                }
            },
            "required": [_FIELD],
        },
    )
    return InputRequiredResult(
        result_type="input_required",
        input_requests={_KEY: ElicitRequest(method="elicitation/create", params=params)},
        request_state=request_state,
    )


def _is_modern(ctx: Context) -> bool:
    request_context = ctx.request_context
    if request_context is None:
        return False
    return getattr(request_context, "protocol_version", None) in MODERN_PROTOCOL_VERSIONS


async def request_confirmation(
    ctx: Context,
    *,
    tool: str,
    preview: str,
    payload: dict[str, Any],
) -> ConfirmationOutcome:
    """Obtain the user's own approval before an outward-facing action.

    `preview` is what the user reads; `payload` is exactly what will be sent.
    Returning an outcome with `needs_input` means the caller should return
    `outcome.input_required` unchanged and wait for the next round.
    """
    if _is_modern(ctx):
        responses = ctx.input_responses
        if not responses or _KEY not in responses:
            # Round one: ask, and carry the payload forward sealed.
            return ConfirmationOutcome(input_required=_ask(preview, _seal(tool, preview, payload)))

        answer = responses[_KEY]
        # Check the action before touching content — a client may decline or cancel.
        if getattr(answer, "action", None) != "accept":
            raise ToolError(DECLINED_MESSAGE)
        content = getattr(answer, "content", None) or {}
        if content.get(_FIELD) is not True:
            raise ToolError(DECLINED_MESSAGE)

        return ConfirmationOutcome(payload=_unseal(tool, ctx.request_state))

    # Handshake era (<= 2025-11-25): the blocking back-channel still exists.
    try:
        result = await ctx.elicit(preview, response_type=bool)
    except ToolError:
        raise
    except Exception as exc:
        # No elicitation capability on this client. That is FR-019's shape exactly:
        # change nothing, and say why it could not run.
        raise ToolError(NO_ELICITATION_MESSAGE) from exc

    if getattr(result, "action", None) != "accept" or getattr(result, "data", None) is not True:
        raise ToolError(DECLINED_MESSAGE)
    return ConfirmationOutcome(payload=payload)
