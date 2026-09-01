<!--
Sync Impact Report
==================
Version change: (none) → 1.0.0
Rationale: 초기 제정(initial ratification). 이전 파일은 치환되지 않은 템플릿 플레이스홀더만
           담고 있었으므로 개정이 아니라 최초 채택으로 처리한다.

Principles defined (5):
  - I.   Ground Data Only (NON-NEGOTIABLE)   [신규]
  - II.  Code Conventions                     [신규]
  - III. Test-First (NON-NEGOTIABLE)          [신규]
  - IV.  Latest Spec First                    [신규]
  - V.   No Deprecated Surfaces (NON-NEGOTIABLE) [신규]

Sections added:
  - Technology & Verification Standards (SECTION_2)
  - Development Workflow & Quality Gates (SECTION_3)
  - Governance

Sections removed: (none)

Authoring note:
  사용자 입력은 4개 항목이었다 — "코드컨벤션 및 ground data only, 테스트 우선,
  최신 스펙 먼저 반영, deprecated 금지". 첫 항목의 두 요소를 원칙 I과 II로 분리해 5개로
  구성했다. 근거: 두 요소는 준수 여부를 서로 다른 방식으로 확인하므로(원칙 I은 출처 추적,
  원칙 II는 도구 실행), 한 원칙에 묶으면 "준수했는가"가 모호해진다. 4개로 되돌리려면
  원칙 I과 II를 병합하고 MINOR 버전을 올리면 된다.

Compliance status at ratification:
  기존 산출물(spec.md, plan.md, research.md, data-model.md, contracts/tools.md,
  quickstart.md, tasks.md) 전수 점검 결과 위반 0건.
  - 원칙 V 검증: v2 proto 전체에서 deprecated 표시된 필드는 `Comment.plain_text_body`
    하나뿐이며, data-model.md는 이를 "쓰지 않는다"고 명시한다.
  - 원칙 IV 검증: fastmcp 4.0.0, google-cloud-support 0.5.3, MCP 2026-07-28 모두
    현재 최신 안정 버전. v2beta 미채택은 원칙 IV에 부합한다(안정 버전 우선).

Follow-up TODOs: 없음
-->

# Cloud Support MCP Constitution

## Core Principles

### I. Ground Data Only (근거 데이터 전용) — NON-NEGOTIABLE

외부 시스템에 관한 모든 사실은 **1차 출처로 검증한 것만** 산출물과 코드에 들어간다.

- API의 엔드포인트, 필드명, enum 값, 제약(길이·크기 상한), deprecation 여부는 **설치된
  패키지의 소스 또는 벤더 공식 문서 원문**으로 확인해야 한다(MUST).
- 모델의 기억, 블로그, 요약본, AI가 생성한 설명은 1차 출처가 **아니다**(MUST NOT).
- 요약본과 원문이 어긋나면 **원문이 이긴다.** 어긋난 사실은 기록해야 한다(MUST).
- 연구·설계 문서의 각 결정은 **검증 방법을 명시**해야 한다(MUST) — 예: "휠 직접 해제 후
  `gapic_metadata.json` 파싱", "공식 REST 문서 `.md.txt` 원문 확인".
- 확인할 수 없는 항목은 추측으로 채우지 않고 **미해결 항목으로 기록**하며, 그것이 설계에
  주는 영향을 함께 적어야 한다(MUST).

**Rationale**: 이 프로젝트는 이 원칙으로 실제 오류 세 건을 잡았다 — v2beta가 `OR`로 여러
조직을 검색할 수 있다는 오해, 첨부 업로드의 파일명이 쿼리 파라미터라는 오해, `plain_text_body`가
사용 가능한 필드라는 오해. 셋 다 요약본에서 왔고 원문에서 뒤집혔다.

### II. Code Conventions (코드 컨벤션)

코드는 도구로 강제되는 형식과, 주변 코드에서 읽어낸 관습을 함께 따른다.

- 커밋 전에 `ruff` 린트와 포맷이 **통과해야 한다**(MUST).
- 새 코드는 주변 코드의 **명명·주석 밀도·관용구를 따라야 한다**(MUST). 파일마다 다른 스타일을
  섞지 않는다.
- 공개 함수와 MCP 도구는 **타입 주석을 가져야 한다**(MUST). 출력은 임시 `dict`가 아니라
  **선언된 모델**이어야 한다(MUST).
- 주석 처리된 코드를 남기지 않는다(MUST NOT). 소스의 `TODO`는 **과제 ID를 참조해야 한다**(MUST).

**Rationale**: 형식은 도구가, 관습은 사람이 지킨다. 도구만으로는 "이 파일에서만 다른 방식"을
막지 못한다.

### III. Test-First (테스트 우선) — NON-NEGOTIABLE

테스트를 먼저 쓰고, **실패를 확인한 뒤** 구현한다.

- 구현 과제를 시작하기 전에 해당 테스트가 작성되어 있고 **실패해야 한다**(MUST).
- 모든 계약 — 도구 스키마, 오류 매핑, 확인 절차, 페이지네이션 — 은 **계약 테스트를 가져야
  한다**(MUST).
- 네트워크가 필요한 테스트는 **기본 실행에서 제외**되어야 하며 환경변수로만 활성화된다(MUST).
- 외부에 실제 부작용을 일으키는 테스트는 벤더가 제공하는 **테스트 모드**를 써야 한다(MUST) —
  이 프로젝트에서는 `test_case=True`.

**Rationale**: 확인 절차(사용자 승인 없이 실행되지 않음)와 팬아웃 부분 실패(한 범위의 오류가
나머지를 가리지 않음)는 테스트 없이는 존재를 증명할 수 없는 종류의 요구사항이다.

### IV. Latest Spec First (최신 스펙 우선)

새 작업은 각 프로토콜·SDK의 **최신 안정 릴리스**를 대상으로 한다.

- 채택 시점에 릴리스된 **최신 안정 버전**을 대상으로 해야 한다(MUST).
- 버전 핀은 **정확한 값**이어야 하며(MUST), 확인 시점을 함께 기록해야 한다(MUST).
- 구현 착수 전에 **레지스트리에서 현재 버전을 다시 확인해야 한다**(MUST). 기억에 의존하지
  않는다(MUST NOT).
- 프리릴리스·베타 채택은 **그것만이 제공하는 능력을 문서로 정당화해야 한다**(MUST). 표기나
  편의상의 차이는 정당화가 되지 않는다.

**Rationale**: "최신"은 "베타"가 아니다. 이 프로젝트는 v2beta가 cross-org 검색을 제공하지
**않음**을 확인하고 안정 버전 v2를 유지했다 — 원칙 IV의 정확한 적용 사례다.

### V. No Deprecated Surfaces (deprecated 금지) — NON-NEGOTIABLE

벤더가 deprecated로 표시한 것은 동작하더라도 쓰지 않는다.

- 벤더 문서나 소스에서 deprecated로 표시된 API·필드·인자·전송 방식은 **사용하지 않는다**
  (MUST NOT). 아직 동작한다는 사실은 사용 근거가 되지 않는다.
- 기존 코드에서 deprecated 사용이 발견되면 **미루지 않고 교체해야 한다**(MUST).
- 대체 수단이 없는 deprecated 표면은 **미해결 항목으로 기록**하고 벤더가 밝힌 상태를 함께
  적어야 한다(MUST).
- 의존성 추가 시 그 표면에 deprecated 항목이 있는지 **확인해야 한다**(MUST) — 원칙 I의
  1차 출처 확인에 포함된다.

**Rationale**: deprecated 표면은 예고 없이 사라지거나 조용히 동작이 바뀐다. 채택 시점에
비용이 0인 회피가, 나중에는 마이그레이션이 된다.

## Technology & Verification Standards

- **런타임**: Python 3.14 이상. 패키지·환경 관리는 `uv`.
- **1차 출처 우선순위** (원칙 I 적용 시 위에서부터):
  1. 설치된 패키지의 소스 코드(휠/sdist 내부) — 가장 강한 근거
  2. 벤더 공식 문서의 기계 판독 원문(`.md.txt`, `llms.txt`, OpenAPI/proto)
  3. 벤더 공식 문서의 HTML 페이지
  4. 패키지 레지스트리 메타데이터(PyPI JSON 등) — 버전·의존성 확인용
- **버전 고정**: 런타임 의존성은 정확한 버전 또는 명시적 범위로 고정한다. 전이 의존성을 직접
  선언하지 않는다 — 상위 패키지가 이미 핀을 갖는 경우 중복 선언은 충돌의 원인이 된다.
- **미해결 항목**: 원칙 I·V가 요구하는 기록은 해당 기능의 `research.md`에 모으고, 설계에 주는
  영향("무영향" 포함)을 함께 적는다.

## Development Workflow & Quality Gates

- **spec이 권위를 갖는다.** 계획이나 과제가 명세를 벗어나면, 명세를 갱신하거나 계획을 되돌린다.
  둘 중 하나를 반드시 한다 — 어긋난 채로 구현에 들어가지 않는다(MUST NOT).
- **게이트 순서**: `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-analyze` → `/speckit-implement`. `analyze`에서 CRITICAL이 남아 있으면
  구현을 시작하지 않는다(MUST NOT).
- **헌법 위반은 CRITICAL이다.** 원칙을 희석하거나 재해석해서 통과시키지 않는다(MUST NOT) —
  명세·계획·과제를 고치거나, 별도의 헌법 개정을 거친다.
- **범위 변경 기록**: 명세 범위가 바뀌면 `spec.md`의 Clarifications에 질문과 답을 남기고,
  하위 산출물(plan/tasks/contracts)의 무효화 범위를 명시적으로 보고한다(MUST).

## Governance

이 헌법은 다른 모든 관행에 우선한다. 충돌 시 헌법이 이긴다.

- **개정 절차**: 개정은 `/speckit-constitution`으로 수행하며, 변경 사유와 Sync Impact
  Report를 문서에 남긴다. 원칙의 추가·제거·의미 변경은 별도 커밋으로 분리한다.
- **버전 정책** (semantic versioning):
  - **MAJOR**: 원칙 제거, 또는 기존 원칙의 의미를 뒤집는 재정의
  - **MINOR**: 원칙 추가, 원칙 병합·분할, 또는 지침의 실질적 확대
  - **PATCH**: 문구 명확화, 오타 수정, 의미를 바꾸지 않는 다듬기
- **준수 검토**: `/speckit-analyze`가 매 기능마다 헌법 정합성을 검사한다. 원칙별로 무엇을
  근거로 통과 판정했는지 보고해야 하며, "위반 없음"만으로는 부족하다.
- **예외**: 원칙을 지킬 수 없는 경우, 계획 문서의 Complexity Tracking에 위반 내용·필요성·
  기각한 단순한 대안을 기록해야 한다. 기록되지 않은 예외는 예외가 아니다.

**Version**: 1.0.0 | **Ratified**: 2026-09-01 | **Last Amended**: 2026-09-01
