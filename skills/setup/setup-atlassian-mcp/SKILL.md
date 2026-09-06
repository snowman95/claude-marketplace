---
name: setup-atlassian-mcp
description: Atlassian MCP(Jira·Confluence)를 Claude Code에 연결한다.
---

# setup-atlassian-mcp

목표 상태: `getAccessibleAtlassianResources`가 Atlassian 사이트 목록을 반환한다 — **connected**.

## Step 1: 연결 확인

`getAccessibleAtlassianResources` 호출을 시도한다. 사이트가 반환되면 이미 connected — 종료.

## Step 2: MCP 서버 등록

`~/.claude.json`의 `mcpServers`에 Atlassian 항목을 추가한다.

> 설정 스니펫 → `REFERENCE.md`

설정 추가 후 Claude Code를 재시작한다.

## Step 3: OAuth 인증

재시작 후 `mcp__atlassian__authenticate` 도구를 호출한다. 브라우저가 열리면 Atlassian 계정으로 로그인한다. 로그인 완료 후 `mcp__atlassian__complete_authentication`을 호출해 토큰을 확정한다.

## Step 4: 연결 검증

`getAccessibleAtlassianResources`를 호출해 사이트 목록과 `cloudId`가 반환되는지 확인한다. 반환되면 **connected** — 스킬 종료.

실패하면 `REFERENCE.md`의 트러블슈팅을 참고한다.
