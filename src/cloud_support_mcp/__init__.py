"""MCP server for Google Cloud Support."""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    from .server import create_server

    create_server().run()
