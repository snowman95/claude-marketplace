---
name: docs-pull
description: >-
  Confluence 페이지를 Atlassian MCP로 가져와 .claude/docs/{space-key}/{page-title}.md에 저장한다.
disable-model-invocation: true
---

# docs-pull

## 저장 구조

```
{프로젝트 루트}/
└── .claude/
    └── docs/
        └── {space-key}/
            └── {page-title}.md
```

- `{space-key}`: Confluence Space 키 (예: `DEV`, `PLAN`, `WPQ`)
- `{page-title}`: 페이지 제목에서 파일시스템 비안전 문자(`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`) 제거. 공백은 유지.

## 절차

### 1. 페이지 식별

- 사용자가 **URL**을 주면 URL에서 페이지 ID를 추출.
- 사용자가 **페이지 ID**를 주면 그대로 사용.
- 사용자가 **키워드/제목**만 주면 Confluence 검색 MCP 도구로 후보를 찾아 사용자에게 확인.
- 아무것도 없으면 무엇을 가져올지 물어본다.

### 2. MCP로 페이지 조회

- Atlassian MCP에서 Confluence 관련 도구를 사용한다.
- 도구 이름·파라미터는 MCP 구현체마다 다르므로, **먼저 MCP 도구 목록을 확인**하고 페이지 조회를 지원하는 도구를 고른다.
- `cloudId`가 필요하면 `getAccessibleAtlassianResources` 등으로 확보.
- 가져올 정보: 페이지 제목, 본문(storage format 또는 마크다운), space 키, 페이지 ID, 마지막 수정 시각, URL.

### 3. 본문 변환

- Confluence Storage Format(XHTML/ADF)이면 읽기 쉬운 마크다운으로 정리한다.
- 테이블, 코드 블록, 헤딩, 리스트 등 구조를 최대한 보존.
- 이미지는 `![alt](원본URL)` 형태로 링크 유지 (파일 다운로드 안 함).
- 매크로(expand, panel, info 등)는 내용 위주로 평문 변환.

### 4. 저장 경로

- 프로젝트 루트의 `.claude/docs/{space-key}/` 가 없으면 생성.
- 대상: `.claude/docs/{space-key}/{page-title}.md`.

### 5. 파일 구조 (신규 작성 시 템플릿)

```markdown
---
confluence_id: "123456"
space_key: "DEV"
title: "주문 API 설계서"
url: https://your-site.atlassian.net/wiki/spaces/DEV/pages/123456
pulled_at: YYYY-MM-DD
doc_updated_at: YYYY-MM-DDTHH:mm:ss+09:00
last_modified_in_confluence: YYYY-MM-DDTHH:mm:ss+09:00
---

# {title}

## Confluence 원문

(마크다운 변환된 본문)

## 메모

> 아래는 **수동**으로 작성합니다. `docs-pull` 재실행 시 이 섹션 본문을 덮어쓰지 않습니다.
```

### 6. 재-pull (파일이 이미 있을 때) — merge 정책

1. 기존 파일을 읽는다.
2. **`## 메모` 헤더부터 파일 끝까지**의 텍스트를 **그대로 보존**한다 (없으면 신규 템플릿으로 끝에 추가).
3. 갱신하는 것:
   - frontmatter: `pulled_at`, `doc_updated_at`, `last_modified_in_confluence`, `url`, `title` (Confluence와 다르면)
   - **`## Confluence 원문` 섹션 전체** — MCP 최신 본문으로 교체 (헤더 `## Confluence 원문` 아래부터 다음 `## ` 섹션 직전까지).
4. 첫 번째 줄 `# {title}` 은 최신 제목으로 맞춘다.

## 완료 시

- 생성·갱신한 파일의 **절대 경로**를 사용자에게 알린다.
- Confluence 페이지 제목과 URL을 함께 출력.
- 여러 페이지를 가져왔으면 개수와 목록 요약.
