---
name: ticket-review
description: >-
  Reviews a PR against the ticket's Research and Plan docs. Checks ticket
  coverage, quality patterns, and trade-offs; records findings in the ticket md.
  Does NOT implement anything. Use when user says "ticket review", "티켓 리뷰",
  "PR 리뷰", "QA 리뷰", "plan 대비 diff", or "코드 리뷰 패턴 제안".
---

# ticket-review

## 금지

- **앱 소스 수정·구현 제안을 코드로 적용하지 않는다.** 문서에 리뷰 기록만.
- Plan을 승인 없이 바꾸지 않는다.

## 전제

- Jira 키 또는 `tasks/{releaseVersion}/{JIRA-KEY}.md` 존재.
- PR URL 또는 `owner/repo#number`.
- 해당 리포가 **로컬에 클론**되어 있어야 함. 없으면 클론 후 재시작 안내.

## Phase 요약

| Phase | 내용 |
|-------|------|
| R0 | `gh pr checkout <URL>`로 PR head checkout (필수 — 이후 모든 작업의 전제) |
| R1 | 티켓 md 없으면 ticket-pull 생성. ticket-workflow Phase 0~2 적용 (이미 있으면 읽기만) |
| R2 | PR 메타 수집 (`gh pr view --json …`). 변경 파일 vs Plan "수정 파일 경로" 1차 대조 |
| R3 | `git diff origin/<base>...HEAD` 로 전체 변경 확보 |
| R4 | 이행·범위·누락·리스크·일관성·품질·가독성·대안 7개 축으로 리뷰 |
| R5 | `{JIRA-KEY}.md` 하단에 `## PR 리뷰: #{number}` 섹션 기록 |

> Phase별 상세·리뷰 출력 템플릿 → `REFERENCE.md`
