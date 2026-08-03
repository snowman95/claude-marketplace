---
name: ticket-pull
description: >-
  Fetches a Jira issue via Atlassian MCP and saves it to
  Obsidian tasks/{releaseVersion}/{JIRA-KEY}.md. Key prefix and digit
  count vary by org. Use when user says "ticket pull", "티켓 풀",
  or "Jira에서 티켓 받아와".
---

# ticket-pull

## 절차 요약

1. 티켓 키 확인 (없으면 물어본다).
2. `getJiraIssue` MCP로 이슈 조회 (summary, description, status, fixVersions, comment 등).
3. `fixVersions` 표시 이름으로 `tasks/{fixVersion}/` 폴더 결정 (없으면 생성).
4. `{JIRA-KEY}.md` 신규 생성 또는 **재-pull merge** (아래 규칙).
5. 완료 후 절대 경로 알리고 ticket-workflow 다음 단계 안내.

## 재-pull merge 정책

- `## Jira 원문` 섹션: 최신 MCP 본문으로 교체.
- `## 문의·Blocked` 헤더부터 파일 끝: **그대로 보존** (덮어쓰지 않음).
- `blocked`: 기존 값 유지 (신규만 `false`).
- `## Phase 1`, `## Plan`, `## 구현 체크리스트`: 있으면 삭제하지 않는다.

> 파일 템플릿·fixVersion 복수 처리·vault 경로 규칙 → `REFERENCE.md`
