---
name: ticket-review
description: >-
  PR을 티켓의 Research·Plan 대비 리뷰하고 결과를 티켓 md에 기록한다. 구현하지 않는다.
disable-model-invocation: true
---

# ticket-review

## 경계

- 리뷰 결과는 문서에 기록만. 앱 소스 수정·구현 제안 코드 적용은 이 스킬 범위 밖.
- Plan 변경은 사용자 승인 후에만.

## 전제

- Jira 키 또는 `.claude/tickets/{releaseVersion}/{JIRA-KEY}.md` 존재.
- PR URL 또는 `owner/repo#number`.
- 해당 리포가 **로컬에 클론**되어 있어야 함. 없으면 클론 후 재시작 안내.

## Phase 요약

| Phase | 내용 |
|-------|------|
| R0 | `gh pr checkout <URL>`로 PR head checkout (필수 — 이후 모든 작업의 전제) |
| R1 | 티켓 md 없으면 ticket-pull 생성. ticket-workflow Phase 0~2 적용 (이미 있으면 읽기만) |
| R2 | PR 메타 수집 (`gh pr view --json …`). 변경 파일 vs Plan "수정 파일 경로" 1차 대조 |
| R3 | **티켓 변경분** diff 확보 (다른 티켓·동봉 커밋 제외 후 `git diff <제외커밋>..HEAD`) |
| R4 | 이행·범위·누락·리스크·일관성·품질·가독성·대안 8개 축으로 리뷰 |
| R5 | `{JIRA-KEY}.md` 하단에 `## PR 리뷰: #{number}` 섹션 기록 |
| R6 | `render-html` 스킬로 리뷰 결과를 브라우저에 렌더링 |

> Phase별 상세·리뷰 출력 템플릿 → `REFERENCE.md`
