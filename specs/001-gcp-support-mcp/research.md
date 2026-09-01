# Phase 0 Research: Google Cloud Support MCP

**Feature**: `001-gcp-support-mcp` | **Date**: 2026-09-01 | **Plan**: [plan.md](./plan.md)

모든 결정은 1차 출처(설치된 SDK 휠 내부, 공식 문서, PyPI 메타데이터)에서 확인했다. 확인 방법을 각 항목에 명시한다.

---

## R-001: Google Cloud Support Python SDK — 버전과 실제 RPC 인벤토리

**Decision**: `google-cloud-support == 0.5.3`의 **비동기 GAPIC 클라이언트(gRPC asyncio)** 를 v2 안정 버전 기준으로 사용한다.

**확인 방법**: PyPI 메타데이터 조회 + 휠(`google_cloud_support-0.5.3-py3-none-any.whl`) 직접 해제 후 `gapic_metadata.json` 파싱.

`support_v2` 실제 RPC (총 20개):

| 서비스 | RPC |
|--------|-----|
| `CaseService` | `GetCase`, `ListCases`, `SearchCases`, `CreateCase`, `UpdateCase`, `EscalateCase`, `CloseCase`, `SearchCaseClassifications` (8) |
| `CommentService` | `ListComments`, `GetComment`, `CreateComment` (3) |
| `CaseAttachmentService` | `ListAttachments`, `GetAttachment` (2) |
| ~~`SupportEventSubscriptionService`~~ | 7 RPC 존재하나 **범위 밖** — spec.md Clarifications 2026-09-01 |

`support_v2beta`는 위와 동일한 20개에 `FeedService.ShowFeed` 1개를 더한다.

**범위 내 RPC는 13개다.** spec.md Clarifications(2026-09-01)가 `SupportEventSubscriptionService` 전체를 — 푸시 수신뿐 아니라 구독 리소스 CRUD까지 — 범위 밖으로 확정했다. 따라서 이 서버가 다루는 것은 `CaseService` 8 + `CommentService` 3 + `CaseAttachmentService` 2 = **13 RPC**, 여기에 R-002의 미디어 HTTP 2개를 더해 **15개 오퍼레이션**이다. GAPIC 클라이언트도 4개가 아니라 **3개**만 생성한다.

**패키지 제약** (`requires_dist`): `google-api-core[grpc]>=2.25.0`, `google-auth>=2.14.1`, `proto-plus>=1.26.1`, `protobuf>=6.33.5`, 그리고 `grpcio>=1.75.1; python_version >= "3.14"`. 프로젝트의 `requires-python = ">=3.14"`와 호환된다.

**전송 방식**: `gapic_metadata.json`은 `grpc`, `grpc-async`, `rest` 세 가지를 선언하지만, `services/*/transports/` 디렉터리 확인 결과 **비동기 전송은 `grpc_asyncio.py` 하나뿐이다**(`rest.py`/`rest_base.py`는 동기 전용). MCP 도구는 async이므로 `*AsyncClient` + gRPC asyncio를 쓴다.

**페이지네이션**: `ListCasesAsyncPager`, `SearchCasesAsyncPager`, `SearchCaseClassificationsAsyncPager` 등 async pager가 제공된다. 단 R-004의 팬아웃 때문에 pager를 그대로 노출하지 않고 원시 `page_token`을 직접 다룬다.

**Alternatives considered**: REST 직접 호출(HTTP + `httpx`) — 전 API를 손으로 매핑해야 하고 재시도·타임아웃·페이지네이션을 재구현해야 해 기각. 동기 클라이언트 + 스레드풀 — async 이벤트 루프에서 불필요한 스레드 홉이 생기고 `run_in_thread` 튜닝 부담이 늘어 기각.

---

## R-002: 첨부 파일 업로드·다운로드는 SDK에 없다 *(중요)*

**Decision**: 첨부 **메타데이터**(`ListAttachments`, `GetAttachment`)는 GAPIC 클라이언트로, 첨부 **바이트**(업로드·다운로드)는 `google-auth` 자격 증명으로 서명한 **`httpx.AsyncClient` REST 직접 호출**로 처리한다.

**Rationale**: 휠 내부 확인 결과 `CaseAttachmentService`에는 `GetAttachment`, `ListAttachments` 두 개뿐이다. `media.upload` / `media.download`는 gRPC 서비스가 아니라 HTTP 미디어 엔드포인트라서 GAPIC 생성 범위 밖에 있다. 공식 REST 문서로 확인한 엔드포인트:

**다운로드** (`media/download` 원문 확인):
- `GET https://cloudsupport.googleapis.com/v2/{name=*/*/cases/*/attachments/*}:download`
- "HTTP requests must append `?alt=media` to the URL"
- 요청 본문은 비어야 하고, 성공 시 "the response body is empty" — 즉 바이트가 본문 자리를 대신한다.

**업로드** (`media/upload` 원문 확인) — **URI가 두 개다**:
- Upload URI (미디어 업로드): `POST https://cloudsupport.googleapis.com/upload/v2/{parent=*/*/cases/*}/attachments`
- Metadata URI (메타데이터 전용): `POST https://cloudsupport.googleapis.com/v2/{parent=*/*/cases/*}/attachments`
- 요청 본문: `{"attachment": {object (Attachment)}}` — `attachment`는 필수. **파일명은 쿼리 파라미터가 아니라 이 `Attachment` 객체의 `filename`으로 전달된다.**
- 응답 본문: `Attachment` 인스턴스.

두 엔드포인트 모두 OAuth 스코프 `https://www.googleapis.com/auth/cloudsupport` 또는 `https://www.googleapis.com/auth/cloud-platform`을 요구한다.

`media` 리소스 인덱스는 "There is no persistent data associated with this resource"라고 명시한다 — 미디어는 리소스 표현을 갖지 않으며, 영속 메타데이터는 전부 `Attachment`에 있다. 데이터 모델에 `Media` 엔티티를 만들지 않는 근거다.

**다운로드 결과는 디스크에 쓰고 경로만 반환한다.** 바이트를 도구 결과로 되돌리면 FR-022(지원 데이터 노출 최소화)에 반하고 대화 맥락을 압도한다. FR-014가 "접근 가능한 위치가 반환"으로 쓰인 이유가 이것이다.

**Alternatives considered**: `google.auth.transport.requests.AuthorizedSession` — 편리하지만 **동기 블로킹**이라 async 도구에서 이벤트 루프를 막는다. 대신 `google.auth`로 토큰만 갱신해 `Authorization: Bearer` 헤더를 만들고 `httpx.AsyncClient`로 호출한다.

---

## R-003: MCP 최신 스펙과 FastMCP 4 — `ctx.elicit()`가 제거되었다 *(중요)*

**Decision**: 대상 프로토콜은 **MCP `2026-07-28`(modern era)**, 라이브러리는 **`fastmcp == 4.0.0`**. 사용자 확인(FR-016)은 FastMCP 4의 **다중 라운드 입력 패턴**(`InputRequiredResult` + `ctx.input_responses`)으로 구현하고, `2025-11-25` 이하 handshake era 연결에는 `ctx.elicit()` 분기를 둔다.

**확인 방법**: `modelcontextprotocol.io/llms.txt`에 문서 트리가 `2026-07-28`, `2025-11-25`, `2025-06-18` 순으로 존재 — 최신 리비전은 `2026-07-28`. FastMCP 4 릴리스 노트에서 제거 항목 확인.

FastMCP 4가 **제거**한 것: `ctx.sample()`, `ctx.sample_step()`, `ctx.list_roots()` (전 era), 그리고 **modern 연결에서의 `ctx.elicit()`**. modern 연결에서 `ctx.elicit()`를 호출하거나 handshake 연결에서 `InputRequiredResult`를 반환하면 era mismatch 오류가 난다. 따라서 `ctx.request_context.protocol_version` 분기가 선택이 아니라 필수다.

**확인 흐름 (FR-016 / FR-017)**:

1. 라운드 1 — 도구가 전송될 페이로드 전체를 사람이 읽을 문장으로 만들고, `InputRequiredResult`로 예/아니오를 묻는다. **페이로드 원본 자체를 `request_state`에 실어 보낸다.**
2. 라운드 2 — `ctx.input_responses[key].action`을 **먼저** 확인한다. `accept`가 아니면 아무 변경 없이 종료(FR-017). `accept`면 `request_state`에서 페이로드를 복원해 실행한다.

`request_state`는 프레임워크가 봉인(암호화·검증)하고 위조된 토큰은 도구 실행 전에 거부된다. 즉 **2라운드에서 실행되는 페이로드가 1라운드에서 사용자에게 보여준 것과 바이트 단위로 동일함이 프레임워크 수준에서 보장된다.** 관례가 아니라 메커니즘으로 FR-016/FR-017을 만족시킨다.

**클라이언트가 elicitation을 지원하지 않으면 쓰기 도구는 거부한다.** 이것은 결함이 아니라 FR-019의 형태 그대로다 — 아무 변경도 하지 않고, 왜 실행할 수 없는지 안내한다.

**`confirm: bool` 파라미터는 명시적으로 기각한다.** 그 값은 사용자가 아니라 모델이 채운다. FR-016은 *사용자*의 확인을 요구하므로 도구 파라미터로는 절대 만족시킬 수 없다.

**배포 주의**: `request_state` 서명 키는 단일 프로세스(stdio) 기본값이 프로세스별 임시 키라 충분하다. HTTP 다중 복제본 배포 시에만 `RequestStateSecurity(keys=[...])`로 32바이트 이상 공유 키가 필요하다.

---

## R-004: Cross-org 동작 — v2beta는 답이 아니다, 클라이언트 팬아웃이 답이다 *(중요)*

**Decision**: **v2 안정 버전 + 설정된 parent 목록에 대한 클라이언트 측 병렬 팬아웃 및 병합.** cross-org를 위해 v2beta를 채택하지 **않는다**.

**Rationale**: 처음에는 v2beta가 답으로 보였다. SDK docstring상 v2beta는 `parent`를 무시하고 쿼리 안에서 범위를 받는다:

```
organization="organizations/123456789"
project="projects/my-project-id" AND (priority=P0 OR priority=P1)
```

그러나 v2beta `cases.search` 공식 문서를 확인한 결과 **`OR`는 한 필드 안의 여러 값에만 적용되며(`priority=P0 OR priority=P1`), `organization` / `project`를 `OR`로 묶어 여러 조직을 한 번에 검색하는 문법은 문서화되어 있지 않다.** 범위 식별자는 필터 가능한 필드가 아니라 고정 제약으로 동작한다.

결론: **어느 API 버전을 쓰든 한 번의 호출은 하나의 parent만 조회한다.** v2beta가 주는 것은 "범위를 `parent` 대신 `query`에 쓴다"는 표기 차이뿐이며 실제 cross-org 능력이 아니다. 베타의 안정성 비용을 지불할 이유가 없다.

따라서 cross-org는 **설정된 parent 목록에 대해 동시 호출 → 병합**으로 구현한다. 이 결정이 세 가지 파생 설계를 강제한다:

### 4a. 복합 커서 (FR-007)

Google의 `page_token`은 parent별로 유효하다. 병합 결과에는 그대로 쓸 수 없다. 서버가 자체 커서를 발급한다:

```
base64url( {"v":1, "cursors": {"projects/a": "<tok>", "organizations/b": null}} )
```

`null`은 해당 parent가 소진되었음을 뜻한다. 모든 값이 `null`이면 커서를 발급하지 않는다. 커서는 불투명 문자열로만 노출하고 내부 구조를 문서화하지 않는다.

### 4b. 부분 실패가 정상 경로다 (FR-021)

parent가 N개면 그중 하나는 권한 없음, 다른 하나는 유료 지원 플랜 미가입일 수 있다. **한 parent의 403이 전체 호출을 실패시켜서는 안 된다.** 모든 목록/검색 도구는 성공한 parent의 결과와 함께, 실패한 parent별 사유를 구조화해 반환한다:

```json
{
  "cases": [...],
  "scopes_queried": ["projects/a", "organizations/b"],
  "scopes_failed": [
    {"parent": "organizations/b", "reason": "permission_denied", "detail": "...", "retryable": false}
  ],
  "next_cursor": "..."
}
```

### 4c. 요청 한도 노출이 N배가 된다

동시 호출은 rate limit에 N배로 노출된다. parent별 동시성 상한(기본 5)과 `google-api-core` 기본 재시도를 사용하고, `ResourceExhausted`는 `retryable: true`로 분류해 다른 오류와 구분한다(FR-021).

**Alternatives considered**: 도구 호출마다 사용자가 parent를 넘기게 하기 — 사용자가 자기 조직 ID를 외워야 하므로 SC-008(10분 내 첫 조회)에 반한다. 설정 목록을 기본으로 하되 도구 파라미터로 재정의 가능하게 한다. 조직 자산 검색으로 프로젝트를 자동 발견하기 — 별도 API 권한이 필요하고 범위가 폭발하므로 기각.

---

## R-005: 인증, 스코프, quota project

**Decision**: `google.auth.default()`로 ADC를 그대로 사용한다. 스코프는 `https://www.googleapis.com/auth/cloud-platform`. quota project는 설정으로 노출하고 미설정 시 진단 가능한 오류를 낸다.

**Rationale (FR-020)**: 서버는 자격 증명을 저장하지 않는다. `gcloud auth application-default login`, 서비스 계정 키, Workload Identity, GCE/Cloud Run 메타데이터 서버가 모두 자동으로 동작한다.

**IAM 역할** (공식 access-control 문서 확인):

| 역할 | 부여 가능 수준 | 용도 |
|------|----------------|------|
| `roles/cloudsupport.techSupportViewer` | 조직 / 폴더 / 프로젝트 | 읽기 전용 (P1) |
| `roles/cloudsupport.techSupportEditor` | 조직 / 폴더 / 프로젝트 | 생성·에스컬레이션·조회·목록·수정 (P2, P3) |
| `roles/cloudsupport.admin` / `viewer` | **조직 전용** | 지원 계정 관리 (케이스 접근 아님) |
| ~~Support Subscription Editor / Viewer~~ | — | 이벤트 구독 — **범위 밖이므로 요구하지 않는다** |

파생 사실 두 가지가 설계에 영향을 준다:

1. **조직 수준 케이스 조회는 `resourcemanager.organizations.get` 권한을 추가로 요구한다.** 흔한 실패 모드이므로 오류 매핑에서 별도 안내 문구를 갖는다.
2. **구독 관련 역할은 요구하지 않는다.** 이벤트 구독이 범위 밖이므로 사용자는 `techSupportViewer`/`techSupportEditor`만 있으면 된다. 이는 설치 문턱을 낮춰 SC-008(10분 내 첫 조회)에 유리하다.

**지원 플랜**: Standard / Enhanced / Premium 중 하나가 필요하다(문서 확인). 미가입 조직은 조회조차 실패하며, 권한 오류와 **구분해서** 안내해야 한다(FR-021, spec Edge Case).

**quota project**: 사용자 ADC로 조직 수준 리소스를 호출할 때 조직은 quota/billing 컨테이너가 아니므로 `x-goog-user-project`(= quota project)가 필요하다. `CLOUD_SUPPORT_MCP_QUOTA_PROJECT` 설정으로 노출하고, 미설정 상태에서 관련 오류가 나면 `gcloud auth application-default set-quota-project <ID>`를 안내한다. *구현 시 실제 조직 호출로 재확인할 것.*

---

## R-006: FastMCP 4 서버 구성 — 명시적 등록, 태그 게이팅, 미들웨어

**Decision**: 도메인별 모듈에 `register(mcp)` 함수를 두고 `server.py`에서 명시적으로 호출한다. `FileSystemProvider`는 사용하지 않는다.

**Rationale**: FastMCP 4 문서는 모듈 분할에 `FileSystemProvider("mcp/")`(디렉터리 스캔)를 제시하지만, 이 프로젝트는 `pip`/`uv`로 설치되어 임의 경로에서 실행되는 **패키지**다. 런타임 디렉터리 스캔은 설치 환경에서 경로가 어긋나기 쉽고, 정적 분석·테스트·임포트 오류 추적이 모두 어려워진다. 명시적 등록은 동일한 모듈 분리 효과를 주면서 결정적이다.

**FR-018 구현 수단 = 태그 + 가시성 API**. 모든 도구에 도메인 태그(`cases`/`comments`/`attachments`/`classifications`), 모드 태그(`read`/`write`), 위험 태그(`destructive`/`escalation`)를 붙인다. 서버 기동 시 설정에 따라 `mcp.disable(tags={...})`를 호출한다. 기본값: `escalation` 비활성, 나머지 쓰기 활성(FR-018 개정 문구와 일치).

**FR-016 보조 신호 = `ToolAnnotations`**. 8개 읽기 도구에 `readOnlyHint=True`, `close_case`·`escalate_case`에 `destructiveHint=True`, `get_*`류에 `idempotentHint=True`, 전체에 `openWorldHint=True`. 클라이언트 UI가 확인 프롬프트를 띄우는 근거가 되며 토큰 비용이 없다.

**미들웨어 스택** (순서대로):
1. `ErrorHandlingMiddleware` — 미처리 예외 포착
2. 커스텀 `RedactionMiddleware` — **FR-022**: 로그·진단 출력에서 케이스 본문·코멘트·첨부 파일명을 제거. 기본 미들웨어만으로는 부족해 직접 만든다.
3. `TimingMiddleware`, `LoggingMiddleware` — 구조화 로깅(내용이 아니라 도구 이름·소요 시간·결과 종류만)
4. `RateLimitingMiddleware` — 팬아웃이 상류 한도를 때리기 전에 자체 제한

`mask_error_details=True`로 설정해 **`ToolError`만 클라이언트에 도달**하게 한다. 즉 R-007의 오류 매핑을 통과하지 않은 예외는 절대 내부 세부사항을 흘리지 않는다.

**리소스와 프롬프트도 제공한다** (MCP 모범 사례: 데이터는 리소스, 행위는 도구):
- 리소스 템플릿 `case://{parent}/{case_id}` — 케이스를 주소 지정 가능한 읽기 전용 맥락으로 노출
- 프롬프트 `triage_open_cases`, `draft_case_from_incident` — SC-002(3분 내 케이스 제출)를 직접 겨냥

**Alternatives considered**: `mount()`로 도메인별 하위 서버 합성 — 네임스페이스 접두사(`cases_get_case`)가 붙어 도구 이름이 장황해지고, 단일 배포 단위에서 얻는 이득이 없어 기각.

---

## R-007: 오류 매핑 (FR-021)

**Decision**: `google.api_core.exceptions`를 단일 매핑 테이블로 사용자 언어 `ToolError`로 변환하고, 각 오류에 `retryable` 플래그와 다음 조치를 붙인다.

| 예외 | 분류 | 사용자에게 알릴 다음 조치 | retryable |
|------|------|---------------------------|-----------|
| `PermissionDenied` + API 미활성 시그니처 | **API 미활성** | `gcloud services enable cloudsupport.googleapis.com` — 권한 문제가 아님을 명시 | false |
| `PermissionDenied` (403) | 권한 부족 | 필요한 역할(`techSupportViewer`/`Editor`)과 부여 수준 안내 | false |
| `FailedPrecondition` + 자격 시그니처 (**400**) | **플랜 미가입** | Standard 이상 지원 플랜 필요 안내 | false |
| `Unauthenticated` (401) | 자격 증명 없음/만료 | `gcloud auth application-default login` 안내 | false |
| `NotFound` (404) | 대상 없음 | 케이스 이름 형식과 parent 확인 안내 | false |
| `InvalidArgument` (400) | 입력 오류 | 어떤 필드가 왜 잘못됐는지 | false |
| `FailedPrecondition` (그 외) | 상태 충돌 (이미 종료된 케이스 등) | 현재 상태 안내 | false |
| `ResourceExhausted` (429) | 요청 한도 | 잠시 후 재시도 | **true** |
| `ServiceUnavailable` / `DeadlineExceeded` | 일시 장애 | 재시도 | **true** |
| 그 밖의 모든 예외 | **미분류(`unknown`)** | 무엇을 시도해야 하는지 담은 **기본 안내** — 빈 문구나 원본 예외 문자열이 아니다 | false |

마지막 행이 spec.md Clarifications(2026-09-01)로 추가된 요구다. FR-021과 SC-006이 이제 **전수 기준**이다 — 위 표의 모든 분류에 더해 어느 분류에도 걸리지 않은 실패까지, 예외 없이 다음 조치를 담은 안내를 반환해야 한다. 95% 같은 비율 기준이 아니므로 계약 테스트로 전수 검증한다.

**403이 세 갈래라는 것이 이 표의 핵심이다.** 2026-09-01 실 API 호출로 확인했다 — Google은 **API가 활성화되지 않은 프로젝트에도 403을 돌려주며**, 메시지는 `Google Cloud Support API has not been used in project X before or it is disabled.`이다.

| 403의 원인 | 사용자가 할 일 |
|-----------|----------------|
| API 미활성 | `gcloud services enable cloudsupport.googleapis.com` |
| 권한 부족 | `techSupportViewer`/`Editor` 역할 부여 |
| 지원 플랜 미가입 | Standard 이상 지원 계약 구매 |

셋을 뭉뚱그리면 API가 꺼진 사용자에게 "역할을 부여하라"고 말하게 된다 — 완전히 다른 길이다. 그래서 API 미활성을 **가장 먼저** 검사하고, 그다음 플랜 시그니처, 마지막으로 권한으로 폴백한다. 폴백 문구는 권한과 지원 플랜 두 가능성을 모두 짚는다.

이 항목은 계획 단계에 없었다. 실 호출이 찾아냈다.

**그리고 플랜 미가입은 403이 아니었다.** 같은 날 실 호출에서 확인했다 — 지원 플랜이 없는 프로젝트에 케이스를 만들면 **`FailedPrecondition`(400)** 이 오고 메시지는 `You are not eligible to create a case with this channel.`이다. 계획은 이것을 403으로 가정했다.

영향이 컸다: 이 분기가 없으면 사용자는 `failed_precondition`의 기본 안내인 *"이미 종료된 케이스일 수 있으니 get_case로 상태를 확인하라"* 를 받는다. 케이스를 **만들려는** 사람에게는 의미가 없는 말이다. 그래서 `FailedPrecondition`도 자격 시그니처를 먼저 검사하고, 걸리지 않을 때만 상태 충돌로 읽는다.

읽기는 되는데 생성만 막히므로, 이 오류는 **조회를 다 해본 뒤에야** 나타난다.

**팬아웃에서는 이 분류가 호출 전체가 아니라 parent별로 적용된다** (R-004b).

### 두 번째 오류 원천: 미디어 REST 경로

R-002의 SDK/REST 간극 때문에 이 서버는 트랜스포트가 둘이고, 따라서 **예외 타입도 둘**이다. gRPC 경로는 `google.api_core.exceptions`를, 미디어 경로는 `httpx.HTTPStatusError`를 던진다. 매핑 테이블은 **두 원천을 같은 `ErrorKind`로 정규화**해야 하며, 그렇지 않으면 FR-021이 첨부 업로드·다운로드에서만 조용히 깨진다.

| HTTP 상태 | 대응 `ErrorKind` | api_core 대응물 |
|-----------|------------------|-----------------|
| 401 | `unauthenticated` | `Unauthenticated` |
| 403 | `permission_denied` 또는 `support_plan_required` | `PermissionDenied` (본문 시그니처로 분기, gRPC와 동일 규칙) |
| 404 | `not_found` | `NotFound` |
| 400 | `invalid_argument` | `InvalidArgument` |
| 429 | `rate_limited` (retryable) | `ResourceExhausted` |
| 503 / 504 / 타임아웃 | `unavailable` (retryable) | `ServiceUnavailable` / `DeadlineExceeded` |

`errors.py`는 두 개의 진입 함수(`from_grpc(exc)`, `from_http(exc)`)를 노출하고 **동일한 `ErrorKind`와 안내 문구를 반환한다.** 사용자는 첨부 파일 오류인지 케이스 조회 오류인지에 따라 다른 형식의 안내를 받아서는 안 된다. Unit 테스트가 두 경로의 같은 상태 코드가 같은 `ErrorKind`와 같은 안내를 내는지 검증한다.

---

## R-008: 케이스 데이터 모델 — enum과 콘솔 링크

**확인 방법**: 휠 내부 `google/cloud/support_v2/types/case.py` 직접 확인.

`Case.State`: `STATE_UNSPECIFIED`, `NEW`, `IN_PROGRESS_GOOGLE_SUPPORT`, `ACTION_REQUIRED`, `SOLUTION_PROVIDED`, `CLOSED`
`Case.Priority`: `PRIORITY_UNSPECIFIED`, `P0`(가장 긴급) ~ `P4`

`Case` 필드: `name`, `display_name`, `description`, `classification`, `time_zone`, `subscriber_email_addresses`, `state`, `create_time`, `update_time`, `creator`, `contact_email`, `escalated`, `test_case`, `language_code`, `priority`.

**주의**: 검색 쿼리 문법의 `state`는 `OPEN` 또는 `CLOSED` 두 값만 받지만, `Case.state` 응답은 위 5개 값을 갖는다. 즉 **쿼리 어휘와 응답 어휘가 다르다.** 도구 입력은 `OPEN`/`CLOSED`로 받고 응답은 실제 state를 그대로 노출하며, 이 차이를 도구 설명에 명시한다.

`test_case` 필드가 있으므로 통합 테스트는 실제 지원 티켓을 만들지 않고 테스트 케이스로 수행할 수 있다.

**콘솔 링크 (FR-023)**: `name`이 `projects/{p}/cases/{id}`이면 `https://console.cloud.google.com/support/cases/detail/{id}?project={p}`, `organizations/{o}/cases/{id}`이면 `.../detail/{id}?organizationId={o}`. 파싱한 `parent`·`case_id`와 함께 구조화 출력에 포함한다.

---

## R-009: 테스트 전략

**Decision**: `pytest` + `pytest-asyncio`, 3계층.

1. **Unit** — 오류 매핑 표, 복합 커서 인코딩/디코딩(라운드트립 및 위조 입력), 콘솔 URL 생성, proto→pydantic 직렬화. 네트워크 없음.
2. **Contract** — FastMCP 인메모리 `Client(mcp)`로 도구 목록·입력/출력 스키마·`annotations`·태그 게이팅을 검증하고, GAPIC 클라이언트는 목으로 대체. **확인 흐름 2라운드**(라운드1이 `InputRequiredResult` 반환, `decline` 시 상류 호출 0회 — FR-017)와 **팬아웃 부분 실패**(한 parent가 403이어도 나머지 결과 반환)가 여기 핵심이다.
3. **Integration** — 실제 프로젝트 대상. `CLOUD_SUPPORT_MCP_IT_PARENT` 환경변수가 있을 때만 실행되며 기본 skip. 쓰기 검증은 `test_case=True`로 한정한다.

**Alternatives considered**: 실제 gRPC를 VCR로 녹화 — 지원 케이스 본문에 고객 데이터가 섞일 위험이 있어(FR-022) 기각. 목 + 계약 테스트로 충분하다.

---

## R-010: 신규 의존성 deprecated 표면 점검 (헌법 원칙 V)

**확인 시점**: 2026-09-01 | **확인 방법**: 설치본(`uv sync` 후)에서 직접 임포트해 `DeprecationWarning` 포착 + 패키지 소스에서 해당 심볼 주변의 deprecated 마킹 검색.

| 패키지 | 핀 | 사용 예정 표면 | 결과 |
|--------|-----|----------------|------|
| `httpx` | 0.28.1 | `AsyncClient`, `HTTPStatusError` | deprecated 없음 |
| `pydantic-settings` | 2.15.0 | `BaseSettings`, `SettingsConfigDict` | deprecated 없음 |
| `respx` | 0.23.1 | `mock` | deprecated 없음 |
| `pytest` | 9.1.1 | `mark.skipif`, `fixture`, `raises` | deprecated 없음 |
| `pytest-asyncio` | 1.4.0 | `asyncio_mode = "auto"` | deprecated 없음 |
| `ruff` | 0.16.5 | CLI 전용 | 해당 없음 |

**주의 하나**: `pytest-asyncio 1.x`는 `event_loop` 픽스처를 **제거**했다(설치본에서 부재 확인). 이 프로젝트는 `asyncio_mode = "auto"`만 쓰므로 영향이 없지만, 예전 예제를 복사하면 즉시 깨진다.

**런타임 환경 확인**: Python 3.14.7, `grpcio 1.83.1`(cp314 휠 정상 설치 — R-001의 예측 확인).

---

## 미해결 항목 (구현 중 확인)

구현 시점(2026-09-01) 갱신. **네 항목 모두 실 API 호출이 있어야 확정되며, 이번 구현에서는 자격 증명이 없어 해소하지 못했다.** 넷 다 설계를 바꾸지 않으며 설정 기본값이나 오류 문구만 조정된다.

| # | 항목 | 현재 상태 | 구현에 반영된 것 |
|---|------|-----------|------------------|
| 1 | quota project 실제 필요 조건 | **부분 해소** (2026-09-01 실 호출) — 프로젝트 스코프에서는 **불필요**했다. ADC 파일의 `quota_project_id`를 google-auth가 자동으로 쓰기 때문이다. 조직 스코프는 접근 가능한 조직이 없어 미확인 | `CLOUD_SUPPORT_MCP_QUOTA_PROJECT` 설정이 있고, `auth.py`가 `with_quota_project()`와 `x-goog-user-project` 헤더를 모두 적용한다. 필요 여부와 무관하게 동작한다 |
| 2 | 지원 플랜 미가입의 메시지 시그니처 | **해소** (2026-09-01 실 호출) — 403이 아니라 **`FailedPrecondition`(400) + `not eligible ... with this channel`** 이었다. 덤으로 403의 세 번째 원인(API 미활성)도 발견해 분류를 추가했다 | `errors.py`가 `support plan`·`support account`·`not entitled`·`no entitlement` 네 시그니처로 분기하고, **매칭 실패 시 `permission_denied`로 폴백하되 그 안내문이 지원 플랜 확인도 함께 지시한다.** 시그니처가 틀려도 사용자는 두 가능성을 모두 안내받는다 |
| 3 | 첨부 업로드 크기 상한 | **미해소** — 실측하려면 케이스가 필요한데, 검증 프로젝트가 지원 플랜 미가입이라 생성이 막힌다 | `MAX_UPLOAD_BYTES` 기본 10MB로 사전 검증. 서버가 더 큰 값을 허용하면 설정으로 올리면 되고, 거부하면 그 오류가 정규화되어 전달된다 |
| 4 | 업로드 `uploadType` | **미해소** — 항목 3과 같은 이유. `?uploadType=multipart`로 구현했으나 실 호출 미검증 | `media.py`가 `?uploadType=multipart` + 멀티파트 본문(메타데이터 JSON + 파일)으로 구현. 실패 시 Metadata URI 선행 생성 폴백을 검토한다 |

**항목 2에 대한 설계 판단**: 시그니처 목록이 틀릴 가능성이 있으므로, 폴백 안내문 자체가 두 원인을 모두 짚도록 썼다. 즉 분류가 어긋나도 사용자는 막히지 않는다. 이것이 미해소 상태에서도 SC-006(전수 기준)을 만족시키는 방식이다.
