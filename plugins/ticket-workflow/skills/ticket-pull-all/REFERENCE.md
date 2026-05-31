# ticket-pull-all — 상세 규칙

## MCP 도구 선택

연결된 Atlassian MCP에서 **JQL로 여러 이슈를 한 응답에 반환하는 도구**를 먼저 확인한다.
도구 이름·파라미터는 구현체마다 다르므로, 이름에 `search`, `jql`, `issues`가 포함된 검색 계열을 고른다.

`cloudId` 등이 필요하면 `getAccessibleAtlassianResources`로 별도 사전 호출 허용 (이슈 일괄 조회와 별도).

## JQL 기본 후보

```
project = WPQ ORDER BY key ASC
project = WPQ AND fixVersion = "3.0.0" ORDER BY key ASC
```

버전 문자열은 사용자·맥락에 맞게 조정.

## 요청 필드

`summary`, `description`, `status`, `issuetype`, `priority`, `created`, `updated`, `fixVersions`, `comment`  
도구가 허용하는 범위에서 최대한 포함.

## vault·레포 라우팅

ticket-pull과 동일.  
Summary 접두로 shop(`web_weverseshop`) vs admin(`web_weverseshop_admin`) 결정.  
`jh.han`: vault 루트 `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/projects/` 아래 프로젝트 폴더만 사용.
