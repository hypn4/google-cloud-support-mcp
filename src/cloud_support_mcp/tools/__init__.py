"""Explicit registration of every domain module."""

from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP

from ..clients import SupportClients
from ..settings import Settings

__all__ = ["register_all"]

GetClients = Callable[[], SupportClients]


def register_all(mcp: FastMCP, settings: Settings, get_clients: GetClients) -> None:
    from . import attachments, cases, classifications, comments

    cases.register(mcp, settings, get_clients)
    classifications.register(mcp, settings, get_clients)
    comments.register(mcp, settings, get_clients)
    attachments.register(mcp, settings, get_clients)
