"""The three GAPIC async clients plus one HTTP client, owned by the server lifespan.

Three, not four: SupportEventSubscriptionService is out of scope. And an HTTP
client alongside them because attachment upload and download are HTTP media
endpoints that the GAPIC generator does not cover (research.md R-002).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from google.cloud.support_v2.services.case_attachment_service import (
    CaseAttachmentServiceAsyncClient,
)
from google.cloud.support_v2.services.case_service import CaseServiceAsyncClient
from google.cloud.support_v2.services.comment_service import CommentServiceAsyncClient

from .auth import CredentialProvider

__all__ = ["SupportClients", "build_clients"]

SUPPORT_API_ROOT = "https://cloudsupport.googleapis.com"


@dataclass(slots=True)
class SupportClients:
    """One bundle constructed per server process, never per call."""

    cases: CaseServiceAsyncClient
    comments: CommentServiceAsyncClient
    attachments: CaseAttachmentServiceAsyncClient
    http: httpx.AsyncClient
    credentials: CredentialProvider

    async def aclose(self) -> None:
        await self.http.aclose()


def build_clients(credentials: CredentialProvider) -> SupportClients:
    creds = credentials.resolve()
    return SupportClients(
        cases=CaseServiceAsyncClient(credentials=creds),
        comments=CommentServiceAsyncClient(credentials=creds),
        attachments=CaseAttachmentServiceAsyncClient(credentials=creds),
        http=httpx.AsyncClient(base_url=SUPPORT_API_ROOT, timeout=60.0),
        credentials=credentials,
    )
