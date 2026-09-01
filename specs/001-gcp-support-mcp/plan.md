# Implementation Plan: Google Cloud Support MCP

**Branch**: `001-gcp-support-mcp` | **Date**: 2026-09-01 (rev. 3 — 헌법 v1.0.0 준수 반영) | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-gcp-support-mcp/spec.md`

## Summary

Google Cloud Support API v2의 **케이스·코멘트·첨부·분류 표면(13개 gRPC RPC + 2개 미디어 HTTP 엔드포인트)** 을 14개 MCP 도구, 리소스 템플릿, 프롬프트로 노출하는 FastMCP 4 서버. `SupportEventSubscriptionService`는 spec.md Clarifications(2026-09-01)에 따라 범위 밖이다. MCP `2026-07-28` 스펙을 대상으로 하며, 쓰기 동작은 FastMCP 4의 다중 라운드 입력 패턴(`InputRequiredResult`)으로 **사용자 본인의** 확인을 받는다.

핵심 기술 판단 세 가지 (근거는 [research.md](./research.md)):

1. **Cross-org는 클라이언트 측 팬아웃으로 구현한다.** v2beta가 쿼리 안에서 `organization=`을 받지만, 공식 문서 확인 결과 `OR`로 여러 조직을 묶는 문법이 없다. 어느 API 버전이든 1회 호출 = 1개 parent다. 따라서 설정된 parent 목록에 병렬 호출 후 병합하며, **v2 안정 버전을 쓰고 v2beta는 채택하지 않는다.**
2. **첨부 파일 바이트는 SDK에 없다.** GAPIC 클라이언트에는 `GetAttachment`/`ListAttachments`(메타데이터)만 있다. 업로드·다운로드는 `httpx.AsyncClient` + `google-auth` 토큰으로 REST 직접 호출한다.
3. **`ctx.elicit()`는 FastMCP 4의 modern 연결에서 제거되었다.** 확인 절차는 `InputRequiredResult` + `ctx.input_responses`로 구현하고, 전송될 페이로드 원본을 프레임워크가 봉인하는 `request_state`에 실어 라운드 간 전달한다. 이로써 FR-016/FR-017이 관례가 아니라 메커니즘으로 보장된다.

## Technical Context

**Language/Version**: Python 3.14 (`requires-python = ">=3.14"`, 기존 `pyproject.toml` 유지)

**Primary Dependencies** — 모든 핀은 **2026-09-01 PyPI에서 확인**했다(헌법 원칙 IV: 정확한 값 + 확인 시점 기록). 구현 착수 시 T001이 재확인한다.

*직접 선언 (`pyproject.toml`)*:

| 패키지 | 핀 | 용도 |
|--------|-----|------|
| `fastmcp` | `== 4.0.0` | MCP 서버 프레임워크 (MCP `2026-07-28` 대응) |
| `google-cloud-support` | `== 0.5.3` | v2 GAPIC 비동기 클라이언트 (gRPC asyncio) |
| `httpx` | `== 0.28.1` | 첨부 업로드/다운로드 REST 호출 (SDK 미커버 구간) |
| `pydantic-settings` | `== 2.15.0` | 환경변수 설정 |

*전이 의존성 — 사용하지만 **직접 선언하지 않는다*** (헌법 Technology 표준: "전이 의존성을 직접 선언하지 않는다"):

| 패키지 | 어디서 오는가 | 용도 |
|--------|---------------|------|
| `google-auth` | `google-cloud-support`가 `>=2.14.1` 요구 | ADC 자격 증명, 미디어 REST 베어러 토큰 |
| `pydantic` | `fastmcp`가 요구 | 출력 모델 |
| `mcp` | `fastmcp-slim`이 자체 핀 보유 | 프로토콜 타입 |
| `grpcio` | `google-cloud-support`가 py3.14에서 `>=1.75.1` 요구 | gRPC 전송 |

**Storage**: N/A — 케이스 데이터를 저장·캐시하지 않는다(spec Assumptions). 유일한 디스크 쓰기는 FR-014의 첨부 다운로드 대상 디렉터리다.

**Testing**: `pytest==9.1.1` + `pytest-asyncio==1.4.0` + `respx==0.23.1`(미디어 REST 경로의 httpx 목킹), 린트·포맷은 `ruff==0.16.5` — dev 의존성도 정확한 값으로 고정한다(2026-09-01 확인). 3계층 — unit(순수 로직), contract(FastMCP 인메모리 `Client` + 목 GAPIC 클라이언트 + `respx`), integration(실제 프로젝트, 환경변수로 opt-in, `test_case=True`로 한정).

**Target Platform**: 사용자 워크스테이션의 로컬 프로세스. 기본 전송은 stdio. HTTP 전송은 코드상 지원하되 v1의 검증 대상은 stdio다.

**Project Type**: 단일 Python 패키지 — MCP 서버 (라이브러리 + 콘솔 스크립트 진입점)

**Performance Goals**: 팬아웃 지연이 지배적이다. N개 parent 조회는 순차합이 아니라 **가장 느린 parent 1개 수준**이어야 한다(동시성 상한 기본 5). SC-001("한 번의 요청으로 파악")이 이 목표의 사용자 측 표현이다. 요청 처리량 목표는 없다 — 단일 사용자 로컬 서버다.

**Constraints**:
- 도구 결과는 대화 맥락에 들어간다. 목록 응답은 기본 페이지를 작게(기본 20건) 잡고 케이스 본문 전문이 아니라 요약을 싣는다.
- 첨부 파일 바이트는 절대 도구 결과로 반환하지 않는다(FR-022 + 맥락 보호).
- `mask_error_details=True` — 매핑을 거친 `ToolError`만 클라이언트에 도달한다.
- 팬아웃 중 한 parent의 실패가 전체 호출을 실패시키지 않는다.

**Scale/Scope**: 14개 도구 — 읽기 8 / 쓰기 6 (범위 내 v2 RPC 13개 + 미디어 2개를 커버), 1개 리소스 템플릿, 2개 프롬프트. 설정된 parent 수는 실사용 기준 1~20개 규모를 상정한다.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**상태: 5개 원칙 전부 통과. 위반 0건.**

헌법 `v1.0.0`(2026-09-01 제정) 기준. 이 계획은 헌법보다 먼저 작성되었으므로 소급 점검이며, 원칙별 통과 근거를 명시한다 — 헌법 Governance가 "위반 없음"만으로는 부족하다고 규정한다.

> **rev. 3 갱신 이력**: rev. 2의 점검은 원칙 II·IV·V를 통과로 판정했으나 `/speckit-analyze`가 세 건의 실제 미충족을 찾아냈다 — 무핀 의존성 2건, 착수 전 버전 재확인 과제 부재, 신규 의존성 deprecated 점검 부재, ruff 실행 게이트 부재. rev. 3은 그 넷을 해소한 뒤의 판정이다. 특히 rev. 2가 원칙 IV의 근거로 든 "핀은 정확한 값(`==`)이다"는 4개 런타임 의존성 중 2개에만 해당하는 **부정확한 서술**이었다.

| 원칙 | 판정 | 통과 근거 |
|------|------|-----------|
| **I. Ground Data Only** (NON-NEGOTIABLE) | **PASS** | research.md의 각 결정이 검증 방법을 명시한다 — 휠 직접 해제 후 `gapic_metadata.json`·proto 파싱, 공식 문서 `.md.txt` 원문 확인. 요약본이 원문과 어긋난 **3건을 기록하고 원문을 채택**했다: v2beta가 `OR`로 여러 조직을 검색한다는 오해(R-004), 첨부 업로드 파일명이 쿼리 파라미터라는 오해(R-002), `plain_text_body`가 사용 가능하다는 오해(R-008). 미해결 4건은 research.md 말미에 설계 영향과 함께 기록되어 있다 |
| **II. Code Conventions** | **PASS** | 강제 수단과 실행 게이트를 모두 갖췄다 — T006이 ruff 설정 후 `ruff check`·`ruff format --check` **통과를 확인**하고, T085가 최종 게이트에서 다시 확인하며, tasks.md Notes가 **커밋 전 통과**와 **소스 `TODO`의 과제 ID 참조**를 규칙으로 명시한다. 출력은 임시 `dict`가 아니라 data-model.md에 선언된 pydantic 모델(T012·T013)이다. 소스가 아직 빈 `__init__.py` 하나뿐이므로 실효 검증은 구현 단계에서 이뤄진다 |
| **III. Test-First** (NON-NEGOTIABLE) | **PASS** | tasks.md의 세 스토리 모두 테스트 블록이 구현 블록보다 **앞에** 있고, 각 블록 머리에 "먼저 작성하고 실패를 확인한 뒤 구현한다"가 명시되어 있다. contracts/tools.md의 계약 테스트 19항목이 전부 과제로 인용된다. 네트워크 테스트는 `integration` 마커로 기본 제외(T007)되고 `GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT`로만 활성화된다. 외부 부작용은 벤더 테스트 모드(`test_case=True`)로 한정된다 |
| **IV. Latest Spec First** | **PASS** | **런타임 의존성 4개 전부 정확한 값으로 고정**되고(`fastmcp==4.0.0`, `google-cloud-support==0.5.3`, `httpx==0.28.1`, `pydantic-settings==2.15.0`), dev 의존성 4개도 마찬가지다. 확인 시점(2026-09-01, PyPI)이 Technical Context와 T003·T004에 기록되어 있다. **T001이 구현 착수 전 레지스트리 재확인을 수행한다** — 기억에 의존하지 않는다. MCP `2026-07-28`은 공식 문서 트리의 최신 리비전이다. **v2beta 미채택이 이 원칙에 부합한다** — 원칙 IV는 베타 채택에 고유 능력의 정당화를 요구하는데, R-004가 v2beta에 고유 능력이 없음(cross-org 미해결)을 확인했다 |
| **V. No Deprecated Surfaces** (NON-NEGOTIABLE) | **PASS** | v2 proto **전수 검사** 결과 deprecated 표시 필드는 `Comment.plain_text_body`(`Output only. DEPRECATED. DO NOT USE.`) **하나뿐**이며, data-model.md가 이를 명시적으로 배제한다. FastMCP 4의 deprecated 항목도 어느 것도 쓰지 않는다 — `import_server()` 대신 명시적 등록, SSE 전송 대신 stdio/HTTP, `Client("server.py")` 문자열 추론 대신 인메모리 `Client(mcp)`. **T002가 신규 의존성 6종의 사용 예정 표면을 점검**하고 결과를 research.md에 기록한다 |

**Post-Phase 1 재확인**: 변동 없음. 설계 단계(data-model, contracts, quickstart)에서 새로 도입된 의존성이나 API 표면이 없어 원칙 IV·V의 재검사 대상이 발생하지 않았다.

## Project Structure

### Documentation (this feature)

```text
specs/001-gcp-support-mcp/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── tools.md         # Phase 1 output — MCP 도구 계약
├── checklists/
│   └── requirements.md  # /speckit-specify output
├── tasks.md             # /speckit-tasks output — NOT created here
└── deferred.md          # 실 API 검증이 남은 3건의 재개 절차
```

### Source Code (repository root)

```text
src/google_cloud_support_mcp/
├── __init__.py              # main() 진입점 (pyproject의 console script)
├── __main__.py              # python -m google_cloud_support_mcp
├── settings.py              # pydantic-settings: parents, 기능 토글, 다운로드 경로, quota project
├── server.py                # FastMCP 인스턴스 조립: lifespan, 미들웨어, 태그 게이팅, 등록 호출
├── auth.py                  # google.auth.default(), 스코프, quota project 헤더, 토큰 갱신
├── clients.py               # 3개 GAPIC AsyncClient + httpx.AsyncClient 번들 (lifespan 소유)
├── errors.py                # gRPC(api_core) + HTTP(httpx) 예외 → 공통 ErrorKind → ToolError (R-007)
├── confirm.py               # 이중 era 확인: InputRequiredResult / ctx.elicit 분기
├── fanout.py                # parent 목록 해석, 동시 실행, 병합, 복합 커서, 부분 실패 수집
├── media.py                 # 첨부 업로드/다운로드 REST (SDK 미커버 구간)
├── models.py                # pydantic 출력 모델 (도구 output_schema의 원천)
├── serializers.py           # proto → 출력 모델, 콘솔 URL 생성, state/priority enum 변환
├── redaction.py             # RedactionMiddleware — FR-022
├── resources.py             # case://{parent}/{case_id} 리소스 템플릿
├── prompts.py               # triage_open_cases, draft_case_from_incident
└── tools/
    ├── __init__.py          # register_all(mcp)
    ├── cases.py             # search_cases, get_case, create/update/escalate/close_case
    ├── classifications.py   # search_case_classifications
    ├── comments.py          # list_comments, get_comment, add_comment
    └── attachments.py       # list/get_attachment, download/upload_attachment

tests/
├── conftest.py              # 목 GAPIC 클라이언트, 인메모리 FastMCP Client 픽스처
├── unit/                    # 오류 매핑, 커서 라운드트립/위조, URL 생성, 직렬화
├── contract/                # 도구 목록·스키마·annotations·태그 게이팅, 확인 2라운드, 팬아웃 부분 실패
└── integration/             # 실제 API (GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT 있을 때만)
```

**Structure Decision**: 단일 Python 패키지. 도메인별 `tools/*.py` 모듈이 각각 `register(mcp)`를 노출하고 `server.py`가 명시적으로 호출한다. FastMCP 4가 모듈 분할용으로 제시하는 `FileSystemProvider`(디렉터리 런타임 스캔)는 채택하지 않았다 — 이 프로젝트는 임의 경로에 설치되어 실행되는 배포 패키지라 경로 스캔이 취약하고, 명시적 등록이 동일한 분리 효과를 결정적으로 준다(R-006).

횡단 관심사(`fanout`, `confirm`, `errors`, `serializers`)를 도구 모듈에서 분리한 것이 이 구조의 핵심이다. 확인 절차만 해도 6개 도구에, `errors.py`·`serializers.py`는 14개 전부에 걸쳐 반복되므로, 도구 모듈에 인라인하면 요구사항 하나를 고치는 데 여러 파일을 손봐야 한다.

## Design Highlights

전체 도구 계약은 [contracts/tools.md](./contracts/tools.md), 데이터 형태는 [data-model.md](./data-model.md) 참조.

### 도구 표면과 RPC 커버리지

14개 도구가 범위 내 13개 RPC와 2개 미디어 엔드포인트를 모두 덮는다. 유일한 통합은 `search_cases`가 `ListCases`와 `SearchCases`를 함께 처리하는 것이다 — v2에서 빈 쿼리는 parent 아래 전체를 반환하므로 두 RPC는 사실상 같은 도구의 두 모드다. 나머지는 1:1이다.

`SupportEventSubscriptionService`의 7개 RPC는 노출하지 않는다. 이 결정의 부수 효과가 하나 있는데 나쁘지 않다 — 구독 IAM 역할은 조직 수준에서만 부여되므로, 이를 빼면서 사용자가 갖춰야 할 역할이 `techSupportViewer`/`techSupportEditor` 둘로 줄었다(R-005). 설치 문턱이 낮아져 SC-008에 유리하다.

### 태그 기반 기능 게이팅 (FR-018 / FR-019)

모든 도구는 도메인 태그 + 모드 태그(`read`/`write`) + 위험 태그(`destructive`/`escalation`)를 갖는다. 기동 시 설정에 따라 `mcp.disable(tags={...})`를 호출한다. 기본값은 `escalation` 비활성, 나머지 쓰기 활성이다. 비활성 도구는 `tools/list`에 나타나지 않으므로, 안내(FR-019)는 서버 `instructions`와 인접 도구의 오류 문구로 전달한다.

### 확인 흐름 (FR-016 / FR-017)

6개 쓰기 도구가 공통 `confirm.py` 헬퍼를 쓴다. 라운드 1에서 전송될 페이로드를 사람이 읽을 문장으로 제시하고 원본을 `request_state`에 봉인해 반환, 라운드 2에서 `action`을 먼저 확인한 뒤 `accept`일 때만 `request_state`에서 복원해 실행한다. 클라이언트가 elicitation을 지원하지 않으면 아무 변경 없이 거부한다.

### 팬아웃 (Cross-org)

`search_cases` 한 도구가 `fanout.py`를 경유해 설정된 parent 전체에 병렬 호출한다. parent 목록은 설정 기본값을 쓰되 도구 인자로 재정의 가능하다. 반환값에는 항상 `scopes_queried`와 `scopes_failed`가 포함되어, 한 조직의 권한 오류가 다른 조직의 결과를 가리지 않는다.

## Complexity Tracking

> 헌법 `v1.0.0`은 원칙을 지킬 수 없는 경우 이 표에 위반 내용·필요성·기각한 단순한 대안을 기록하도록 요구한다("기록되지 않은 예외는 예외가 아니다"). **현재 기록할 위반이 없다** — 위 Constitution Check가 5개 원칙 전부 PASS다.
>
> 아래는 위반이 아니라, 단순한 대안을 검토한 뒤 의도적으로 선택한 복잡도의 기록이다.

| 복잡도 | 왜 필요한가 | 기각한 단순한 대안 |
|--------|-------------|--------------------|
| 복합 커서 (`fanout.py`) | Google `page_token`은 parent별로만 유효해서 병합 결과에 그대로 쓸 수 없다 (FR-007) | 첫 parent의 토큰만 전달 — 두 번째 parent 결과가 조용히 유실된다 |
| 별도 미디어 REST 경로 (`media.py`) | 첨부 업로드·다운로드가 GAPIC 클라이언트에 존재하지 않는다 (R-002, 휠 직접 확인) | SDK만 사용 — FR-014·FR-015를 구현할 수 없다 |
| 이중 프로토콜 era 분기 (`confirm.py`) | FastMCP 4는 modern 연결에서 `ctx.elicit()`를, handshake 연결에서 `InputRequiredResult`를 각각 거부한다 | 한쪽만 구현 — 나머지 era의 클라이언트에서 모든 쓰기 도구가 깨진다 |
| 이중 오류 정규화 (`errors.py`) | SDK/REST 간극 때문에 트랜스포트가 둘이라 예외 타입도 둘이다. 같은 403이 경로에 따라 다른 안내를 내면 FR-021이 첨부 경로에서만 깨진다 | api_core 예외만 매핑 — 첨부 업로드·다운로드 오류가 분류되지 않은 채 사용자에게 도달한다 |
| 커스텀 `RedactionMiddleware` | 기본 `LoggingMiddleware`는 메시지 내용을 기록하며, 그 내용이 곧 고객 지원 데이터다 (FR-022) | 기본 로깅 미들웨어 사용 — 케이스 본문이 로그로 유출된다 |

## Spec Deviations

**없다.** rev. 1에는 이벤트 구독을 범위에 넣은 이탈이 하나 있었으나, spec.md Clarifications(2026-09-01)가 그 서비스 전체를 명시적으로 배제하면서 되돌렸다.

기록을 위해 남긴다: rev. 1의 근거는 "모든 API를 커버리지" 지시를 `SupportEventSubscriptionService`까지 확장 해석한 것이었고, 배제 사유(*푸시 수신*이 요청-응답 모델과 맞지 않음)가 구독 **리소스 CRUD**에는 적용되지 않는다고 판단했다. 사용자가 CRUD를 포함해 전체를 배제한다고 확정했으므로 이 해석은 폐기한다.

v2beta는 이전과 같이 범위 밖이다 — cross-org 요구를 v2beta가 해결해주지 않는다는 것이 R-004의 결론이므로, 사용자의 cross-org 요청은 오히려 v2 유지를 지지한다.

**인터페이스 언어**: spec Assumptions대로 도구 이름·설명·오류 문구는 영어, 케이스 본문·코멘트는 원문 그대로. 문서 산출물만 한국어다.

## Clarification Impact (rev. 2)

spec.md Clarifications(2026-09-01) 2건이 이 계획에 가한 변경:

| 항목 | rev. 1 | rev. 2 |
|---|---|---|
| 도구 수 | 21 (읽기 10 / 쓰기 11) | **14 (읽기 8 / 쓰기 6)** |
| 기본 노출 (에스컬레이션 off) | 20 | **13** |
| 커버 오퍼레이션 | 20 RPC + 2 HTTP | **13 RPC + 2 HTTP** |
| 파괴적 도구 | 4 | **2** (`close_case`, `escalate_case`) |
| GAPIC 클라이언트 | 4 | **3** |
| 설정 항목 | 9 | **8** (`ENABLE_SUBSCRIPTIONS` 제거) |
| 요구 IAM 역할 | +구독 역할(조직 전용) | `techSupportViewer`/`Editor`만 |
| 오류 처리 | R-007 매핑 8행 | **10행 — `unknown` 조치 안내 요구사항화 + 구현 중 실 API에서 발견한 `api_not_enabled` 추가** (`ErrorKind` 10종) |

두 번째 clarification(SC-006 전수 기준)은 `errors.py`에 실질적 요구를 하나 추가했다. FR-021이 이제 **어느 분류에도 걸리지 않은 실패에도** 다음 조치를 담은 기본 안내를 요구하므로, 매핑 테이블의 폴백이 "알 수 없는 오류"로 끝나서는 안 된다. 비율이 아닌 전수 기준이라 계약 테스트로 검증한다(R-007).
