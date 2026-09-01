"""Credentials, used exactly as the user already configured them.

The server stores nothing (FR-020): ADC covers `gcloud auth
application-default login`, service account keys, Workload Identity, and the
metadata server without any of them being handled here.

Two consumers share one credential object, and they refresh independently — the
gRPC channel manages its own lifecycle while the media REST path needs a bearer
token minted on demand. That split is the second-order consequence of the SDK
not generating the media endpoints.
"""

from __future__ import annotations

import asyncio

import google.auth
from google.auth.transport.requests import Request as AuthRequest

__all__ = ["SCOPES", "CredentialProvider"]

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


class CredentialProvider:
    """Resolves ADC once and mints bearer tokens for the media REST calls."""

    def __init__(self, quota_project: str | None = None) -> None:
        self._quota_project = quota_project
        self._credentials = None
        self._lock = asyncio.Lock()

    @property
    def quota_project(self) -> str | None:
        return self._quota_project

    def resolve(self):
        """Return the ADC credentials, resolving them on first use."""
        if self._credentials is None:
            credentials, _ = google.auth.default(scopes=list(SCOPES))
            if self._quota_project and hasattr(credentials, "with_quota_project"):
                credentials = credentials.with_quota_project(self._quota_project)
            self._credentials = credentials
        return self._credentials

    async def bearer_headers(self) -> dict[str, str]:
        """Headers for the media endpoints, refreshing the token when stale.

        google-auth's refresh is blocking, so it runs off the event loop. The lock
        keeps concurrent uploads from refreshing the same credential at once.
        """
        async with self._lock:
            credentials = self.resolve()
            if not credentials.valid:
                await asyncio.to_thread(credentials.refresh, AuthRequest())
            token = credentials.token

        headers = {"Authorization": f"Bearer {token}"}
        if self._quota_project:
            headers["x-goog-user-project"] = self._quota_project
        return headers
