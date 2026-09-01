"""The GAPIC async clients plus one HTTP client, owned by the server lifespan.

Three support clients, not four: SupportEventSubscriptionService is out of scope.
An HTTP client alongside them because attachment upload and download are HTTP
media endpoints the GAPIC generator does not cover (001 research R-002).

Two Resource Manager clients join them so a scope can be named in conversation
rather than configured in advance. They are a different API from support, but
they take the same credentials and belong to the same lifespan, so keeping them
in one bundle beats a second ownership story (002 research R-111).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from google.cloud.resourcemanager_v3.services.organizations import OrganizationsAsyncClient
from google.cloud.resourcemanager_v3.services.projects import ProjectsAsyncClient
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
    projects: ProjectsAsyncClient
    organizations: OrganizationsAsyncClient
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
        projects=ProjectsAsyncClient(credentials=creds),
        organizations=OrganizationsAsyncClient(credentials=creds),
        http=httpx.AsyncClient(base_url=SUPPORT_API_ROOT, timeout=60.0),
        credentials=credentials,
    )
