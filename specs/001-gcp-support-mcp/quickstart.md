# Phase 1 Quickstart & Validation Guide

**Feature**: `001-gcp-support-mcp` | **Date**: 2026-09-01 | **Plan**: [plan.md](./plan.md)

구현이 끝났을 때 이 문서의 시나리오가 전부 통과하면 기능이 완성된 것이다. 각 시나리오는 spec의 User Story / Success Criteria로 추적된다.

---

## Prerequisites

1. **Python 3.14** 이상, `uv` 설치
2. **유료 Google Cloud 지원 플랜** (Standard / Enhanced / Premium) — 미가입 조직은 조회조차 되지 않는다 (R-005)
3. **IAM 역할** — 최소 `roles/cloudsupport.techSupportViewer`, 쓰기 검증에는 `roles/cloudsupport.techSupportEditor`. 조직 수준 조회는 `resourcemanager.organizations.get`도 필요하다
4. **Cloud Support API 활성화**:
   ```bash
   gcloud services enable cloudsupport.googleapis.com --project=<PROJECT_ID>
   ```
5. **ADC 및 quota project**:
   ```bash
   gcloud auth application-default login
   gcloud auth application-default set-quota-project <PROJECT_ID>
   ```

---

## Setup

```bash
uv sync
uv run pytest tests/unit tests/contract    # 네트워크 불필요 — 여기서 먼저 통과해야 한다
```

**설정** (환경변수, 접두사 `CLOUD_SUPPORT_MCP_`). 전체 항목은 [data-model.md](./data-model.md)의 Configuration 표 참조.

```bash
export CLOUD_SUPPORT_MCP_PARENTS='["projects/my-project","organizations/123456789"]'
export CLOUD_SUPPORT_MCP_QUOTA_PROJECT=my-project
```

**실행**:
```bash
uv run cloud-support-mcp          # stdio (기본)
```

**MCP 클라이언트 등록**:
```json
{
  "mcpServers": {
    "cloud-support": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cloud-support-mcp", "cloud-support-mcp"],
      "env": {
        "CLOUD_SUPPORT_MCP_PARENTS": "[\"projects/my-project\"]",
        "CLOUD_SUPPORT_MCP_QUOTA_PROJECT": "my-project"
      }
    }
  }
}
```

---

## ⚠️ 쓰기 시나리오 실행 조건

**V4와 V5는 Google Support API에 케이스와 첨부를 만든다.** `test_case: true`로 수행하면 레코드는 남지만 **지원 엔지니어에게 라우팅되지 않으므로** 수행해도 된다.

두 가지는 지킨다:

1. **`test_case: true` 없이 케이스를 만들지 않는다.** 그러면 실제 지원 티켓이 되어 엔지니어에게 전달된다.
2. **에스컬레이션(V4 확장)은 실행하지 않는다.** 대상이 테스트 케이스여도 Google 지원 조직에 직접 전달되는 조치다. 검증은 계약 테스트로 한다.

나머지 시나리오(V1·V2·V3·V6·V7·V8·V9)는 읽기 전용이거나 목 기반이다.

## Validation Scenarios

### V1 — 도구 표면 (계약)

```bash
uv run fastmcp inspect src/cloud_support_mcp/server.py
```

**기대**:
- 기본 설정에서 **13개** 도구가 보인다. `escalate_case`는 **보이지 않는다** (FR-018 기본 비활성).
- 읽기 도구 8개에 `readOnlyHint: true`.
- `close_case`에 `destructiveHint: true`. 구독 관련 도구는 **하나도 보이지 않는다**.
- 리소스 템플릿 `case://{parent}/{case_id}` 1개, 프롬프트 2개.

```bash
CLOUD_SUPPORT_MCP_ENABLE_ESCALATION=true uv run fastmcp inspect src/cloud_support_mcp/server.py
# → 14개 도구, escalate_case에 destructiveHint: true

CLOUD_SUPPORT_MCP_ENABLE_WRITES=false uv run fastmcp inspect src/cloud_support_mcp/server.py
# → 8개 도구 (읽기만)
```

**추적**: FR-018, FR-019 / contracts 체크리스트 1~4번

---

### V2 — 케이스 조회 (spec US1 / P1)

MCP Inspector 또는 어시스턴트에서:

1. `search_cases` (인자 없음) → `ListEnvelope[CaseSummary]`. 각 항목에 `ref.console_url`이 있다.
2. 반환된 `ref.name`으로 `get_case` → `CaseDetail`. `description`이 있고, `state`가 5개 응답 어휘 중 하나다.
3. 같은 이름으로 `list_comments` → 시간 순 코멘트. 각 항목의 `author_side`가 `customer` 또는 `google_support`다.
4. `list_attachments` → 메타데이터만. **`body`/바이트 필드가 없다.**

**추적**: US1 AS-1~3, FR-001·003·004·005·023 / **SC-001**

---

### V3 — Cross-org 팬아웃과 부분 실패 (사용자 요청의 핵심)

접근 권한이 **있는** parent와 **없는** parent를 함께 설정한다:

```bash
export CLOUD_SUPPORT_MCP_PARENTS='["projects/my-project","organizations/999999999"]'
```

`search_cases` 호출 →

**기대**:
- 호출이 **성공한다** (실패가 아니다).
- `items`에 접근 가능한 프로젝트의 케이스가 들어 있다.
- `scopes_queried`에 두 parent가 모두 있다.
- `scopes_failed`에 1건 — `parent: "organizations/999999999"`, `reason: "permission_denied"`(또는 `support_plan_required`), `retryable: false`, 그리고 다음 조치 안내.

**이것이 실패하면 cross-org 요구가 충족되지 않은 것이다.** 하나의 403이 전체를 죽이는 것이 가장 흔한 회귀다.

**페이지네이션**: `page_size=1`로 호출해 `next_cursor`를 받고 그대로 다시 호출한다. 결과가 이어지고 중복이 없어야 한다. 그 뒤 `parents`를 바꿔 같은 커서로 호출하면 **거부되어야** 한다.

**추적**: R-004, FR-002·007·021 / data-model 복합 커서

---

### V4 — 확인 절차 (spec US2·US3 / FR-016·FR-017)

**⚠️ 이 시나리오는 케이스를 만든다. 반드시 `test_case: true`로 수행할 것** — 그래야 지원 엔지니어에게 라우팅되지 않는다. `test_case`를 빠뜨리면 실제 지원 티켓이 된다.

1. `search_case_classifications`에 제품 키워드 → 후보 목록. `id` 하나를 고른다.
2. `create_case`를 `test_case: true`로 호출 →
   - **케이스가 만들어지지 않는다.**
   - 제출될 전체 페이로드를 담은 확인 요청이 돌아온다.
3. **거절**한다 → 아무 것도 만들어지지 않는다. `search_cases`로 확인.
4. 다시 호출하고 **승인**한다 → `CaseDetail` 반환, `console_url`로 열면 2단계에서 본 내용과 정확히 일치한다.
5. 잘못된 `classification_id`로 `create_case` → **확인을 묻지 않고** 즉시 거부되며 후보 목록이 온다 (FR-009).
6. 만든 케이스에 `add_comment` → 확인 요청 → 승인 → `list_comments`에 나타난다.
7. `close_case` → 확인 요청에 **되돌릴 수 없음**이 명시된다 → 승인 → `state: CLOSED`.

**추적**: US2 AS-1~4, US3 AS-1~2, FR-008~012, FR-016, FR-017 / **SC-002, SC-004, SC-005**

---

### V5 — 첨부 파일 (FR-014 / FR-015 / FR-022)

1. `upload_attachment`로 작은 텍스트 파일 → 확인 요청에 파일명·크기·대상 케이스가 있고 **파일 내용은 없다** → 승인 → `Attachment`.
2. `list_attachments` → 방금 올린 파일이 보인다.
3. `download_attachment` → `DownloadedAttachment`.
   - **결과에 바이트가 없다.**
   - `local_path`의 파일이 실제로 존재하고 원본과 내용이 같다.
4. 같은 파일을 다시 다운로드 → 덮어쓰지 않고 접미사가 붙은 새 경로.

**추적**: FR-014, FR-015, FR-022 / R-002

---

### V6 — 오류 안내 (FR-021 / SC-006)

각각을 유발해 안내 문구를 확인한다:

| 유발 방법 | 기대 분류 | 안내에 포함될 것 |
|-----------|-----------|------------------|
| 권한 없는 parent | `permission_denied` | 필요한 역할과 부여 수준 |
| 지원 플랜 미가입 조직 | `support_plan_required` | Standard 이상 필요 — **권한 오류와 다른 문구** |
| `gcloud auth application-default revoke` 후 호출 | `unauthenticated` | `gcloud auth application-default login` |
| 존재하지 않는 케이스 이름 | `not_found` | 이름 형식과 parent 확인 |
| 이미 닫힌 케이스에 `close_case` | `failed_precondition` | 현재 상태 |
| 매핑되지 않는 예외 (목으로 유발) | `unknown` | **빈 문구가 아닌** 다음 조치 기본 안내 |

**핵심 두 가지**: (1) 첫 두 행이 서로 다른 문구를 내야 한다 — 둘 다 403이지만 사용자가 할 일이 전혀 다르다. (2) 마지막 행이 SC-006의 전수 기준이다 — 분류되지 않은 실패에도 안내가 있어야 하며, 여기서 비면 SC-006은 미달이다.

**추적**: FR-021 / **SC-006**

---

### V7 — 데이터 유출 방지 (FR-022)

```bash
FASTMCP_LOG_LEVEL=DEBUG uv run cloud-support-mcp 2> server.log
# V2·V4 시나리오 수행 후:
grep -iE "<케이스 본문 일부>|<코멘트 본문 일부>" server.log   # 매치 0건이어야 한다
```

로그에는 도구 이름·소요 시간·결과 종류만 있어야 한다.

**추적**: FR-022 / spec Edge Case

---

### V8 — 프로토콜 era 호환 (R-003)

- **Modern (`2026-07-28`)**: V4가 `InputRequiredResult` 경로로 통과한다.
- **Handshake (`2025-11-25` 이하)**: 해당 era 클라이언트로 붙어 V4를 반복 — `ctx.elicit()` 경로로 통과해야 한다.
- **elicitation 미지원 클라이언트**: 쓰기 도구가 **변경 없이** 거부하고 사유를 안내한다 (FR-019).

**추적**: R-003, FR-016, FR-019 / contracts 체크리스트 5~9번

---

### V9 — 첫 사용자 경험 (SC-008)

문서를 읽지 않은 사람에게 README와 이 파일의 Prerequisites만 주고 측정한다: 자격 증명 설정 → 첫 `search_cases` 성공까지 **10분 이내**.

특히 `PARENTS` 미설정 상태의 오류 문구가 무엇을 설정해야 하는지 스스로 알려주는지 확인한다 — 이것이 이 시나리오의 가장 흔한 실패 지점이다.

**추적**: **SC-008**

---

## Integration Test Suite

```bash
# 읽기 전용 통합 테스트만
export CLOUD_SUPPORT_MCP_IT_PARENT=projects/my-test-project
uv run pytest tests/integration -v

# 쓰기 통합 테스트까지 (실제 케이스가 생성된다 — 의도적으로만)
export CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1
uv run pytest tests/integration -v
```

`CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES`가 없으면 쓰기 통합 테스트는 **전부 skip된다.** 이중 게이트는 "통합 테스트를 켰더니 케이스가 생겼다"를 막기 위한 것이다.

`CLOUD_SUPPORT_MCP_IT_PARENT`가 없으면 통합 테스트 전부가 skip된다. 쓰기 테스트는 `CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1`을 추가로 요구하며, 실행 시 `test_case=True`를 쓰고 만든 케이스를 종료해 정리한다 — 다만 **정리해도 레코드 자체는 남는다.**

---

## Done Criteria

- [x] V1·V2·V3·V6·V7·V8 — 2026-09-01 실 API 확인 완료
- [ ] V4·V5 — 유료 지원 플랜이 있는 프로젝트 필요. 절차는 [deferred.md](./deferred.md)
- [ ] V9 — 사람이 측정. 절차는 [deferred.md](./deferred.md)
- [ ] `uv run pytest` 전체 통과 (unit + contract; integration은 자격 증명 있을 때)
- [ ] [contracts/tools.md](./contracts/tools.md)의 계약 테스트 체크리스트 19항목 전부 통과
- [ ] 범위 내 13개 RPC + 2개 미디어 엔드포인트가 14개 도구로 모두 도달 가능 (**SC-007**)
- [ ] README에 미커버 두 가지(`SupportEventSubscriptionService` 범위 밖, `v2beta` `FeedService.ShowFeed`)가 명시되어 있다
