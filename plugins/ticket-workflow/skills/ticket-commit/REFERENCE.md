# ticket-commit — 상세 규칙

## 베이스 브랜치

| 레포 | fixVersion이 **3.0.0** | 그 외 |
|------|-------------------------|-------|
| **web_weverseshop** | `features/api-order-renewal` | `develop` |
| **web_weverseshop_admin** | `api/order-renewal-2` | `develop` |

## 브랜치 이름

`fix/{JIRA-KEY}` (예: `fix/WPQ-15538`, `fix/CWEB-1234`).
이미 있으면 그 티켓 전용인지 확인 후 checkout. 다른 티켓용이면 사용자와 조율.

## git commit 규칙

- 레포 루트에서 `git commit` 만 실행 (**`-n` / `--no-verify` 금지**).
- Husky 없는 프로젝트 — `lint-staged` 등을 별도로 복제 실행하지 않는다.
- Husky 있는 프로젝트 — Git이 훅을 호출하도록 두어 로컬과 동일 경로.
- 훅이 실패하면 코드·포맷 수정 후 재커밋. `--no-verify`로 통과시키지 않는다.
- 훅이 에이전트 환경에서만 안 도는 것 같으면 사용자에게 로컬 터미널 재시도 안내.

## 커밋 메시지 형식

```
fix(페이지명): 작업 내용 한 줄 요약 (JIRA-KEY)

https://{조직 Jira}/browse/JIRA-KEY
```

`페이지명`: 실제 영향 화면/기능(예: `order-detail`, `claim-history`).

## 커밋 후 frontmatter 갱신

파일 위치: `tasks/**/{JIRA-KEY}.md`  
**`## 문의·Blocked` 섹션 본문은 절대 수정·삭제하지 않는다.**

갱신·추가 키:

| 키 | 값 |
|----|-----|
| `last_commit_at` | ISO 8601 (`2026-03-19T15:04:00+09:00`) |
| `commit_sha` | 짧은 해시 (예: `3dd340a`) |
| `git_branch` | 현재 브랜치 (예: `fix/WPQ-16135`) |
| `doc_updated_at` | 갱신 시각 (ISO) |
| `jira_status` | MCP 조회 성공 시 갱신 |

유지: `blocked`, `jira_key`, `fix_version`, `url`, `pulled_at` 등 기존 값은 삭제하지 않는다.

## 완료 시 알림

- 브랜치명, 베이스 브랜치, 커밋 해시
- 갱신한 티켓 md 절대 경로
- 훅에 막혔다면 원인 한 줄
