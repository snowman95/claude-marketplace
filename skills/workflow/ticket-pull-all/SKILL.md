---
name: ticket-pull-all
description: >-
  Searches Jira issues via JQL in a single MCP batch call and bulk-creates or
  updates Obsidian tasks/{fixVersion}/{JIRA-KEY}.md files. Never calls
  getJiraIssue per ticket. Use when user says "ticket pull all", "티켓 전체 풀",
  "일괄 ticket-pull", or "WPQ 전부 pull".
---

# ticket-pull-all

## 핵심 규칙

- **JQL 검색 도구 1회 호출**로 전체 이슈를 가져온다. 이슈마다 `getJiraIssue` 반복 금지.
- 한 응답에 전부 안 들어오면 N회 반복 대신 사용자에게 JQL 범위 분할 안내.
- 파일 템플릿·재-pull merge 정책은 **ticket-pull과 동일**.

## 절차 요약

1. JQL 확정 (없으면 기본 `project = WPQ ORDER BY key ASC` 또는 사용자 입력).
2. JQL 검색 MCP 도구 1회 호출 (`maxResults` 상한까지).
3. 각 이슈마다 ticket-pull과 동일하게 `tasks/{fixVersion}/{JIRA-KEY}.md` 생성·갱신.
4. 완료 후 절대 경로 목록·이슈 수 요약, ticket-workflow 다음 단계 안내.

> fixVersion·vault 경로·파일 구조 상세 → ticket-pull `REFERENCE.md`  
> JQL 도구 선택 방법 → 이 스킬의 `REFERENCE.md`
