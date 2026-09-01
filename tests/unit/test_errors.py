"""errors.py — 두 트랜스포트의 오류를 하나의 ErrorKind로 정규화한다 (research.md R-007).

핵심 불변 조건 둘:
  1. 같은 상태 코드는 gRPC 경로와 HTTP 경로에서 같은 결과를 낸다.
  2. 어느 분류에도 걸리지 않은 실패도 조치 안내를 담는다 (FR-021, SC-006 전수 기준).
"""

import httpx
import pytest
from google.api_core import exceptions as gexc

from google_cloud_support_mcp.errors import ErrorKind, from_grpc, from_http, to_tool_error

PLAN_403 = "The caller does not have a Google Cloud support plan for this resource."
PERM_403 = "Permission 'cloudsupport.cases.list' denied on resource."
# Observed verbatim from a live 403 on 2026-09-01.
DISABLED_403 = (
    "Google Cloud Support API has not been used in project kktae-demo before or it is "
    "disabled. Enable it by visiting https://console.developers.google.com/apis/api/"
    "cloudsupport.googleapis.com/overview?project=kktae-demo then retry."
)


def _http(status: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://cloudsupport.googleapis.com/v2/x")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


class TestGrpcClassification:
    def test_permission_denied(self):
        info = from_grpc(gexc.PermissionDenied(PERM_403))
        assert info.kind is ErrorKind.PERMISSION_DENIED
        assert info.retryable is False

    def test_support_plan_is_distinguished_from_permission(self):
        """둘 다 403이지만 사용자가 할 일이 전혀 다르다 — 역할 부여 vs 지원 계약 구매."""
        plan = from_grpc(gexc.PermissionDenied(PLAN_403))
        perm = from_grpc(gexc.PermissionDenied(PERM_403))
        assert plan.kind is ErrorKind.SUPPORT_PLAN_REQUIRED
        assert perm.kind is ErrorKind.PERMISSION_DENIED
        assert plan.detail != perm.detail

    def test_api_not_enabled_is_not_read_as_a_permission_problem(self):
        """A live 403 that says the API is disabled must not tell the user to grant roles."""
        info = from_grpc(gexc.PermissionDenied(DISABLED_403))
        assert info.kind is ErrorKind.API_NOT_ENABLED
        assert "gcloud services enable" in info.detail
        assert "roles/" not in info.detail

    @pytest.mark.parametrize(
        ("exc", "kind", "retryable"),
        [
            (gexc.Unauthenticated("no creds"), ErrorKind.UNAUTHENTICATED, False),
            (gexc.NotFound("nope"), ErrorKind.NOT_FOUND, False),
            (gexc.InvalidArgument("bad"), ErrorKind.INVALID_ARGUMENT, False),
            (gexc.FailedPrecondition("state"), ErrorKind.FAILED_PRECONDITION, False),
            (gexc.ResourceExhausted("slow down"), ErrorKind.RATE_LIMITED, True),
            (gexc.ServiceUnavailable("down"), ErrorKind.UNAVAILABLE, True),
            (
                gexc.InternalServerError("500 Internal error encountered."),
                ErrorKind.UNAVAILABLE,
                True,
            ),
            (gexc.DeadlineExceeded("slow"), ErrorKind.UNAVAILABLE, True),
        ],
    )
    def test_mapping_table(self, exc, kind, retryable):
        info = from_grpc(exc)
        assert info.kind is kind
        assert info.retryable is retryable


class TestSupportPlanBlocker:
    """Observed live on 2026-09-01: creating a case without a plan returns 400, not 403."""

    ELIGIBILITY_400 = "400 You are not eligible to create a case with this channel."

    def test_failed_precondition_eligibility_is_a_plan_problem(self):
        info = from_grpc(gexc.FailedPrecondition(self.ELIGIBILITY_400))
        assert info.kind is ErrorKind.SUPPORT_PLAN_REQUIRED
        assert "support plan" in info.detail.lower()

    def test_a_genuine_state_conflict_still_reads_as_one(self):
        info = from_grpc(gexc.FailedPrecondition("case already closed"))
        assert info.kind is ErrorKind.FAILED_PRECONDITION

    def test_the_same_body_over_http_classifies_identically(self):
        assert (
            from_http(_http(400, self.ELIGIBILITY_400)).kind
            is from_grpc(gexc.FailedPrecondition(self.ELIGIBILITY_400)).kind
        )


class TestUnknownFallback:
    """FR-021 + SC-006 전수 기준: 미분류 실패도 다음 조치를 담아야 한다."""

    def test_unmapped_grpc_exception_is_unknown_with_guidance(self):
        info = from_grpc(RuntimeError("something nobody mapped"))
        assert info.kind is ErrorKind.UNKNOWN
        assert info.detail.strip(), "unknown 의 detail 이 비어 있으면 SC-006 미달"
        assert "something nobody mapped" not in info.detail, (
            "원본 예외 문자열을 그대로 옮기는 것은 '다음 조치 안내'가 아니다"
        )

    def test_unmapped_http_status_is_unknown_with_guidance(self):
        info = from_http(_http(418, "teapot"))
        assert info.kind is ErrorKind.UNKNOWN
        assert info.detail.strip()


class TestTransportParity:
    """계약 체크리스트 14: 같은 상태 코드 → 같은 ErrorKind·같은 안내·같은 retryable."""

    @pytest.mark.parametrize(
        ("status", "body", "grpc_exc"),
        [
            (401, "", gexc.Unauthenticated("x")),
            (403, PERM_403, gexc.PermissionDenied(PERM_403)),
            (403, PLAN_403, gexc.PermissionDenied(PLAN_403)),
            (403, DISABLED_403, gexc.PermissionDenied(DISABLED_403)),
            (404, "", gexc.NotFound("x")),
            (400, "", gexc.InvalidArgument("x")),
            (429, "", gexc.ResourceExhausted("x")),
            (500, "", gexc.InternalServerError("x")),
            (503, "", gexc.ServiceUnavailable("x")),
            (504, "", gexc.GatewayTimeout("x")),
        ],
    )
    def test_same_status_same_result(self, status, body, grpc_exc):
        h, g = from_http(_http(status, body)), from_grpc(grpc_exc)
        assert h.kind is g.kind
        assert h.detail == g.detail
        assert h.retryable == g.retryable


def test_to_tool_error_carries_kind_and_detail():
    err = to_tool_error(from_grpc(gexc.NotFound("x")))
    assert "not_found" in str(err) or "찾" in str(err) or "not found" in str(err).lower()
    assert str(err).strip()
