---

description: "Task list for Google Cloud Support MCP implementation"
---

# Tasks: Google Cloud Support MCP

**Input**: Design documents from `/specs/001-gcp-support-mcp/`

**Prerequisites**: [plan.md](./plan.md) (rev. 2), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/tools.md](./contracts/tools.md), [quickstart.md](./quickstart.md)

**Tests**: 테스트 과제를 **포함한다.** research.md R-009가 3계층 테스트 전략을 확정했고, contracts/tools.md가 **19항목** 계약 테스트 체크리스트를 정의했다. 확인 절차(FR-016/FR-017)와 팬아웃 부분 실패(R-004b)는 계약 테스트 없이는 검증이 불가능하다.

**Organization**: 과제는 사용자 스토리별로 묶여 각 스토리를 독립적으로 구현·테스트할 수 있다.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 병렬 실행 가능 (다른 파일, 미완료 과제에 의존하지 않음)
- **[Story]**: 소속 사용자 스토리 (US1, US2, US3)
- 모든 과제에 정확한 파일 경로 포함

## Path Conventions

단일 Python 패키지 — 소스는 `src/google_cloud_support_mcp/`, 테스트는 `tests/` (plan.md의 Project Structure).

## Scope

**14개 도구** (읽기 8 / 쓰기 6)가 범위 내 **13개 RPC + 2개 미디어 HTTP 엔드포인트**를 덮는다. 세 사용자 스토리가 모든 도구를 소진하므로 US4 같은 추가 단계는 없다.

> **범위 밖 — 과제를 만들지 않는다**: `SupportEventSubscriptionService`(7 RPC) 전체가 spec.md Clarifications(2026-09-01)로 배제되었다. 푸시 수신기뿐 아니라 구독 리소스 CRUD도 구현하지 않으며, `tools/subscriptions.py`는 존재하지 않는다. `v2beta` `FeedService.ShowFeed`도 미커버다. 두 사실은 T080의 README에 명시한다.

## ⚠️ 쓰기 실행 규칙 (Write Execution Policy)

실 API 쓰기는 **테스트 케이스에 한해 허용**한다. 지원 엔지니어에게 라우팅되지 않기 때문이다.

| 동작 | 실행 |
|------|------|
| `create_case`에 **`test_case=True`** | **허용** — 레코드는 남지만 지원 조직에 라우팅되지 않는다 |
| 위에서 만든 테스트 케이스에 대한 `add_comment` · `update_case` · `close_case` · `upload_attachment` | **허용** |
| `create_case`에 **`test_case=False`**(또는 미지정) | **금지** — 실제 지원 티켓이 되어 엔지니어에게 라우팅된다 |
| **`escalate_case`** | **금지** — 대상이 테스트 케이스여도 실행하지 않는다. 에스컬레이션은 Google 지원 조직에 직접 전달되는 조치이며, spec이 기본 비활성으로 둔 이유가 이것이다 |

**강제 수단** (관례가 아니라 코드로):

- 쓰기 통합 테스트는 `GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT`와 `GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1`을 **둘 다** 요구한다. 읽기 테스트만 켜려던 사람이 실수로 케이스를 만드는 것을 막는다.
- `tests/integration/conftest.py`가 **모든 `CreateCase` 요청에 `test_case=True`가 붙었는지 단언**하고, 아니면 요청 전에 테스트를 실패시킨다(T042). 사람의 주의력에 의존하지 않는다.
- 통합 테스트는 `escalate_case`를 호출하지 않는다. 에스컬레이션 검증은 목 기반 계약 테스트(T064)로만 한다.
- 만든 테스트 케이스는 테스트 종료 시 `close_case`로 정리한다. 다만 **정리해도 레코드 자체는 남는다.**

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 프로젝트 초기화 및 의존성 확정

- [X] T001 `pyproject.toml`에 적을 런타임·dev 의존성의 **현재 최신 안정 버전을 레지스트리(PyPI)에서 재확인**하고 확인 날짜를 함께 기록한다 — 헌법 원칙 IV MUST("구현 착수 전 재확인, 기억에 의존하지 않는다"). 2026-09-01 확인 결과: `fastmcp 4.0.0`, `google-cloud-support 0.5.3`, `httpx 0.28.1`, `pydantic-settings 2.15.0`, `respx 0.23.1`, `ruff 0.16.5`, `pytest 9.1.1`, `pytest-asyncio 1.4.0`. 값이 달라졌으면 T003·T004의 핀을 갱신한다
- [X] T002 신규 의존성 6종(`httpx`, `pydantic-settings`, `respx`, `ruff`, `pytest`, `pytest-asyncio`)의 **사용 예정 표면에 deprecated 항목이 있는지 점검**하고 결과를 `specs/001-gcp-support-mcp/research.md`에 기록한다 — 헌법 원칙 V MUST("의존성 추가 시 deprecated 표면 확인"). 특히 `pytest 9.x`와 `pytest-asyncio 1.x`의 `asyncio_mode` 관련 변경, `httpx` 클라이언트 API 변경을 확인한다. deprecated가 발견되면 대체 API를 쓰고, 대체 수단이 없으면 미해결 항목으로 기록한다
- [X] T003 `pyproject.toml`에 런타임 의존성 추가 — **전부 정확한 값으로 고정한다**(헌법 원칙 IV MUST): `fastmcp==4.0.0`, `google-cloud-support==0.5.3`, `httpx==0.28.1`, `pydantic-settings==2.15.0` (T001에서 2026-09-01 확인) (`google-auth`는 SDK가 이미 요구하므로 직접 선언하지 않는다). `mcp`를 직접 의존성으로 추가하지 말 것 — `fastmcp-slim`이 자체 핀을 갖는다
- [X] T004 `pyproject.toml`에 dev 의존성 그룹 추가 — **전부 정확한 값으로 고정한다**: `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `respx==0.23.1`(httpx 목킹), `ruff==0.16.5` (T001에서 2026-09-01 확인)
- [X] T005 `src/google_cloud_support_mcp/` 아래 plan.md Project Structure의 빈 모듈 파일과 `tools/` 패키지 생성 (`subscriptions.py`는 만들지 않는다)
- [X] T006 [P] `pyproject.toml`에 ruff lint/format 설정 추가 후 `uv run ruff check .`와 `uv run ruff format --check .`가 **통과하는지 확인한다** (헌법 원칙 II MUST)
- [X] T007 [P] `pyproject.toml`에 pytest 설정 추가: `asyncio_mode = "auto"`, `integration` 마커 등록 (기본 deselect)
- [X] T008 [P] `tests/unit/`, `tests/contract/`, `tests/integration/` 디렉터리와 `__init__.py` 생성
- [X] T009 `pyproject.toml` 기준으로 `uv sync` 실행 후 Python 3.14에서 `grpcio` cp314 휠이 설치되는지 확인 (research 확인: cp314 휠 10종 존재). 실패 시 SDK를 `transport="rest"`(동기)로 두고 `asyncio.to_thread`로 감싸는 방식으로 전환 판단

**Checkpoint**: 의존성이 설치되고 빈 패키지가 임포트된다

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 모든 사용자 스토리가 의존하는 횡단 인프라

**⚠️ CRITICAL**: 이 단계가 끝나기 전에는 어떤 사용자 스토리도 시작할 수 없다

plan.md의 Structure Decision이 밝힌 대로 이 프로젝트는 인프라 비중이 크다 — `confirm`은 6개 도구에, `errors`·`serializers`는 14개 전부에 걸린다. 이들을 도구 모듈에 인라인하면 요구사항 하나를 고치는 데 여러 파일을 손봐야 한다.

### 설정과 데이터 형태

- [X] T010 `src/google_cloud_support_mcp/settings.py`에 `Settings`(pydantic-settings, 접두사 `GOOGLE_CLOUD_SUPPORT_MCP_`) 구현 — data-model.md Configuration 표의 **8개 항목** 전부 (`ENABLE_SUBSCRIPTIONS`는 없다)
- [X] T011 `src/google_cloud_support_mcp/settings.py`에 `PARENTS` 형식 검증 추가 — 각 항목이 `projects/{id}` 또는 `organizations/{id}`여야 하며 **기동 시점에** 거부한다 (첫 도구 호출까지 미루면 원인 파악이 어렵다)
- [X] T012 [P] `src/google_cloud_support_mcp/models.py`에 enum 정의: `CaseState`(5+1), `CaseStateFilter`(OPEN/CLOSED), `CasePriority`(P0~P4), `EscalationReason`(RESOLUTION_TIME/TECHNICAL_EXPERTISE/BUSINESS_IMPACT), `ErrorKind`(9종)
- [X] T013 `src/google_cloud_support_mcp/models.py`에 엔티티 모델 추가: `ResourceRef`, `CaseSummary`, `CaseDetail`, `Comment`, `Attachment`, `DownloadedAttachment`, `Classification`, `ScopeFailure`, `ListEnvelope[T]` (T010의 enum에 의존)

### 오류 정규화 — 두 트랜스포트, 전수 기준

- [X] T014 [P] `src/google_cloud_support_mcp/errors.py`에 공유 매핑 테이블과 `from_grpc(exc)` 구현 — research.md R-007 표의 **9행**. `permission_denied`와 `support_plan_required`를 403 본문 시그니처로 분기하고, 구분 실패 시 두 가능성을 모두 안내하는 문구로 폴백. **마지막 행(`unknown`)은 빈 문구나 원본 예외 문자열이 아니라 다음 조치를 담은 기본 안내를 반환해야 한다** (FR-021·SC-006 전수 기준)
- [X] T015 `src/google_cloud_support_mcp/errors.py`에 `from_http(exc)` 추가 — `httpx.HTTPStatusError`의 401/403/404/400/429/503과 미매핑 예외를 **동일한 `ErrorKind`와 동일한 안내 문구**로 정규화 (T012의 테이블 재사용)
- [X] T016 [P] `tests/unit/test_errors.py`에 두 경로 동등성 테스트 + **미분류 예외가 `unknown`으로 분류되고 `detail`이 비어 있지 않은 조치 안내를 담는지** 검증 (계약 체크리스트 13·14번). **`media.py`가 아니라 직접 만든 `httpx.HTTPStatusError`/`GoogleAPICallError` 인스턴스로 테스트한다** — US3을 기다리지 않는다

### 직렬화

- [X] T017 [P] `src/google_cloud_support_mcp/serializers.py`에 proto→모델 변환 구현 — enum을 문자열 이름으로, `Timestamp`를 ISO-8601로, `Comment.creator.google_support`를 `author_side`로. **`Comment.plain_text_body`는 쓰지 않는다**(proto가 `DEPRECATED. DO NOT USE.`로 표시)
- [X] T018 `src/google_cloud_support_mcp/serializers.py`에 콘솔 URL 생성 추가 — 프로젝트/조직 형식 분기. **파싱 실패 시 `console_url=None`이되 호출은 성공해야 한다** (FR-023)
- [X] T019 [P] `tests/unit/test_serializers.py`에 직렬화·콘솔 URL·파싱 실패 폴백 테스트

### 인증과 클라이언트 수명주기

- [X] T020 `src/google_cloud_support_mcp/auth.py`에 `google.auth.default()` 기반 자격 증명 획득 구현 — 스코프 `https://www.googleapis.com/auth/cloud-platform`, quota project 헤더(`x-goog-user-project`) 적용. **자격 증명을 저장하지 않는다** (FR-020)
- [X] T021 `src/google_cloud_support_mcp/auth.py`에 미디어 REST용 베어러 토큰 공급자 추가 — 같은 `Credentials`에서 `refresh()` 후 `token`을 꺼내며, gRPC 채널 자격 증명과 **갱신 주기가 독립적**임을 처리 (SDK/REST 간극의 2차 결과)
- [X] T022 `src/google_cloud_support_mcp/clients.py`에 **3개** GAPIC AsyncClient(`CaseService`, `CommentService`, `CaseAttachmentService`)와 `httpx.AsyncClient` 번들 구현 — **lifespan이 소유하며 호출마다 생성하지 않는다**

### 팬아웃 (Cross-org)

- [X] T023 [P] `src/google_cloud_support_mcp/fanout.py`에 복합 커서 인코딩/디코딩 구현 — base64url JSON `{"v":1,"cursors":{...}}`. 소진 parent는 `null`, 모두 `null`이면 커서 미발급
- [X] T024 `src/google_cloud_support_mcp/fanout.py`에 커서 거부 규칙 추가 — 알 수 없는 `v`, 손상된 base64, **커서의 parent 집합이 현재 요청과 불일치**하는 경우
- [X] T025 `src/google_cloud_support_mcp/fanout.py`에 동시 실행·병합 구현 — `FANOUT_CONCURRENCY` 세마포어, parent별 오류를 `ScopeFailure`로 수집. **한 parent의 실패가 전체 호출을 실패시키지 않는다** (FR-007, FR-021; T014·T023 의존)
- [X] T026 [P] `tests/unit/test_fanout.py`에 커서 라운드트립·소진 생략·위조·`v` 불일치·parent 집합 불일치 테스트, **그리고 합성 호출자로 다중 parent 병합·부분 실패 수집 테스트** (계약 체크리스트 15번) — 커서 절반만 검증하고 병합을 US1까지 미루지 않는다

### 확인 절차 (FR-016 / FR-017)

- [X] T027 [P] `src/google_cloud_support_mcp/confirm.py`에 프로토콜 era 판별 구현 — `ctx.request_context.protocol_version` 기준으로 modern(≥`2026-07-28`) / handshake(≤`2025-11-25`) / elicitation 미지원 3분기
- [X] T028 `src/google_cloud_support_mcp/confirm.py`에 modern 경로 구현 — 라운드 1은 미리보기 문장과 함께 `InputRequiredResult` 반환하고 **페이로드 원본을 `request_state`에 봉인**. 라운드 2는 `action`을 **먼저** 확인하고 `accept`일 때만 `request_state`에서 **재구성 없이 그대로** 복원해 실행 (FR-016, FR-017)
- [X] T029 `src/google_cloud_support_mcp/confirm.py`에 `tool` 필드 검증 추가 — 라운드 2의 실행 도구와 봉인된 `tool`이 다르면 거부 (확인 토큰의 도구 간 재사용 차단)
- [X] T030 `src/google_cloud_support_mcp/confirm.py`에 handshake era `ctx.elicit()` 분기와 **elicitation 미지원 클라이언트 거부 경로** 추가 — 변경 없이 사유 안내 (FR-019)

### 서버 조립

- [X] T031 [P] `src/google_cloud_support_mcp/redaction.py`에 `RedactionMiddleware` 구현 — 로그·진단 출력에서 케이스 본문·코멘트 본문·첨부 파일명 제거 (FR-022)
- [X] T032 [P] `tests/unit/test_redaction.py`에 민감 필드가 로그 레코드에 남지 않는지 테스트
- [X] T033 `src/google_cloud_support_mcp/server.py`에 FastMCP 인스턴스 생성 — `name`, `instructions`(비활성 기능 안내 포함, FR-019), `mask_error_details=True`, lifespan으로 T022 클라이언트 소유
- [X] T034 `src/google_cloud_support_mcp/server.py`에 미들웨어 스택 등록 — 순서대로 `ErrorHandlingMiddleware`, `RedactionMiddleware`, `TimingMiddleware`, `LoggingMiddleware`, `RateLimitingMiddleware`
- [X] T035 `src/google_cloud_support_mcp/server.py`에 태그 게이팅 구현 — 도메인 태그는 `cases`/`comments`/`attachments`/`classifications` 넷. 설정에 따라 `mcp.disable(tags={...})`. 기본값: `escalation` 비활성, 나머지 쓰기 활성 (FR-018)
- [X] T036 [P] `src/google_cloud_support_mcp/tools/__init__.py`에 `register_all(mcp)` 구현 — 네 도메인 모듈의 `register(mcp)`를 명시적으로 호출 (`FileSystemProvider` 사용하지 않음)
- [X] T037 [P] `src/google_cloud_support_mcp/__init__.py`에 `main()`, `src/google_cloud_support_mcp/__main__.py`에 모듈 실행 진입점 구현 — 기본 stdio 전송
- [X] T038 `tests/conftest.py`에 픽스처 구현 — 목 GAPIC 클라이언트 3종, `respx` 기반 httpx 목, 인메모리 `Client(mcp)`, 설정 오버라이드, 프로토콜 era 지정 가능한 클라이언트
- [X] T039 [P] `tests/contract/test_gating.py`에 게이팅 **메커니즘** 계약 테스트 — 합성 태그 도구를 등록한 뒤 `mcp.disable(tags={...})`가 `tools/list`에서 해당 도구를 제거하는지 검증. **실제 14개 도구 인벤토리 단언은 T075(Phase 6)이 담당한다** — 이 시점에는 등록된 도구가 없다

**Checkpoint**: 서버가 기동되고 도구 0개로 `tools/list`에 응답한다. 오류 정규화·커서·병합·게이팅 메커니즘이 합성 입력으로 검증된 상태다 — 실제 도구를 통한 종단 검증은 각 스토리 단계에서 이뤄진다

---

## Phase 3: User Story 1 - 지원 케이스 조회 및 상황 파악 (Priority: P1) 🎯 MVP

**Goal**: 콘솔을 열지 않고 담당 프로젝트·조직의 케이스 상태와 대화 내역을 파악한다. 쓰기 기능이 전혀 없어도 완결적으로 동작한다.

**Independent Test**: quickstart.md V2 — 케이스 목록 조회 → 상세 조회 → 코멘트 조회를 순서대로 수행해 콘솔과 동일한 정보가 반환되는지 확인. 그리고 V3 — 권한 있는 parent와 없는 parent를 함께 설정해 부분 실패가 나머지 결과를 가리지 않는지 확인.

**도구 6개**: `search_cases`, `get_case`, `list_comments`, `get_comment`, `list_attachments`, `get_attachment`

### Tests for User Story 1 ⚠️

> **먼저 작성하고 실패를 확인한 뒤 구현한다**

- [X] T040 [P] [US1] `tests/contract/test_read_tools.py`에 6개 읽기 도구의 이름·입력 스키마·출력 스키마·태그·`annotations` 검증 (`readOnlyHint=true`, `get_*`에 `idempotentHint=true`)
- [X] T041 [P] [US1] `tests/contract/test_fanout_partial_failure.py`에 3개 parent 중 1개가 `PermissionDenied`일 때 나머지 2개 결과가 반환되고 `scopes_failed`에 1건이 실리는지 검증 (계약 체크리스트 11번)
- [X] T042 [P] [US1] `tests/contract/test_pagination.py`에 parent 간 복합 커서 페이지네이션 검증 — 결과 연속성, 중복 없음, **`truncated` 플래그가 남은 결과 유무를 정확히 반영**, `parents` 변경 시 커서 거부 (FR-007, 계약 체크리스트 15번)
- [X] T043 [P] [US1] `tests/contract/test_error_classification.py`에 도구 경유 오류 분류 검증 — 지원 플랜 403과 권한 403이 서로 다른 `ErrorKind`·다른 안내를 내는지, **미매핑 예외가 `unknown`으로 조치 안내와 함께 반환되는지** (계약 체크리스트 12·13번)
- [X] T044 [P] [US1] `tests/integration/test_read_journey.py`에 실제 API 조회 여정 테스트 (`GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT` 있을 때만). 같은 파일의 `tests/integration/conftest.py`에 **모든 `CreateCase` 요청의 `test_case=True`를 단언하는 가드**를 둔다 — 위 쓰기 실행 규칙의 강제 수단

### Implementation for User Story 1

- [X] T045 [US1] `src/google_cloud_support_mcp/tools/cases.py`에 `search_cases` 구현 — **항상 `SearchCases`를 호출하고 `ListCases`로 분기하지 않는다**(빈 쿼리가 곧 목록 조회). 쿼리 빌더는 `priorities`를 `AND (priority=P0 OR priority=P1)` 형태로 **괄호로 묶는다**. T025 팬아웃 경유 (FR-001, FR-002, SC-001)
- [X] T046 [US1] `src/google_cloud_support_mcp/tools/cases.py`에 `get_case` 구현 — `CaseDetail` 반환, `console_url` 포함 (FR-003, FR-023)
- [X] T047 [P] [US1] `src/google_cloud_support_mcp/tools/comments.py`에 `list_comments`와 `get_comment` 구현 — 시간 순서, `author_side`로 고객/지원팀 구분 (FR-004, spec US1 AS-3)
- [X] T048 [P] [US1] `src/google_cloud_support_mcp/tools/attachments.py`에 `list_attachments`와 `get_attachment` 구현 — **메타데이터만, 바이트 없음** (FR-005)
- [X] T049 [P] [US1] `src/google_cloud_support_mcp/resources.py`에 `case://{parent}/{case_id}` 리소스 템플릿 구현 — 두 세그먼트에 경로 이탈 방지 형식 검증
- [X] T050 [P] [US1] `src/google_cloud_support_mcp/prompts.py`에 `triage_open_cases` 프롬프트 구현 (SC-001 대상)
- [X] T051 [US1] `src/google_cloud_support_mcp/tools/__init__.py`에 cases·comments·attachments 읽기 도구 등록 후 quickstart V1·V2·V3 수행

**Checkpoint**: US1이 독립적으로 완전히 동작한다. 여기서 멈춰도 배포 가능한 MVP다

---

## Phase 4: User Story 2 - 케이스 생성 및 대화 참여 (Priority: P2)

**Goal**: 장애 정황을 정리한 내용을 그대로 새 케이스로 제출하고, 기존 케이스에 코멘트를 남긴다.

**Independent Test**: 목 클라이언트로 확인 2라운드를 검증한다 — 라운드 1이 상류 호출 없이 확인을 요청하고, 거절 시 호출 0회, 승인 시 봉인된 페이로드가 그대로 전송되는지. **실 API 검증(quickstart V4)은 담당자가 자기 프로젝트에서 의도적으로 수행할 때만 이뤄지며, 이 프로젝트에서는 실행하지 않는다.**

**도구 3개**: `search_case_classifications`, `create_case`, `add_comment`

### Tests for User Story 2 ⚠️

- [X] T052 [P] [US2] `tests/contract/test_confirm_create_case.py`에 2라운드 확인 검증 — 라운드 1이 `InputRequiredResult`를 반환하고 **상류 호출 0회**, `action="decline"` 라운드 2도 **상류 호출 0회**(FR-017), `action="accept"` 라운드 2가 `request_state`의 페이로드를 **바이트 단위로 동일하게** 전송(FR-016) (계약 체크리스트 6~8번, SC-004)
- [X] T053 [P] [US2] `tests/contract/test_classification_validation.py`에 유효하지 않은 `classification_id`가 **확인을 묻지 않고** 거부되고 후보 목록이 반환되는지 검증 (FR-009, 계약 체크리스트 17번)
- [X] T054 [P] [US2] `tests/contract/test_confirm_add_comment.py`에 코멘트 2라운드 확인, 본문 무재구성 전송, 12,800자 상한 검증
- [X] T055 [P] [US2] `tests/contract/test_no_elicitation.py`에 elicitation 미지원 클라이언트에서 쓰기 도구가 **변경 없이** 거부하고 사유를 안내하는지 검증 (FR-019, 계약 체크리스트 9번)
- [X] T056 [P] [US2] `tests/integration/test_create_journey.py`에 **`test_case=True`** 케이스 생성·코멘트·정리 여정 테스트 작성. `GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT`와 `GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1`이 **둘 다** 있을 때만 실행되도록 이중 게이트를 건다(`pytest.mark.skipif`). 테스트 종료 시 `close_case`로 정리한다

### Implementation for User Story 2

- [X] T057 [P] [US2] `src/google_cloud_support_mcp/tools/classifications.py`에 `search_case_classifications` 구현 — parent 없는 전역 검색, `ListEnvelope[Classification]` 반환 (FR-006)
- [X] T058 [US2] `src/google_cloud_support_mcp/tools/cases.py`에 `create_case` 구현 — **확인 요청 전에** `classification_id`를 T055로 검증(FR-009), 통과 시 T028 확인 흐름 경유. 미리보기에 제출될 전체 페이로드 포함 (FR-008, FR-009, FR-016)
- [X] T059 [US2] `src/google_cloud_support_mcp/tools/comments.py`에 `add_comment` 구현 — 본문 12,800자 상한 검증, 미리보기에 본문 전문 포함, T028 확인 흐름 경유 (FR-010, FR-016)
- [X] T060 [P] [US2] `src/google_cloud_support_mcp/prompts.py`에 `draft_case_from_incident` 프롬프트 구현 (SC-002 대상)
- [X] T061 [US2] `src/google_cloud_support_mcp/tools/__init__.py`에 US2 도구 등록 후 quickstart V1과 **V4의 확인 흐름을 목 클라이언트로** 검증한다. 실 API 검증(V4 전체)은 `test_case: true`로 수행 가능하되 자격 증명이 있을 때만

**Checkpoint**: US1과 US2가 각각 독립적으로 동작한다

---

## Phase 5: User Story 3 - 케이스 수명주기 관리 및 첨부 파일 (Priority: P3)

**Goal**: 케이스 속성 변경·종료·에스컬레이션과 첨부 파일 업로드·다운로드.

**Independent Test**: quickstart.md V4 7단계와 V5 전체 — 우선순위 변경 → 첨부 업로드/목록/다운로드 → 케이스 종료. 에스컬레이션은 `ENABLE_ESCALATION=true`에서만.

**도구 5개**: `update_case`, `close_case`, `escalate_case`, `download_attachment`, `upload_attachment`

**⚠️ SDK 간극 주의**: 첨부 업로드·다운로드는 GAPIC 클라이언트에 **존재하지 않는다**. `media.py`가 `httpx` + T021 베어러 토큰으로 REST를 직접 호출한다.

### Tests for User Story 3 ⚠️

- [X] T062 [P] [US3] `tests/contract/test_update_case.py`에 미리보기가 **변경 전/후 값을 나란히** 보여주는지, `update_mask`가 `None`이 아닌 필드에서만 생성되는지, 전 필드 `None`이 `invalid_argument`인지 검증
- [X] T063 [P] [US3] `tests/contract/test_close_case.py`에 미리보기의 **되돌릴 수 없음** 명시와 이미 `CLOSED`인 케이스의 `failed_precondition` 검증
- [X] T064 [P] [US3] `tests/contract/test_escalate_case.py`에 기본 설정에서 도구 부재, `ENABLE_ESCALATION=true`에서 `destructiveHint=true`·`justification` 필수·미리보기의 **Google 지원 조직 전달 명시** 검증
- [X] T065 [P] [US3] `tests/contract/test_attachment_media.py`에 `download_attachment` 결과에 **바이트가 없고** `local_path`의 파일이 실제로 존재하는지, 파일명 충돌 시 접미사가 붙는지 검증 (FR-014, FR-022, 계약 체크리스트 16번)
- [X] T066 [P] [US3] `tests/integration/test_lifecycle_journey.py`에 **`test_case=True`** 케이스 대상 수명주기·첨부 여정 테스트 작성 (T056과 동일한 이중 게이트). **`escalate_case`는 호출하지 않는다** — 에스컬레이션 검증은 T064의 목 계약 테스트로만 한다

### Implementation for User Story 3

- [X] T067 [US3] `src/google_cloud_support_mcp/tools/cases.py`에 `update_case` 구현 — `update_mask` 생성, 변경 전/후 미리보기, T028 확인 흐름 경유 (FR-011, FR-016)
- [X] T068 [US3] `src/google_cloud_support_mcp/tools/cases.py`에 `close_case` 구현 — `destructiveHint=true`, 되돌릴 수 없음 미리보기 (FR-012, FR-016)
- [X] T069 [US3] `src/google_cloud_support_mcp/tools/cases.py`에 `escalate_case` 구현 — `EscalationReason` 3종, `justification` 필수, T035 태그 게이팅으로 기본 미등록 (FR-013, FR-016, FR-018, SC-005)
- [X] T070 [P] [US3] `src/google_cloud_support_mcp/media.py`에 다운로드 구현 — `GET https://cloudsupport.googleapis.com/v2/{name}:download` + `?alt=media`, 디스크 기록, 파일명 충돌 시 접미사, T015 오류 정규화 경유
- [X] T071 [US3] `src/google_cloud_support_mcp/media.py`에 업로드 구현 — Upload URI `POST https://cloudsupport.googleapis.com/upload/v2/{parent=*/*/cases/*}/attachments`, 요청 본문 `{"attachment": {"filename": ...}}`(쿼리 파라미터 아님). **`uploadType` 값을 실제 호출로 확정한다**(research 미해결 4) — `multipart` 실패 시 Metadata URI 선행 생성 경로를 폴백으로 검토
- [X] T072 [US3] `src/google_cloud_support_mcp/tools/attachments.py`에 `download_attachment` 구현 — `readOnlyHint=true`, 확인 불필요, `DownloadedAttachment` 반환 (FR-014, FR-022)
- [X] T073 [US3] `src/google_cloud_support_mcp/tools/attachments.py`에 `upload_attachment` 구현 — 확인 요청 **전에** 파일 존재와 `MAX_UPLOAD_BYTES` 검증, 미리보기에 파일명·크기만(내용 제외), **`request_state`에 파일 경로만 담고 바이트는 담지 않는다** (FR-015, FR-016, FR-022)
- [X] T074 [US3] `src/google_cloud_support_mcp/tools/__init__.py`에 US3 도구 등록 후 quickstart V1과 계약 테스트로 검증한다. 실 API 검증(V4 7단계·V5)은 테스트 케이스 대상으로 수행 가능하되 **에스컬레이션은 제외한다**

**Checkpoint**: 세 사용자 스토리가 모두 독립적으로 동작하고 14개 도구가 전부 등록된다

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 여러 스토리에 걸친 마무리와 research 미해결 항목 해소

- [X] T075 [P] `tests/contract/test_tool_inventory.py`에 도구 인벤토리 단언 — 총 **14개**, 읽기 8개(`readOnlyHint`), 쓰기 6개, 파괴적 2개(`close_case`·`escalate_case`, `destructiveHint`), 리소스 템플릿 1개, 프롬프트 2개. **구독 관련 도구가 하나도 등록되지 않는지 함께 단언한다** (계약 체크리스트 1~3번). 설정별 노출 개수도 단언 — 기본 13개, `ENABLE_ESCALATION=true`에서 14개, `ENABLE_WRITES=false`에서 8개 (계약 체크리스트 4~5번, T037에서 이월). SC-005·SC-007의 검증 지점이다
- [X] T076 [P] `tests/contract/test_protocol_eras.py`에 handshake era 연결에서 `ctx.elicit()` 경로가 동작하는지 검증 (계약 체크리스트 10번, quickstart V8)
- [X] T077 [P] `tests/contract/test_console_url.py`에 모든 `CaseSummary`/`CaseDetail`에 `console_url`이 있거나 파싱 실패 시 `None`이되 호출은 성공하는지 검증 (계약 체크리스트 18번)
- [X] T078 quickstart.md V7 수행 — `FASTMCP_LOG_LEVEL=DEBUG`로 실행 후 로그에 케이스 본문·코멘트 본문·첨부 파일명이 나타나지 않는지 확인 (FR-022, 계약 체크리스트 19번)
- [X] T079 [P] research 미해결 1 해소 — 조직 parent + 사용자 ADC 조합에서 quota project가 실제로 필요한지 확인하고 `src/google_cloud_support_mcp/settings.py`의 기본값과 `src/google_cloud_support_mcp/errors.py`의 안내 문구를 결과에 맞춘다
- [X] T080 [P] research 미해결 2 해소 — 지원 플랜 미가입 403의 실제 메시지 시그니처를 확인해 `src/google_cloud_support_mcp/errors.py`의 분기 조건을 확정하고 폴백 문구 유지 여부를 판단
- [ ] T081 [P] research 미해결 3·4 해소 — 첨부 업로드 크기 상한과 `uploadType` 값을 실제 호출로 확인해 `src/google_cloud_support_mcp/settings.py`의 `MAX_UPLOAD_BYTES`와 `src/google_cloud_support_mcp/media.py`의 업로드 경로를 확정 — **[BLOCKED — 지원 플랜 필요]** 재개 절차는 [deferred.md](./deferred.md#t081--attachment-upload-size-limit-and-uploadtype).
- [X] T082 `README.md` 작성 — 설치, ADC·quota project 설정, 8개 설정 항목 표, MCP 클라이언트 등록 예시, 기본 비활성 기능(에스컬레이션), **SC-003 기준선을 도입 전에 측정해 두라는 안내**, **미커버 두 가지 명시**: `SupportEventSubscriptionService`는 범위 밖(spec.md Clarifications), `v2beta` `FeedService.ShowFeed`는 v1 미커버
- [ ] T083 quickstart.md V9 수행 — 문서를 읽지 않은 사람이 자격 증명 설정부터 첫 `search_cases` 성공까지 10분 이내에 도달하는지 측정 (SC-008). 특히 `PARENTS` 미설정 오류 문구가 스스로 해결법을 알려주는지 확인 — **[BLOCKED — 사람이 측정]** 측정 절차는 [deferred.md](./deferred.md#t083--sc-008-first-run-experience-under-ten-minutes).
- [X] T084 contracts/tools.md의 **19항목** 계약 테스트 체크리스트를 전부 대조해 누락 없음을 확인
- [ ] T085 quickstart.md V1~V9 수행(V4·V5는 `test_case: true`로, **에스컬레이션 단계는 제외**), `uv run pytest` 전체 통과, **`uv run ruff check .`·`uv run ruff format --check .` 통과** 확인 (헌법 원칙 II·III) — **[부분 완료]** V1·V2·V3·V6·V7·V8은 2026-09-01 라이브 확인. V4·V5는 [deferred.md](./deferred.md#t085--quickstart-v4-and-v5-against-the-live-api).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 의존성 없음 — 즉시 시작
- **Foundational (Phase 2)**: Setup 완료 후 — **모든 사용자 스토리를 차단한다**
- **User Stories (Phase 3~5)**: Foundational 완료 후 — 이후 병렬 또는 우선순위 순차
- **Polish (Phase 6)**: 원하는 스토리가 모두 끝난 뒤

### User Story Dependencies

- **US1 (P1)**: Foundational 후 시작. 다른 스토리에 의존하지 않음
- **US2 (P2)**: Foundational 후 시작. `confirm.py`가 Foundational에 있으므로 **US1 없이도 독립 구현·테스트 가능**
- **US3 (P3)**: Foundational 후 시작. `confirm.py`가 Foundational에 있으므로 US2에 의존하지 않음. `media.py`는 이 스토리 안에서 자족적

> `confirm.py`(T027~T030)와 `fanout.py`(T023~T025)를 Foundational에 둔 것이 스토리 독립성의 근거다. `confirm`을 US2에 넣었다면 US3이 US2에 의존하게 되어 병렬 진행이 불가능했다.

### Within Each User Story

- 테스트를 먼저 작성하고 **실패를 확인한 뒤** 구현한다
- 모델 → 서비스 → 도구 등록 순서
- 도구 등록 후 해당 quickstart 시나리오 수행

### Critical Path

`T003 → T009 → T010/T012 → T013 → T014 → T022 → T025 → T028 → T045 → T051` (MVP까지)

---

## Parallel Opportunities

### Phase 2 (Foundational) 내부

```bash
# 서로 다른 파일, 의존성 없음:
Task: "T012 models.py enum 정의"
Task: "T014 errors.py 공유 테이블 + from_grpc()"
Task: "T017 serializers.py proto→모델 변환"
Task: "T023 fanout.py 복합 커서"
Task: "T027 confirm.py 프로토콜 era 판별"
Task: "T031 redaction.py RedactionMiddleware"
```

### Phase 3 (US1) 테스트

```bash
# 5개 테스트 파일 모두 병렬:
Task: "T040 읽기 도구 스키마·annotations 계약 테스트"
Task: "T041 팬아웃 부분 실패 계약 테스트"
Task: "T042 복합 커서 페이지네이션 계약 테스트"
Task: "T043 오류 분류 계약 테스트"
Task: "T044 조회 여정 통합 테스트"
```

### Phase 3 (US1) 구현

```bash
# 서로 다른 모듈:
Task: "T047 tools/comments.py 읽기 도구"
Task: "T048 tools/attachments.py 읽기 도구"
Task: "T049 resources.py 케이스 리소스 템플릿"
Task: "T050 prompts.py triage_open_cases"
```

> **파일 충돌 지점 세 곳** — 스토리를 병렬로 진행한다면 여기만 조율하면 된다:
> - `tools/cases.py`: T045·T046(US1), T058(US2), T067~T069(US3)
> - `tools/attachments.py`: T048(US1), T072·T073(US3)
> - `tools/__init__.py`: T036(Foundational), T051(US1), T061(US2), T074(US3) — **각 스토리의 마지막 등록 과제가 전부 이 파일을 건드린다**

### 스토리 간 병렬

Foundational 완료 후 US1~US3을 서로 다른 담당자가 동시에 진행할 수 있다. 위 세 파일만 조율하면 된다.

---

## Implementation Strategy

### MVP First (US1만)

1. Phase 1 Setup 완료
2. Phase 2 Foundational 완료 — **가장 큰 단계이며 모든 것을 차단한다**
3. Phase 3 US1 완료
4. **중단하고 검증**: quickstart V1·V2·V3 수행
5. 이 시점의 산출물은 "읽기 전용 Cloud Support MCP"로 그 자체로 배포 가능하다

### Incremental Delivery

1. Setup + Foundational → 기반 완성
2. US1 추가 → 독립 검증 → 배포 (**MVP**, 도구 6개)
3. US2 추가 → 독립 검증 → 배포 (도구 9개, 케이스 제출 가능)
4. US3 추가 → 독립 검증 → 배포 (도구 14개, 범위 내 커버리지 완성 — SC-007 달성)

### 위험이 집중된 지점

- **T025 팬아웃 병합** — cross-org 요구의 핵심이며, 한 parent의 403이 전체를 죽이는 것이 가장 흔한 회귀다
- **T028 확인 흐름** — FR-016/FR-017 전체가 여기 걸려 있다. `request_state` 봉인을 우회하고 라운드 2에서 페이로드를 재구성하면 사용자가 승인한 것과 실행되는 것이 갈라진다
- **T071 업로드** — 공식 문서에 `uploadType`이 명시되어 있지 않은 유일한 미확정 구간이다
- **T014 `unknown` 폴백** — SC-006이 전수 기준이라 여기가 비면 기준 미달이다. "알 수 없는 오류"로 끝내지 않는다

---

## Notes

- **미완료 3건(T081·T083·T085)의 재개 절차는 [deferred.md](./deferred.md)에 있다.** 무엇이 막혔는지, 무엇을 이미 확인했는지, 어떤 파일을 고쳐야 하는지가 자족적으로 적혀 있다
- `[P]` = 다른 파일, 의존성 없음
- `[Story]` 라벨로 과제를 spec.md의 세 사용자 스토리에 추적
- 테스트는 구현 전에 실패를 확인한다
- 과제 또는 논리적 묶음마다 커밋한다. **커밋 전 `uv run ruff check .`와 `uv run ruff format --check .`가 통과해야 한다** (헌법 원칙 II MUST)
- 소스에 남기는 `TODO`는 **과제 ID를 참조해야 한다** (헌법 원칙 II MUST)
- 각 Checkpoint에서 멈춰 스토리를 독립적으로 검증할 수 있다
- 실 API 쓰기는 **`test_case=True`인 케이스에 한해** 수행한다 — 문서 상단의 쓰기 실행 규칙 참조. `escalate_case`는 대상이 테스트 케이스여도 실행하지 않는다
