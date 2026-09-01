"""Fixtures: mocked GAPIC clients and an in-memory MCP client.

Nothing here touches the network. The three GAPIC services are replaced with
simple async fakes so contract tests can assert on call counts — which is how
FR-017 ("declining sends nothing") is actually verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from google.cloud.support_v2.types import actor, attachment, case, comment
from google.protobuf import timestamp_pb2

from google_cloud_support_mcp.clients import SupportClients
from google_cloud_support_mcp.settings import Settings

TS = timestamp_pb2.Timestamp(seconds=1_800_000_000)


def make_case(name: str = "projects/p/cases/1", **overrides: Any) -> case.Case:
    defaults: dict[str, Any] = {
        "name": name,
        "display_name": "Disk pressure",
        "description": "Nodes report DiskPressure.",
        "classification": case.CaseClassification(id="100H", display_name="Compute/GKE"),
        "state": case.Case.State.NEW,
        "priority": case.Case.Priority.P2,
        "create_time": TS,
        "update_time": TS,
        "creator": actor.Actor(display_name="Ops", email="ops@example.com"),
    }
    defaults.update(overrides)
    return case.Case(**defaults)


def make_comment(name: str = "projects/p/cases/1/comments/1", **o: Any) -> comment.Comment:
    d: dict[str, Any] = {
        "name": name,
        "body": "Investigating.",
        "create_time": TS,
        "creator": actor.Actor(display_name="Support", google_support=True),
    }
    d.update(o)
    return comment.Comment(**d)


def make_attachment(
    name: str = "projects/p/cases/1/attachments/1", **o: Any
) -> attachment.Attachment:
    d: dict[str, Any] = {
        "name": name,
        "filename": "diag.log",
        "mime_type": "text/plain",
        "size_bytes": 12,
        "create_time": TS,
    }
    d.update(o)
    return attachment.Attachment(**d)


@dataclass
class _Page:
    """Stand-in for a GAPIC list response.

    Field names mirror the real responses (verified against the 0.5.3 wheel):
    SearchCasesResponse.cases, ListCommentsResponse.comments,
    ListAttachmentsResponse.attachments, SearchCaseClassificationsResponse.case_classifications.
    """

    cases: list[Any] = field(default_factory=list)
    comments: list[Any] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)
    case_classifications: list[Any] = field(default_factory=list)
    projects: list[Any] = field(default_factory=list)
    organizations: list[Any] = field(default_factory=list)
    next_page_token: str = ""


@dataclass
class FakeCaseService:
    cases: list[case.Case] = field(default_factory=lambda: [make_case()])
    classifications: list[case.CaseClassification] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    search_error: BaseException | None = None
    errors_by_parent: dict[str, BaseException] = field(default_factory=dict)

    async def search_cases(self, request=None, **kw):
        self.calls.append(("search_cases", request))
        parent = getattr(request, "parent", "") or ""
        if parent in self.errors_by_parent:
            raise self.errors_by_parent[parent]
        if self.search_error is not None:
            raise self.search_error
        return _Page(cases=list(self.cases))

    async def get_case(self, request=None, **kw):
        self.calls.append(("get_case", request))
        return self.cases[0]

    async def search_case_classifications(self, request=None, **kw):
        self.calls.append(("search_case_classifications", request))
        return _Page(case_classifications=list(self.classifications))

    async def create_case(self, request=None, **kw):
        self.calls.append(("create_case", request))
        return self.cases[0]

    async def update_case(self, request=None, **kw):
        self.calls.append(("update_case", request))
        return self.cases[0]

    async def close_case(self, request=None, **kw):
        self.calls.append(("close_case", request))
        return self.cases[0]

    async def escalate_case(self, request=None, **kw):
        self.calls.append(("escalate_case", request))
        return self.cases[0]


@dataclass
class FakeScope:
    """Shape-compatible with resourcemanager_v3 Project / Organization.

    `project_id` is what tells the serializer which class it is, and `name` is
    deliberately a project *number* so a serializer that reaches for the wrong
    field is caught rather than accidentally right.
    """

    project_id: str = ""
    name: str = ""
    display_name: str = ""
    state: Any = field(default_factory=lambda: _FakeEnumValue("ACTIVE"))


class _FakeEnumValue:
    def __init__(self, name: str) -> None:
        self.name = name


def make_project(pid: str, display_name: str | None = None) -> FakeScope:
    return FakeScope(
        project_id=pid,
        name=f"projects/{abs(hash(pid)) % 10**12:012d}",
        display_name=display_name if display_name is not None else pid.replace("-", " ").title(),
    )


def make_org(number: str, display_name: str) -> FakeScope:
    return FakeScope(name=f"organizations/{number}", display_name=display_name)


@dataclass
class _FakePagedService:
    """Base for the two Resource Manager fakes.

    Pages on purpose. A single-page fake would let a paging bug pass every test:
    the tool could ignore `next_page_token` entirely and still return everything
    the fake had. `page_items` sets how many are handed back per call, so a test
    can put a match on page two without building a hundred rows.
    """

    items: list[FakeScope] = field(default_factory=list)
    page_items: int = 2
    error: BaseException | None = None
    calls: list[Any] = field(default_factory=list)

    def _page(self, request):
        if self.error is not None:
            raise self.error
        start = int(request.page_token) if getattr(request, "page_token", "") else 0
        # The real service honours page_size and may return fewer. Modelling only
        # the second half would let a caller ask for 5 and quietly receive 100,
        # which is exactly the bug this fake is used to catch.
        requested = getattr(request, "page_size", 0) or self.page_items
        size = min(self.page_items, requested)
        chunk = self.items[start : start + size]
        nxt = start + size
        return chunk, (str(nxt) if nxt < len(self.items) else "")


@dataclass
class FakeProjectsService(_FakePagedService):
    async def search_projects(self, request=None, **kw):
        self.calls.append(("search_projects", request))
        chunk, token = self._page(request)
        return _Page(projects=list(chunk), next_page_token=token)


@dataclass
class FakeOrganizationsService(_FakePagedService):
    async def search_organizations(self, request=None, **kw):
        self.calls.append(("search_organizations", request))
        chunk, token = self._page(request)
        return _Page(organizations=list(chunk), next_page_token=token)


@dataclass
class FakeCommentService:
    comments: list[comment.Comment] = field(default_factory=lambda: [make_comment()])
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def list_comments(self, request=None, **kw):
        self.calls.append(("list_comments", request))
        return _Page(comments=list(self.comments))

    async def get_comment(self, request=None, **kw):
        self.calls.append(("get_comment", request))
        return self.comments[0]

    async def create_comment(self, request=None, **kw):
        self.calls.append(("create_comment", request))
        return self.comments[0]


@dataclass
class FakeAttachmentService:
    attachments: list[attachment.Attachment] = field(default_factory=lambda: [make_attachment()])
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def list_attachments(self, request=None, **kw):
        self.calls.append(("list_attachments", request))
        return _Page(attachments=list(self.attachments))

    async def get_attachment(self, request=None, **kw):
        self.calls.append(("get_attachment", request))
        return self.attachments[0]


class FakeCredentials:
    """Stands in for CredentialProvider on the media path — no network, no ADC."""

    quota_project = "p"

    async def bearer_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer fake-token", "x-goog-user-project": "p"}


@pytest.fixture
def fake_clients() -> SupportClients:
    return SupportClients(
        cases=FakeCaseService(),
        comments=FakeCommentService(),
        attachments=FakeAttachmentService(),
        projects=FakeProjectsService(
            items=[make_project("my-billing-project"), make_project("other-proj")]
        ),
        organizations=FakeOrganizationsService(items=[make_org("123456789", "acme.example")]),
        http=httpx.AsyncClient(base_url="https://cloudsupport.googleapis.com"),
        credentials=FakeCredentials(),
    )


@pytest.fixture(autouse=True)
def _reset_classification_cache():
    """The catalogue is cached per process; tests must not inherit each other's."""
    from google_cloud_support_mcp.tools import classifications

    classifications._catalog_cache = None
    yield
    classifications._catalog_cache = None


@pytest.fixture
def settings() -> Settings:
    return Settings(parents=["projects/p"], quota_project="p")


@pytest.fixture
def make_server(fake_clients):
    """Build a server with mocks; override settings per test."""
    from google_cloud_support_mcp.server import build_server

    def _build(**overrides):
        return build_server(
            Settings(**{"parents": ["projects/p"], **overrides}), clients=fake_clients
        )

    return _build


@pytest.fixture
def mcp_server(make_server):
    return make_server()
