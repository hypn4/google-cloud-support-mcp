# Phase 1 Data Model: Google Cloud Support MCP

**Feature**: `001-gcp-support-mcp` | **Date**: 2026-09-01 | **Plan**: [plan.md](./plan.md)

이 문서는 `models.py`의 pydantic 모델과 `serializers.py`의 변환 규칙을 정의한다. 이 모델들이 곧 도구의 `output_schema`가 되므로, 여기 없는 필드는 클라이언트에 노출되지 않는다.

원천 필드는 `google-cloud-support 0.5.3` 휠 내부 proto 정의에서 직접 확인했다(R-001, R-008).

---

## 설계 규칙

1. **proto를 그대로 흘리지 않는다.** enum은 문자열 이름으로, `Timestamp`는 ISO-8601 문자열로 변환한다. 클라이언트가 `{"state": 3}` 같은 정수를 해석하게 두지 않는다.
2. **모든 케이스 참조는 파싱된 형태와 콘솔 URL을 동반한다** (FR-023).
3. **목록 응답의 케이스는 요약형이고, 단건 조회만 전문형이다.** 20건 목록에 본문 전문을 실으면 대화 맥락이 무너진다.
4. **모든 목록 응답은 `scopes_queried` / `scopes_failed`를 갖는다** (FR-021, R-004b). 팬아웃을 쓰지 않는 단일 parent 호출에서도 형태를 통일한다.

---

## Core Entities

### `ResourceRef`

모든 케이스·코멘트·첨부 참조에 공통으로 붙는 주소 정보. spec의 **Parent Scope** 엔티티를 구체화한다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | `str` | Google 정식 리소스 이름 (`projects/p/cases/123`) |
| `parent` | `str` | `projects/{id}` 또는 `organizations/{id}` |
| `parent_type` | `"project" \| "organization"` | 파싱 결과 |
| `case_id` | `str` | 케이스 숫자 ID |
| `console_url` | `str` | FR-023. 프로젝트: `…/support/cases/detail/{id}?project={p}`, 조직: `…?organizationId={o}` |

**검증**: `name`이 `(projects|organizations)/{id}/cases/{case_id}` 패턴에 맞지 않으면 파싱 실패로 처리하고, `console_url`은 `None`이 되며 `name`은 그대로 보존한다. 링크 생성 실패가 조회 자체를 실패시켜서는 안 된다.

---

### `CaseSummary` — 목록·검색 응답 요소

spec의 **Support Case** 엔티티, 요약형.

| 필드 | 타입 | 원천 | 비고 |
|------|------|------|------|
| `ref` | `ResourceRef` | `Case.name` | |
| `title` | `str` | `Case.display_name` | |
| `state` | `CaseState` | `Case.state` | 아래 enum |
| `priority` | `CasePriority` | `Case.priority` | 아래 enum |
| `escalated` | `bool` | `Case.escalated` | |
| `create_time` | `str` (ISO-8601) | `Case.create_time` | |
| `update_time` | `str` (ISO-8601) | `Case.update_time` | 최근 활동 판단용 |
| `creator_email` | `str \| None` | `Case.creator.email` | |
| `classification` | `str \| None` | `Case.classification.display_name` | |
| `test_case` | `bool` | `Case.test_case` | 통합 테스트가 만든 케이스 식별 |

`description`은 **요약형에 포함하지 않는다.** 본문은 `get_case`로만 얻는다.

---

### `CaseDetail` — 단건 조회 응답

`CaseSummary`의 모든 필드에 더해:

| 필드 | 타입 | 원천 |
|------|------|------|
| `description` | `str` | `Case.description` |
| `classification_id` | `str \| None` | `Case.classification.id` — 유사 케이스 생성 시 재사용 |
| `contact_email` | `str \| None` | `Case.contact_email` |
| `subscriber_emails` | `list[str]` | `Case.subscriber_email_addresses` |
| `time_zone` | `str \| None` | `Case.time_zone` |
| `language_code` | `str \| None` | `Case.language_code` |

---

### `Comment`

spec의 **Case Comment** 엔티티.

| 필드 | 타입 | 원천 | 비고 |
|------|------|------|------|
| `name` | `str` | `Comment.name` | |
| `create_time` | `str` (ISO-8601) | `Comment.create_time` | |
| `author_display_name` | `str \| None` | `Comment.creator.display_name` | |
| `author_email` | `str \| None` | `Comment.creator.email` | |
| `author_side` | `"customer" \| "google_support"` | `Comment.creator.google_support` | **spec AS1-3이 요구하는 작성자 구분** |
| `body` | `str` | `Comment.body` | 원문 그대로. 최대 12,800자 |

`Comment.plain_text_body`는 **쓰지 않는다** — proto가 `Output only. DEPRECATED. DO NOT USE.`로 표시한 `body`의 중복 필드다(휠 직접 확인).

`author_side`가 이 모델의 핵심이다 — Actor의 boolean 플래그를 사용자가 읽을 수 있는 구분으로 바꾼다.

---

### `Attachment`

spec의 **Case Attachment** 엔티티. **바이트는 담지 않는다** (R-002, FR-022).

| 필드 | 타입 | 원천 |
|------|------|------|
| `name` | `str` | `Attachment.name` — 다운로드 시 이 값을 쓴다 |
| `filename` | `str` | `Attachment.filename` |
| `mime_type` | `str \| None` | `Attachment.mime_type` |
| `size_bytes` | `int` | `Attachment.size_bytes` |
| `create_time` | `str` (ISO-8601) | `Attachment.create_time` |
| `creator_display_name` | `str \| None` | `Attachment.creator.display_name` |

### `DownloadedAttachment` — `download_attachment` 응답

| 필드 | 타입 | 설명 |
|------|------|------|
| `attachment_name` | `str` | 원본 리소스 이름 |
| `local_path` | `str` | 저장된 절대 경로 — **FR-014가 요구하는 반환값** |
| `size_bytes` | `int` | 실제 기록된 바이트 수 |
| `mime_type` | `str \| None` | 응답 헤더 기준 |

---

### `Classification`

spec의 **Case Classification** 엔티티.

| 필드 | 타입 | 원천 | 비고 |
|------|------|------|------|
| `id` | `str` | `CaseClassification.id` | `create_case`에 넘길 값 |
| `display_name` | `str` | `CaseClassification.display_name` | 사람이 읽는 계층 경로 |

**검증 (FR-009)**: `create_case`는 넘어온 `classification_id`를 `SearchCaseClassifications` 결과와 대조한다. 불일치 시 케이스를 만들지 않고, 사유와 함께 후보 목록을 반환한다.

---

## Enumerations

### `CaseState` (응답 어휘)

`STATE_UNSPECIFIED` · `NEW` · `IN_PROGRESS_GOOGLE_SUPPORT` · `ACTION_REQUIRED` · `SOLUTION_PROVIDED` · `CLOSED`

### `CaseStateFilter` (쿼리 어휘)

`OPEN` · `CLOSED`

**두 어휘는 다르다** (R-008). 검색 쿼리 문법은 `OPEN`/`CLOSED` 두 값만 받지만 응답 `state`는 5개 값을 갖는다. `search_cases`의 입력은 `CaseStateFilter`, 출력은 `CaseState`이며 도구 설명에 이 차이를 명시한다. `OPEN`은 `CLOSED`가 아닌 모든 상태를 포괄한다.

### `EscalationReason`

`REASON_UNSPECIFIED` · `RESOLUTION_TIME` · `TECHNICAL_EXPERTISE` · `BUSINESS_IMPACT`

`escalate_case`의 필수 입력. 값은 `escalation.py` proto에서 확인했다. `REASON_UNSPECIFIED`는 입력으로 받지 않는다.

### `CasePriority`

`PRIORITY_UNSPECIFIED` · `P0`(가장 긴급) · `P1` · `P2` · `P3` · `P4`(가장 낮음)

숫자가 클수록 긴급도가 **낮다**. 직관과 반대이므로 도구 설명에 명시한다.

---

## Fan-out Envelope

모든 목록·검색 응답의 공통 봉투 (R-004b). 이 봉투가 spec Edge Case "한 parent만 권한이 없는 경우"를 표현 가능하게 만든다.

### `ScopeFailure`

| 필드 | 타입 | 설명 |
|------|------|------|
| `parent` | `str` | 실패한 parent |
| `reason` | `ErrorKind` | 아래 분류 |
| `detail` | `str` | 사용자에게 보일 다음 조치 |
| `retryable` | `bool` | 재시도로 해결 가능한지 |

### `ErrorKind` (R-007 매핑 표와 1:1)

`permission_denied` · `support_plan_required` · `api_not_enabled` · `unauthenticated` · `not_found` · `invalid_argument` · `failed_precondition` · `rate_limited` · `unavailable` · `unknown`

**403이 세 값으로 갈리는 것이 이 enum의 요점이다.** `permission_denied`(역할 부여), `support_plan_required`(지원 계약 구매), `api_not_enabled`(`gcloud services enable`) — 전부 HTTP 403으로 도착하지만 사용자가 할 일이 전혀 다르다. 세 번째는 2026-09-01 실 API 호출에서 발견했다.

**`unknown`은 "안내 없음"이 아니다.** spec.md Clarifications(2026-09-01)로 FR-021과 SC-006이 전수 기준이 되면서, 매핑되지 않은 실패도 사용자가 다음에 무엇을 시도해야 하는지 알 수 있는 기본 안내를 담아야 한다. `detail`이 비었거나 원본 예외 문자열을 그대로 옮긴 `unknown`은 SC-006 미달이다.

### `ListEnvelope[T]`

| 필드 | 타입 | 설명 |
|------|------|------|
| `items` | `list[T]` | 병합된 결과 |
| `scopes_queried` | `list[str]` | 실제 조회한 parent |
| `scopes_failed` | `list[ScopeFailure]` | 실패한 parent별 사유 — **비어 있지 않아도 호출은 성공이다** |
| `next_cursor` | `str \| None` | 아래 복합 커서. 모든 parent 소진 시 `None` |
| `truncated` | `bool` | 더 남아 있는지 (FR-007이 요구하는 "더 남아 있음" 신호) |

---

## Composite Cursor

**형식**: base64url로 인코딩된 JSON.

```json
{"v": 1, "cursors": {"projects/a": "<google-token>", "organizations/b": null}}
```

**규칙**:
- `null` = 해당 parent 소진. 다음 라운드에서 호출하지 않는다.
- 모든 값이 `null`이면 커서를 발급하지 않고 `next_cursor = None`, `truncated = false`.
- `v`는 형식 버전. 모르는 버전은 거부한다.
- 커서에 담긴 parent 집합이 현재 요청의 parent 집합과 다르면 거부한다 — 페이지 중간에 범위가 바뀌면 결과가 조용히 어긋난다.
- 클라이언트에는 **불투명 문자열**로만 노출한다. 내부 구조를 도구 설명에 쓰지 않는다.

**Unit 테스트 대상**: 라운드트립, 소진 parent 생략, 손상된 base64, 알 수 없는 `v`, parent 집합 불일치.

---

## Confirmation State

`request_state`에 봉인되어 라운드 간 이동하는 페이로드 (R-003, FR-016/FR-017).

| 필드 | 타입 | 설명 |
|------|------|------|
| `tool` | `str` | 확인을 요청한 도구 이름 |
| `payload` | `dict` | 실행될 요청의 **완전한** 인자 |
| `preview` | `str` | 라운드 1에서 사용자에게 보여준 문장 |
| `issued_at` | `str` (ISO-8601) | 발급 시각 |

**불변 조건**: 라운드 2는 `payload`를 **재구성하지 않고 그대로 실행한다.** 재구성하면 사용자가 승인한 것과 실행되는 것이 갈라질 수 있다. `request_state`는 프레임워크가 봉인·검증하므로, 이 불변 조건이 관례가 아니라 메커니즘으로 지켜진다.

`tool`은 한 도구의 확인 토큰이 다른 도구에서 재사용되는 것을 막는다 — 라운드 2에서 실행 도구와 `tool`이 다르면 거부한다.

---

## Configuration

`pydantic-settings`, 접두사 `GOOGLE_CLOUD_SUPPORT_MCP_`. 8개 항목.

| 설정 | 타입 | 기본값 | 근거 |
|------|------|--------|------|
| `PARENTS` | `list[str]` | `[]` | 팬아웃 대상. 비어 있으면 조회 도구가 설정 방법을 안내 (R-004) |
| `QUOTA_PROJECT` | `str \| None` | `None` | 조직 수준 + 사용자 ADC 조합에 필요 (R-005) |
| `ENABLE_WRITES` | `bool` | `true` | FR-018 — 쓰기 전체 토글 |
| `ENABLE_ESCALATION` | `bool` | **`false`** | FR-018 — 명시적으로 기본 비활성 |
| `DOWNLOAD_DIR` | `Path` | 시스템 임시 디렉터리 | FR-014 |
| `MAX_UPLOAD_BYTES` | `int` | `10_000_000` | 문서에 상한 명시 없음 (research 미해결 3) |
| `DEFAULT_PAGE_SIZE` | `int` | `20` | 대화 맥락 보호 |
| `FANOUT_CONCURRENCY` | `int` | `5` | 상류 요청 한도 노출 제한 (R-004c) |

**검증**: `PARENTS`의 각 항목은 `projects/{id}` 또는 `organizations/{id}` 형식이어야 한다. 잘못된 항목은 기동 시점에 거부한다 — 첫 도구 호출까지 미루면 원인 파악이 어려워진다.
