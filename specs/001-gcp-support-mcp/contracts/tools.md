# Phase 1 Contract: MCP Tool Surface

**Feature**: `001-gcp-support-mcp` | **Date**: 2026-09-01 | **Plan**: [plan.md](./plan.md)

MCP 서버의 계약은 곧 도구·리소스·프롬프트 표면이다. 이 문서가 `/speckit-tasks`가 소비할 계약 산출물이며, 각 도구는 커버하는 Google RPC와 만족하는 FR로 추적된다.

타입 이름은 [data-model.md](./data-model.md) 참조.

---

## 커버리지 요약

| 원천 | 개수 | 도구 |
|------|------|------|
| `CaseService` (v2) | 8 RPC | 7개 도구 (`ListCases`는 `search_cases`가 **동작으로** 커버 — 아래 참조) |
| `CommentService` (v2) | 3 RPC | 3개 도구 |
| `CaseAttachmentService` (v2) | 2 RPC | 2개 도구 |
| Media REST (SDK 밖) | 2 엔드포인트 | 2개 도구 |
| **합계** | **13 RPC + 2 HTTP** | **14개 도구** |

`SupportEventSubscriptionService`(7 RPC)는 **범위 밖이다** — spec.md Clarifications(2026-09-01)가 푸시 수신뿐 아니라 구독 리소스 CRUD까지 포함해 이 서비스 전체를 제외했다. 도구를 노출하지 않으며 구독용 IAM 역할도 요구하지 않는다.

`v2beta`도 범위 밖이다(R-004). 유일한 v2beta 전용 RPC인 `FeedService.ShowFeed`는 v1 미커버이며, 이 두 가지 미커버 사실을 README에 명시한다.

---

## 공통 규약

**태그**: 모든 도구는 도메인 태그 하나 + 모드 태그(`read`/`write`) 하나를 갖고, 해당하면 위험 태그(`destructive`, `escalation`)를 추가로 갖는다. FR-018의 게이팅 수단이다.

**Annotations**: `readOnlyHint`는 원격 상태를 바꾸지 않는 도구, `destructiveHint`는 되돌릴 수 없는 도구, `idempotentHint`는 반복 호출이 동일한 도구에 붙인다. `openWorldHint`는 전부 `true`(외부 시스템 호출).

**확인 (FR-016)**: `write` 태그 도구는 예외 없이 2라운드 확인을 거친다. 아래 표의 "확인" 열이 `필수`인 도구는 `str | InputRequiredResult` 유니온을 반환한다.

**팬아웃**: "팬아웃" 열이 `예`인 도구(현재 `search_cases` 하나)는 설정된 parent 전체에 병렬 호출하고 `parents` 인자로 범위를 재정의할 수 있다. 모든 목록형 도구는 팬아웃 여부와 무관하게 `ListEnvelope` 형태로 반환해 응답 모양을 통일한다.

**오류**: 모든 도구는 R-007 매핑을 거친 `ToolError`만 던진다. 미디어 REST 경로(`download_attachment`, `upload_attachment`)는 `httpx` 예외를 거치지만 **동일한 `ErrorKind`와 동일한 안내 문구**로 정규화된다 — 사용자가 첨부 오류와 케이스 오류에서 다른 형식의 안내를 받아서는 안 된다. `mask_error_details=True`로 그 외 예외는 클라이언트에 세부사항을 노출하지 않는다.

---

## Cases — 읽기

### `search_cases`

> `CaseService.ListCases` + `CaseService.SearchCases` | FR-001, FR-002, FR-007 | 태그 `cases`,`read` | `readOnlyHint` | 팬아웃 **예** | 확인 불필요

설정된(또는 지정한) 모든 프로젝트·조직에서 지원 케이스를 찾는다. 필터를 주지 않으면 각 범위의 전체 케이스를 반환한다.

**이 도구는 항상 `SearchCases`를 호출한다. `ListCases`로 분기하지 않는다.** 두 RPC는 필터 언어가 다르다 — `ListCases`는 `filter`를, `SearchCases`는 아래 인자들이 따르는 쿼리 문법을 받는다. v2 문서가 명시하듯 *"빈 `query`를 주면 parent 아래 모든 케이스가 반환된다"* 이므로, 빈 쿼리가 곧 목록 조회다. `ListCases`는 그렇게 **동작으로** 커버되며, 별도 디스패치 경로를 만들 이유가 없다.

| 입력 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `parents` | `list[str] \| None` | 설정값 | `projects/{id}` 또는 `organizations/{id}` |
| `state` | `CaseStateFilter \| None` | `None` | `OPEN` 또는 `CLOSED`. **응답 `state`와 어휘가 다르다** |
| `priorities` | `list[CasePriority] \| None` | `None` | 여러 개는 `OR`로 결합하되 **괄호로 묶는다**: `AND (priority=P0 OR priority=P1)` |
| `creator_email` | `str \| None` | `None` | |
| `updated_after` | `str \| None` | `None` | ISO-8601. `>` 연산자만 지원 |
| `text` | `str \| None` | `None` | 제목·본문·코멘트 전역 검색 |
| `page_size` | `int` | `20` | |
| `cursor` | `str \| None` | `None` | 이전 응답의 `next_cursor`. 불투명 문자열 |

**출력**: `ListEnvelope[CaseSummary]`

**계약 요점**: 한 parent가 실패해도 나머지 결과와 함께 성공을 반환한다. 실패는 `scopes_failed`에 실린다 (R-004b). `cursor`의 parent 집합이 `parents`와 다르면 `invalid_argument`로 거부한다.

---

### `get_case`

> `CaseService.GetCase` | FR-003, FR-023 | 태그 `cases`,`read` | `readOnlyHint`, `idempotentHint` | 팬아웃 아니오 | 확인 불필요

| 입력 | 타입 | 설명 |
|------|------|------|
| `case_name` | `str` | `projects/{p}/cases/{id}` 또는 `organizations/{o}/cases/{id}` |

**출력**: `CaseDetail` (`console_url` 포함 — FR-023)

---

### `search_case_classifications`

> `CaseService.SearchCaseClassifications` | FR-006 | 태그 `classifications`,`read` | `readOnlyHint` | 팬아웃 아니오 | 확인 불필요

케이스 생성에 쓸 유효한 분류를 찾는다. **`create_case`의 선행 단계다** (spec US2 AS-1).

| 입력 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `query` | `str` | — | 제품명 또는 증상 키워드 |
| `page_size` | `int` | `20` | |
| `cursor` | `str \| None` | `None` | 단일 범위 호출이므로 Google 토큰 그대로 |

**출력**: `ListEnvelope[Classification]`

---

## Cases — 쓰기

### `create_case`

> `CaseService.CreateCase` | FR-008, FR-009, FR-016 | 태그 `cases`,`write` | `destructiveHint=false` | 확인 **필수**

| 입력 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `parent` | `str` | — | 케이스를 만들 범위 |
| `classification_id` | `str` | — | `search_case_classifications`가 반환한 `id` |
| `title` | `str` | — | |
| `description` | `str` | — | |
| `priority` | `CasePriority` | — | P0가 가장 긴급 |
| `contact_email` | `str \| None` | `None` | |
| `subscriber_emails` | `list[str] \| None` | `None` | |
| `time_zone` | `str \| None` | `None` | |
| `test_case` | `bool` | `false` | 통합 테스트용 |

**출력**: `CaseDetail | InputRequiredResult`

**계약 요점**:
- 확인 요청을 보내기 **전에** `classification_id`를 검증한다 (FR-009). 유효하지 않으면 확인을 묻지 않고 후보 목록과 함께 거부한다 — 실행되지 않을 동작을 사용자에게 확인받는 것은 무의미하다.
- 라운드 1의 미리보기에는 제출될 전체 페이로드가 들어간다 (spec US2 AS-2).
- `action != "accept"`이면 상류 호출을 **하지 않는다** (FR-017). 계약 테스트가 이를 목 호출 횟수 0으로 검증한다.

---

### `update_case`

> `CaseService.UpdateCase` | FR-011, FR-016 | 태그 `cases`,`write` | 확인 **필수**

| 입력 | 타입 | 설명 |
|------|------|------|
| `case_name` | `str` | |
| `title` | `str \| None` | 지정한 필드만 변경 |
| `description` | `str \| None` | |
| `priority` | `CasePriority \| None` | |
| `subscriber_emails` | `list[str] \| None` | |

**출력**: `CaseDetail | InputRequiredResult`

**계약 요점**: 미리보기는 **변경 전/후 값을 나란히** 보여준다 (spec US3 AS-1). `update_mask`는 `None`이 아닌 필드에서만 생성한다. 모든 필드가 `None`이면 `invalid_argument`.

---

### `close_case`

> `CaseService.CloseCase` | FR-012, FR-016 | 태그 `cases`,`write`,`destructive` | **`destructiveHint=true`** | 확인 **필수**

| 입력 | 타입 |
|------|------|
| `case_name` | `str` |

**출력**: `CaseDetail | InputRequiredResult`

**계약 요점**: 미리보기에 **되돌릴 수 없는 동작임을 명시**한다 (spec US3 AS-2). 이미 `CLOSED`인 케이스는 `failed_precondition`.

---

### `escalate_case`

> `CaseService.EscalateCase` | FR-013, FR-016, FR-018 | 태그 `cases`,`write`,`destructive`,`escalation` | **`destructiveHint=true`** | 확인 **필수** | **기본 비활성**

| 입력 | 타입 | 설명 |
|------|------|------|
| `case_name` | `str` | |
| `reason` | `EscalationReason` | `RESOLUTION_TIME` / `TECHNICAL_EXPERTISE` / `BUSINESS_IMPACT` (`escalation.py` 확인) |
| `justification` | `str` | 자유 서술 사유 — **필수** |

**출력**: `CaseDetail | InputRequiredResult`

**계약 요점**: 이 서버에서 가장 날카로운 도구다.
- `CLOUD_SUPPORT_MCP_ENABLE_ESCALATION=true` 없이는 등록조차 되지 않는다 (FR-018).
- 미리보기에 **Google 지원 조직에 실제 전달되는 조치임을 명시**한다 (spec US3 AS-3).
- `justification`이 선택이 아니라 필수인 것은 spec US3 AS-3이 "사유 입력과 명시적 확인을 모두" 요구하기 때문이다.

---

## Comments

### `list_comments`

> `CommentService.ListComments` | FR-004 | 태그 `comments`,`read` | `readOnlyHint` | 팬아웃 아니오

| 입력 | 타입 | 기본 |
|------|------|------|
| `case_name` | `str` | — |
| `page_size` | `int` | `20` |
| `cursor` | `str \| None` | `None` |

**출력**: `ListEnvelope[Comment]` — **시간 순서, `author_side`로 고객/지원팀 구분** (spec US1 AS-3)

### `get_comment`

> `CommentService.GetComment` | FR-004 | 태그 `comments`,`read` | `readOnlyHint`, `idempotentHint`

입력 `comment_name: str` → 출력 `Comment`

### `add_comment`

> `CommentService.CreateComment` | FR-010, FR-016 | 태그 `comments`,`write` | 확인 **필수**

| 입력 | 타입 |
|------|------|
| `case_name` | `str` |
| `body` | `str` — 최대 12,800자 (proto 확인) |

**출력**: `Comment | InputRequiredResult`

**계약 요점**: 미리보기에 작성될 본문 전문이 들어간다 (spec US2 AS-3). 라운드 2는 `request_state`의 본문을 **그대로** 전송한다 — 재구성하지 않는다.

---

## Attachments

### `list_attachments`

> `CaseAttachmentService.ListAttachments` | FR-005 | 태그 `attachments`,`read` | `readOnlyHint`

입력 `case_name: str`, `page_size: int = 20`, `cursor: str | None` → 출력 `ListEnvelope[Attachment]`

### `get_attachment`

> `CaseAttachmentService.GetAttachment` | FR-005 | 태그 `attachments`,`read` | `readOnlyHint`, `idempotentHint`

입력 `attachment_name: str` → 출력 `Attachment` (메타데이터만 — 바이트 없음)

### `download_attachment`

> Media REST `GET /v2/{name}:download?alt=media` | FR-014 | 태그 `attachments`,`read` | `readOnlyHint` | 확인 불필요

| 입력 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `attachment_name` | `str` | — | |
| `destination_dir` | `str \| None` | 설정값 | |

**출력**: `DownloadedAttachment`

**계약 요점**: **파일 바이트를 도구 결과에 절대 싣지 않는다.** 디스크에 쓰고 경로만 반환한다 (R-002, FR-022). 원격 상태를 바꾸지 않으므로 `readOnlyHint=true`이고 확인이 필요 없다 — 로컬 쓰기는 사용자가 요청한 바로 그 결과다. 파일명이 이미 존재하면 덮어쓰지 않고 접미사를 붙인다.

### `upload_attachment`

> Media REST `POST /upload/v2/{parent=*/*/cases/*}/attachments` (Upload URI) | FR-015, FR-016 | 태그 `attachments`,`write` | 확인 **필수**

| 입력 | 타입 | 설명 |
|------|------|------|
| `case_name` | `str` | |
| `file_path` | `str` | 업로드할 로컬 파일 |
| `filename` | `str \| None` | 미지정 시 `file_path`의 basename. 요청 본문 `{"attachment": {"filename": ...}}`으로 전달한다 — 쿼리 파라미터가 아니다 |

**출력**: `Attachment | InputRequiredResult`

**계약 요점**: 확인 요청 전에 파일 존재와 `MAX_UPLOAD_BYTES`를 검증한다. 미리보기는 파일명·크기·대상 케이스를 보여주되 **파일 내용은 보여주지 않는다**. `request_state`에는 파일 경로만 담고 바이트는 담지 않는다 — 봉인 토큰이 클라이언트를 왕복하기 때문이다.

---

## Resources

### `case://{parent}/{case_id}`

리소스 템플릿. 케이스를 주소 지정 가능한 읽기 전용 맥락으로 노출한다 (데이터는 리소스, 행위는 도구 — MCP 모범 사례).

**반환**: `CaseDetail`의 사람이 읽는 표현 + 최근 코멘트.

**보안**: `parent`와 `case_id`에 경로 이탈 방지 검증을 적용한다. FastMCP 4는 리소스 템플릿에 기본 경로 이탈 보호를 제공하지만, 두 세그먼트 모두 형식 검증을 추가로 건다.

---

## Prompts

### `triage_open_cases`

인자: `parents: list[str] | None`

열린 케이스를 훑고 우선순위·최근 활동 기준으로 무엇부터 볼지 정리하게 하는 프롬프트. **SC-001**("한 번의 요청으로 파악")을 직접 겨냥한다.

### `draft_case_from_incident`

인자: `incident_notes: str`, `parent: str | None`

장애 메모를 받아 분류 검색 → 제목·본문·우선순위 초안 → `create_case` 호출까지 안내하는 프롬프트. **SC-002**("3분 이내 제출")를 직접 겨냥한다.

---

## 계약 테스트 체크리스트

`/speckit-tasks`가 아래를 테스트 과제로 전개한다.

- [ ] 14개 도구가 모두 등록되고, 이름·태그·`annotations`가 이 문서와 일치한다
- [ ] 8개 읽기 도구에 `readOnlyHint=true`, 2개 파괴적 도구(`close_case`, `escalate_case`)에 `destructiveHint=true`
- [ ] 구독 관련 도구가 **하나도 등록되지 않는다** (spec.md Clarifications 2026-09-01)
- [ ] `ENABLE_ESCALATION` 기본값에서 `escalate_case`가 `tools/list`에 **없다** (FR-018)
- [ ] `ENABLE_WRITES=false`에서 6개 쓰기 도구가 모두 사라진다 (FR-018)
- [ ] 모든 쓰기 도구의 라운드 1이 `InputRequiredResult`를 반환하고 상류 호출 횟수가 0이다
- [ ] `action="decline"` 라운드 2에서 상류 호출 횟수가 0이다 (FR-017)
- [ ] `action="accept"` 라운드 2가 `request_state`의 페이로드를 **바이트 단위로 동일하게** 전송한다 (FR-016)
- [ ] elicitation 미지원 클라이언트에서 쓰기 도구가 변경 없이 거부하고 사유를 안내한다 (FR-019)
- [ ] handshake era 연결에서 `ctx.elicit()` 경로가 동작한다 (R-003)
- [ ] 3개 parent 중 1개가 `PermissionDenied`일 때 나머지 2개 결과가 반환되고 `scopes_failed`에 1건이 실린다 (R-004b)
- [ ] 403의 세 원인이 각각 `permission_denied` / `support_plan_required` / `api_not_enabled`로 갈리고 서로 다른 조치를 안내한다 (R-007)
- [ ] **매핑되지 않는 예외가 `unknown`으로 분류되고, 빈 문구나 원본 예외 문자열이 아니라 다음 조치를 담은 기본 안내를 반환한다** (FR-021·SC-006 전수 기준)
- [ ] gRPC 경로와 미디어 HTTP 경로가 **같은 상태 코드에 같은 `ErrorKind`와 같은 안내 문구**를 낸다 (R-007 두 번째 원천)
- [ ] 복합 커서 라운드트립, 소진 parent 생략, parent 집합 불일치 거부, 손상 입력 거부
- [ ] `download_attachment` 결과에 바이트가 없고 `local_path`의 파일이 실제로 존재한다 (FR-014, FR-022)
- [ ] `create_case`가 유효하지 않은 `classification_id`에 대해 확인을 묻지 않고 거부한다 (FR-009)
- [ ] 모든 `CaseSummary`/`CaseDetail`에 `console_url`이 있거나, 파싱 실패 시 `None`이되 호출은 성공한다 (FR-023)
- [ ] 로그 출력에 케이스 본문·코멘트 본문·첨부 파일명이 나타나지 않는다 (FR-022)
