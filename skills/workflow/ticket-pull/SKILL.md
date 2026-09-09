---
name: ticket-pull
description: >-
  Jira 이슈를 Atlassian MCP로 가져와 .claude/tickets/{fixVersion}/{JIRA-KEY}.md에 저장한다.
disable-model-invocation: true
---

# ticket-pull

## 절차 요약

1. 티켓 키 확인 (없으면 물어본다).
2. `getJiraIssue` MCP로 이슈 조회 (summary, description, status, fixVersions, comment 등).
3. `fixVersions` 표시 이름으로 `.claude/tickets/{fixVersion}/` 폴더 결정 (없으면 생성).
4. `{JIRA-KEY}.md` 신규 생성 또는 **재-pull merge** (아래 규칙).
5. 완료 후 절대 경로 알리고 ticket-workflow 다음 단계 안내.

## `links:` 블록은 반드시 채운다

**본문·댓글에서 Confluence·Figma 링크를 찾아 frontmatter `links:` 에 넣는다.**
그리고 **등록 시점의 `version`/`last_modified` 를 현재값으로 조회해 채운다** —
비워두거나 옛 값을 넣으면 다음 폴링이 "변경됐다"고 오탐한다.

```yaml
links:
  confluence:
    - id: "5919834330"
      url: https://your-site.atlassian.net/wiki/spaces/W/pages/5919834330
      title: "…상세기획"
      version: 44          # 지금 조회한 값
      local: "docs/W/….md"
  figma:
    - file_key: LU01ZBqK0wEA930576PjLm
      node_id: "8604-39330"
      name: "샵_장바구니"
      last_modified: 2026-09-03T00:00:00Z   # 지금 조회한 값
```

하나도 못 찾으면 md 맨 위(제목 아래)에 경고를 남긴다.

```markdown
> ⚠️ 문서 링크 없음 — 문서 변경 추적이 꺼진 상태다
```

**조용히 비워두지 마라.** vault 티켓 md 162개 중 `links:` 를 가진 것이 **0개**였고,
그래서 기획서가 **18번 바뀌는 동안 아무도 몰랐다.** 추적이 꺼져 있다는 사실 자체가 보여야 한다.

## 재-pull merge 정책

- `## Jira 원문` 섹션: 최신 MCP 본문으로 교체.
- `## 문의·Blocked` 헤더부터 파일 끝: **그대로 보존** (덮어쓰지 않음).
- `blocked`: 기존 값 유지 (신규만 `false`).
- `## Phase 1`, `## Plan`, `## 구현 체크리스트`: 있으면 삭제하지 않는다.

> 파일 템플릿·fixVersion 복수 처리 세부 규칙 → `REFERENCE.md`
