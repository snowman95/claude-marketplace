# setup-atlassian-mcp — 상세 규칙

## 설정 스니펫

`~/.claude.json`의 `mcpServers`에 아래 항목을 추가한다.

```json
{
  "mcpServers": {
    "atlassian": {
      "type": "http",
      "url": "https://mcp.atlassian.com/v1/mcp"
    }
  }
}
```

## 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| `getAccessibleAtlassianResources` 도구가 없음 | MCP 서버 미등록 또는 재시작 전 | Step 2 재확인 후 재시작 |
| 인증 후에도 빈 배열 반환 | 계정에 Atlassian 사이트 없음 | 올바른 계정으로 재인증 |
| OAuth 브라우저가 안 열림 | `mcp__atlassian__authenticate` 미호출 | Step 3 재실행 |
| 토큰 만료 | 세션 만료 | Step 3부터 재실행 |
