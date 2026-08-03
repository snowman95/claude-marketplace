---
name: ticket-workflow
description: >-
  Non-trivial implementation workflow covering Phase 0~5 (context loading →
  research → plan → annotation cycle → checklist → implementation).
  Defaults to Jira-ticket mode using a ticket md fetched by ticket-pull;
  also supports a generic (no-ticket) mode when the user says so.
  Use when user asks for "ticket workflow", "워크플로", "티켓 워크플로", or
  "workflow" on any non-trivial implementation task.
---

# ticket-workflow

**절대 금지**: 승인된 plan이 있기 전까지 코드를 작성하지 않는다.

사용자가 명시적으로 "한 번에 쭉" / "승인 없이 구현까지"를 요청하면 전체 Phase를 연속 진행 가능.

## 동작 모드

| 모드 | 조건 | plan 위치 |
|------|------|-----------|
| **티켓 모드** | 티켓 키 또는 ticket-pull md가 있을 때 | `tasks/{releaseVersion}/{JIRA-KEY}.md` 내 `## Plan` |
| **범용 모드** | 티켓 없이 작업 요청 시 | `tasks/{모듈명}/{작업명}_plan.md` |

## QA 명확성 게이트 (버그 수정 시)

버그 수정이면, 아래 4가지가 자명해질 때까지 Research·Plan·코드 작업을 하지 않는다.
부족하면 사용자에게 질문해 채운 뒤 Phase 0으로 진행.

| 항목 | 의미 |
|------|------|
| 이슈 | 무엇이 잘못 보이거나 동작하는지 (재현 조건 포함) |
| 원인 | 코드·데이터·환경 중 어디가 문제인지 (또는 아직 불명) |
| 해결 방법 | 어떤 변경으로 고칠지 (또는 조사가 선행이라는 명시) |
| 기대 결과 | 수정 후 확인 가능한 완료 조건 |

## Phases

Phase별 상세 절차는 → `REFERENCE.md`

| Phase | 이름 | 핵심 |
|-------|------|------|
| 0 | 컨텍스트 로딩 | `architecture.md` + `modules/{모듈명}_research.md` 로딩 |
| 1 | Research | 깊이 읽기 → 문서 갱신. 완료 멘트: `research 완료, 검토해주세요` |
| 2 | Plan | research 승인 후 plan 작성. 완료 멘트: `plan 작성 완료, 검토해주세요` |
| 3 | Annotation Cycle | Obsidian 인라인 메모 → plan 반영. 구현 안 함 |
| 4 | Todo List | plan 하단에 `## 구현 체크리스트` 추가. 승인 후 Phase 5 |
| 5 | Implementation | plan 전 항목 실행. 완료마다 체크리스트 체크. 코드 생성·다수 파일 수정은 서브에이전트로 위임 권장 |

> Obsidian vault 경로·문서 구조·문서 계층은 CLAUDE.md 참조.
