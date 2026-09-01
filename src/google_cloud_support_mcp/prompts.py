"""Prompts aimed at the two success criteria that are about speed, not coverage."""

from __future__ import annotations

from fastmcp import FastMCP

from .settings import Settings

__all__ = ["register_prompts"]


def register_prompts(mcp: FastMCP, settings: Settings) -> None:
    @mcp.prompt(tags={"cases", "read"})
    def triage_open_cases(parents: list[str] | None = None) -> str:
        """Review every open support case and decide what to look at first (SC-001)."""
        scope = ", ".join(parents or settings.parents) or (
            "the scopes the user names — call list_scopes first if none is given"
        )
        return (
            f"Use search_cases with state=OPEN over {scope}. Then, for each case, judge "
            "urgency from its priority, how long it has been since update_time, and "
            "whether it is already escalated. Report a short ranked list: what needs "
            "attention now, what is waiting on Google, and what is waiting on us. "
            "If scopes_failed is non-empty, say which scopes could not be read and why "
            "before giving the ranking."
        )

    @mcp.prompt(tags={"cases", "write"})
    def draft_case_from_incident(incident_notes: str, parent: str | None = None) -> str:
        """Turn incident notes into a ready-to-submit support case (SC-002)."""
        target = parent or (
            settings.parents[0]
            if settings.parents
            else "the project the user names — call list_scopes first if none is given"
        )
        return (
            f"Here are incident notes:\n\n{incident_notes}\n\n"
            f"Draft a Google Cloud support case for {target}. First call "
            "search_case_classifications with keywords from the notes and pick the best "
            "classification id. Then propose a title, a description that leads with impact "
            "and includes timestamps in UTC, and a priority (P0 most urgent, P4 least). "
            "Show the draft and let me confirm before calling create_case."
        )
