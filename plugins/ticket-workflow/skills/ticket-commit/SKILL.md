---
name: ticket-commit
description: >-
  Creates a fix/{JIRA-KEY} branch from the correct base, commits only
  ticket-scoped changes without --no-verify, then updates the ticket md
  frontmatter. Use when user says "ticket commit", "티켓 커밋",
  or asks to create a fix branch and commit after Phase 5.
---

# ticket-commit

## 핵심 규칙

- **`--no-verify` 금지** — 사용자가 명시한 경우만 예외.
- 스테이징은 해당 티켓 범위만.
- 1티켓 1브랜치 — 다른 Jira 키의 커밋을 같은 브랜치에 쌓지 않는다.

## 절차 요약

1. 티켓 md(`tasks/**/{JIRA-KEY}.md`)에서 `repo`, `fix_version` 확인.
2. 베이스 브랜치 결정 → `git fetch origin` → `fix/{JIRA-KEY}` 브랜치 생성 또는 checkout.
3. 티켓 범위만 스테이징 → `git commit` (훅 자연 실행).
4. 커밋 성공 직후 해당 티켓 md frontmatter 갱신.

> 베이스 브랜치·커밋 메시지 형식·frontmatter 갱신 세부 규칙 → `REFERENCE.md`
