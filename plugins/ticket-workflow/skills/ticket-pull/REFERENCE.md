# ticket-pull — 상세 규칙

## 파일 구조 (신규 작성 템플릿)

```markdown
---
jira_key: WPQ-16135
fix_version: "3.0.0"
jira_status: "미해결"
blocked: false
pulled_at: YYYY-MM-DD
doc_updated_at: YYYY-MM-DDTHH:mm:ss+09:00
url: https://bighitcorp.atlassian.net/browse/WPQ-16135
---

# {summary}

## Jira 원문

### 설명
…

### 댓글
…

## Phase 1: Research (요약)

> ticket-workflow Phase 1에서 작성. 상세는 modules/{모듈명}_research.md

## Plan

> Phase 2에서 작성.

## 구현 체크리스트

> Phase 4에서 작성.

## 문의·Blocked

> 아래는 **수동**으로 갱신합니다. `ticket-pull` / `ticket-commit`은 이 블록 본문을 덮어쓰지 않습니다.

- **문의 대상**:
- **문의 내용**:
- **기대 해결 / 다음 액션**:
```

## fixVersion 복수 처리

- 복수면 사용자에게 어느 폴더에 둘지 확인하거나 첫 번째를 사용하고 frontmatter에 전체 기록.
- 비어 있으면 사용자에게 버전 문자열 입력 요청.

## vault 경로

CLAUDE.md 또는 rules/workflow.mdc 참조.  
`jh.han` 기준: `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/projects/{프로젝트명}/`

## MCP 조회 필드

`summary`, `description`, `status`, `issuetype`, `priority`, `created`, `updated`, `fixVersions`, `comment`, `project`  
`cloudId`는 `getAccessibleAtlassianResources`로 확보. 설명·댓글은 ADF/마크다운을 읽기 쉬운 평문으로 정리.
