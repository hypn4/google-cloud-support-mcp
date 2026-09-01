"""serializers.py — proto in, declared model out. Nothing raw reaches a client."""

from google.cloud.support_v2.types import actor, attachment, case, comment
from google.protobuf import timestamp_pb2

from google_cloud_support_mcp.models import CasePriority, CaseState
from google_cloud_support_mcp.serializers import (
    parse_resource_ref,
    to_attachment,
    to_case_detail,
    to_case_summary,
    to_classification,
    to_comment,
)

TS = timestamp_pb2.Timestamp(seconds=1_800_000_000)


class TestResourceRef:
    def test_project_case(self):
        ref = parse_resource_ref("projects/my-proj/cases/123456")
        assert ref.parent == "projects/my-proj"
        assert ref.parent_type == "project"
        assert ref.case_id == "123456"
        assert ref.console_url == (
            "https://console.cloud.google.com/support/cases/detail/123456?project=my-proj"
        )

    def test_organization_case(self):
        ref = parse_resource_ref("organizations/987/cases/42")
        assert ref.parent_type == "organization"
        assert ref.console_url == (
            "https://console.cloud.google.com/support/cases/detail/42?organizationId=987"
        )

    def test_unparseable_name_keeps_name_and_drops_url(self):
        """FR-023: a link that cannot be built must not fail the lookup itself."""
        ref = parse_resource_ref("something/entirely/unexpected")
        assert ref.name == "something/entirely/unexpected"
        assert ref.console_url is None
        assert ref.parent_type is None


class TestCase:
    def _proto(self) -> case.Case:
        return case.Case(
            name="projects/p/cases/1",
            display_name="Disk pressure on node pool",
            description="Nodes report DiskPressure since 02:00 UTC.",
            classification=case.CaseClassification(id="100H", display_name="Compute/GKE"),
            state=case.Case.State.ACTION_REQUIRED,
            priority=case.Case.Priority.P1,
            escalated=True,
            test_case=True,
            create_time=TS,
            update_time=TS,
            creator=actor.Actor(display_name="Ops", email="ops@example.com"),
            contact_email="oncall@example.com",
            subscriber_email_addresses=["a@example.com"],
            time_zone="+09:00",
            language_code="en",
        )

    def test_summary_converts_enums_to_names(self):
        s = to_case_summary(self._proto())
        assert s.state is CaseState.ACTION_REQUIRED
        assert s.priority is CasePriority.P1
        assert s.escalated is True
        assert s.test_case is True
        assert s.classification == "Compute/GKE"

    def test_summary_omits_description(self):
        """A 20-item list carrying full bodies drowns the conversation."""
        assert "description" not in to_case_summary(self._proto()).model_dump()

    def test_timestamps_become_iso8601(self):
        s = to_case_summary(self._proto())
        assert s.create_time is not None
        assert s.create_time.startswith("20") and "T" in s.create_time

    def test_detail_carries_description_and_classification_id(self):
        d = to_case_detail(self._proto())
        assert d.description.startswith("Nodes report DiskPressure")
        assert d.classification_id == "100H"
        assert d.subscriber_emails == ["a@example.com"]
        assert d.ref.console_url is not None


class TestComment:
    def test_google_support_author_is_labelled(self):
        c = to_comment(
            comment.Comment(
                name="projects/p/cases/1/comments/9",
                body="We are investigating.",
                create_time=TS,
                creator=actor.Actor(display_name="Support", google_support=True),
            )
        )
        assert c.author_side == "google_support"
        assert c.body == "We are investigating."

    def test_customer_author_is_labelled(self):
        c = to_comment(
            comment.Comment(
                name="projects/p/cases/1/comments/8",
                body="Adding logs.",
                creator=actor.Actor(display_name="Ops", email="ops@example.com"),
            )
        )
        assert c.author_side == "customer"

    def test_deprecated_plain_text_body_is_never_used(self):
        """The proto marks plain_text_body 'Output only. DEPRECATED. DO NOT USE.'"""
        c = to_comment(
            comment.Comment(name="n", body="real body", plain_text_body="deprecated copy")
        )
        assert c.body == "real body"
        assert "deprecated copy" not in c.model_dump_json()


def test_attachment_carries_no_bytes():
    a = to_attachment(
        attachment.Attachment(
            name="projects/p/cases/1/attachments/7",
            filename="diag.log",
            mime_type="text/plain",
            size_bytes=2048,
            create_time=TS,
            creator=actor.Actor(display_name="Support", google_support=True),
        )
    )
    assert a.size_bytes == 2048
    dumped = a.model_dump()
    assert not any(isinstance(v, bytes) for v in dumped.values())
    assert "body" not in dumped and "content" not in dumped


def test_classification():
    c = to_classification(case.CaseClassification(id="100H", display_name="Compute/GKE"))
    assert c.id == "100H"
