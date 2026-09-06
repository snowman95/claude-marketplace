# daily-report 모듈 계약

스펙: `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/projects/personal/tasks/daily-report/daily-report_design.md`

공통 규칙
- **stdlib만.** 외부 의존성 금지 (urllib, json, tomllib, dataclasses, pathlib). 테스트만 pytest.
- Python 3.13. `from __future__ import annotations` 불필요.
- 토큰·비밀값을 **절대 print/log 하지 않는다.**
- 테스트는 fixture 기반. 실제 API를 호출하지 않는다.
- KST = `timezone(timedelta(hours=9))`.
- 참고 컨벤션: `~/.claude/skills/docs-pull-all/scripts/pull.py` (Basic auth, urllib, --dry-run)

## config.py

```python
@dataclass(frozen=True)
class Config:
    vault: Path              # projects/ 루트
    site: str                # "your-site.atlassian.net" (스킴 없음)
    email: str
    parked_statuses: list[str]
    qa_projects: list[str]
    qa_lookback_days: int
    repos: list[Path]
    @property
    def daily_dir(self) -> Path: ...      # vault / "daily"

def load_config(path: Path | None = None) -> Config
    # 기본 경로: <이 파일 옆>/config.toml. tomllib 사용. ~ 확장.

def load_token(email: str) -> str
    # 순서: $ATLASSIAN_API_TOKEN -> ~/.config/atlassian/daily-track.env -> ~/.config/atlassian/config
    # env 파일은 KEY=value 한 줄씩. 없으면 RuntimeError.

def load_figma_token() -> str | None
    # ~/.claude.json 의 mcpServers["figma-console"].env.FIGMA_ACCESS_TOKEN. 없으면 None.
```

## atlassian.py

```python
class JiraClient:
    def __init__(self, site: str, email: str, token: str)
    def search(self, jql: str, fields: list[str], max_results: int = 100) -> list[dict]
        # GET https://{site}/rest/api/3/search/jql
        # 파라미터: jql, maxResults, fields(콤마조인)
        # 반환: 응답의 issues 리스트 그대로

class ConfluenceClient:
    def __init__(self, site: str, email: str, token: str)
    def page_versions(self, ids: list[str]) -> dict[str, int]
        # GET https://{site}/wiki/api/v2/pages?id=...&limit=250  (배치 250)
        # 반환: {page_id: version.number}. 없는 id는 결과에서 빠짐.
```

두 클라이언트 모두 HTTP 에러 시 `ApiError(status:int, path:str, body:str)` 를 raise.
`ApiError`는 atlassian.py에 정의하고 figma.py도 재사용한다.

## figma.py

```python
class FigmaClient:
    def __init__(self, token: str)
    def last_modified(self, file_key: str) -> str | None
        # GET https://api.figma.com/v1/files/{key}?depth=1
        # 헤더: X-Figma-Token
        # 반환: lastModified (ISO8601). 403/404 는 None (권한 없는 파일은 흔함).
        # 그 외 에러는 ApiError raise.
```

## state.py

```python
SCHEMA = 1

@dataclass
class Event:
    ticket: str
    kind: str        # "status" | "confluence" | "figma" | "qa_candidate" | "new"
    text: str        # 히스토리 한 줄 본문 (타임스탬프·불릿 제외)
    attention: bool  # True면 ⚠️ 접두

def load(path: Path) -> dict
    # 없으면 {"schema":1,"polled_at":None,"consecutive_errors":0,"last_error":None,
    #          "tickets":{},"qa_candidates":{}}
    # JSON 파싱 실패 시 <path>.bak 시도, 그것도 실패하면 빈 상태 반환 (예외 안 냄)

def save(path: Path, data: dict) -> None
    # 원자적: 같은 디렉토리에 temp 쓰고 os.replace. 쓰기 전 기존 파일을 <path>.bak 으로 복사.

def diff_ticket(old: dict | None, new: dict) -> list[Event]
    # old is None            -> [Event(kind="new", text=f'**추적 시작** {status}', attention=False)]
    # status 변경            -> Event("status", f'**status** {old} → {new}', False)
    # links.confluence[id] 증가 -> Event("confluence", f'**Confluence** `{id}` v{old} → v{new}', True)
    # links.figma[key] 변경   -> Event("figma", f'**Figma** `{key}` {old[:10]} → {new[:10]}', True)
    # 변경 없으면 []
    # new 에만 있는 링크(최초 등록)는 이벤트를 만들지 않는다.
```

`new` 딕셔너리 형태 (`_state.json["tickets"][KEY]`):
```json
{"status":"진행 중","status_category":"진행 중","updated":"2026-09-02T18:22:00+09:00",
 "summary":"...","blocked":false,"md":["myproject/tasks/shop3.3.0/CWEB-1547.md"],
 "links":{"confluence":{"5919834330":13},"figma":{"AbC123":"2026-08-20T04:11:00Z"}}}
```

## vault.py

```python
HISTORY_HEADER = "## 변경 히스토리"
BLOCKED_HEADER = "## 문의·Blocked"

def scan(vault: Path) -> dict[str, list[Path]]
    # vault.glob("*/tasks/**/*.md") 순회.
    # 키 판정: frontmatter의 jira_key: 우선, 없으면 파일 stem 앞부분 정규식 ^([A-Z][A-Z0-9]+-\d+)
    # 읽기 실패(iCloud 미동기화 등)는 조용히 skip.
    # 반환값 경로는 vault 기준 상대경로가 아니라 절대 Path.

def primary_mds(key: str, paths: list[Path]) -> list[Path]
    # stem 이 key 와 정확히 일치하는 것만. (CWEB-1548.md O, WPQ-17415-share.md X)

def read_frontmatter(md: Path) -> dict
    # --- ... --- 블록을 파싱. 중첩 없는 단순 YAML 부분집합 + links: 블록 지원.
    # 외부 yaml 라이브러리 금지. 필요한 키만 확실히 파싱: jira_key, jira_status, blocked, fix_version, url, links

def read_links(md: Path) -> dict
    # {"confluence":[{"id":str,"url":str,"title":str,"version":int,"local":str}],
    #  "figma":[{"file_key":str,"node_id":str,"name":str,"last_modified":str}]}
    # links: 블록이 없으면 {"confluence":[], "figma":[]}

def append_history(md: Path, lines: list[str], dry_run: bool = False) -> bool
    # lines 는 이미 완성된 한 줄들 (예: "- `09-04 14:07` **status** 개발 준비 → 진행 중")
    # HISTORY_HEADER 섹션이 있으면 그 섹션 끝에 append.
    # 없으면 BLOCKED_HEADER 바로 앞에 섹션을 새로 만들어 삽입.
    # BLOCKED_HEADER 도 없으면 파일 끝에 섹션 추가.
    # dry_run 이면 파일을 쓰지 않고 True 만 반환.
    # 섹션 신규 생성 시 헤더 아래 안내 blockquote 2줄 포함:
    #   > `poll.py`가 자동 append. 항목을 삭제하지 않는다.
    #   > `⚠️`는 판단이 필요하다는 뜻이며, 처리하면 줄 끝에 결과를 덧붙인다.
```

---

## poll.py (통합 — 다른 모듈이 전부 끝난 뒤 구현)

```
python3 poll.py [--dry-run] [--config PATH] [--date YYYY-MM-DD]
```

`--dry-run`: 파일을 일절 쓰지 않고 무엇을 쓸지 stdout에 출력.
`--date`: daily 파일명 기준일 (테스트용, 기본 오늘).

### 다른 모듈 담당자가 남긴 통합 계약

- `state.diff_ticket()` 이 만든 `Event.ticket` 은 **비어 있을 수 있다.** poll.py 가 순회하면서 티켓 키로 채운다.
- `kind="qa_candidate"` 이벤트는 `diff_ticket` 이 만들지 않는다. **poll.py 가 직접 생성한다.**
- `state.load()` 는 예외를 던지지 않는다. 손상 시 빈 상태가 오지만, 그때도 poll.py 가 md 선언값으로 베이스라인을 복구하므로 전 티켓이 `kind="new"` 가 되지는 않는다.
- **md 가 durable 베이스라인이고 `_state.json` 은 캐시다.** `diff_ticket` 에 넘길 `old` 는 poll.py 가 고른다 — state 엔트리가 있으면 그것, 없으면 md 의 `jira_status`·`links[].version`·`links[].last_modified`, 그것도 없을 때만 `None`(→ `kind="new"`).

### 흐름

1. **주말이면 즉시 exit 0** (`datetime.now(KST).weekday() >= 5`). 로그 한 줄만 남긴다.
2. config·토큰 로드. `_state.json` 로드.
3. JQL 2회 — 활성 / parked.
   ```
   활성   assignee = currentUser() AND statusCategory != Done AND status NOT IN (<parked>) ORDER BY updated DESC
   parked assignee = currentUser() AND status IN (<parked>)
   ```
   fields: `summary,status,updated,fixVersions,issuetype,parent`
4. `vault.scan()` → key → md 배열. 활성 티켓마다 `vault.primary_mds()` 로 append 대상 결정.
5. 활성 티켓마다 `new` dict 조립:
   - Jira 응답에서 status / status_category / updated / summary
   - `vault.read_frontmatter()` 에서 `blocked`
   - `vault.read_links()` → Confluence id 목록·Figma key 목록을 모아 **배치로** 조회
     (`ConfluenceClient.page_versions(전체 id)` 1회, Figma는 key마다 1회)
   - `links` = `{"confluence": {id: version}, "figma": {key: last_modified}}`
6. 베이스라인 결정 → `state.diff_ticket(baseline, new)` → 이벤트. `Event.ticket` 을 키로 채운다.
   `baseline` = state 엔트리 > md 선언값(`jira_status`/`links`) > `None`.
   md 의 `version` 이 없거나 0 이면 그 링크는 베이스라인에서 뺀다 (최초 등록으로 본다).
7. QA 후보: `project IN (<qa_projects>) AND created >= -<N>d` 조회 →
   summary + description 에서 `\b(CWEB|WPQ|WV2Q|WWSP)-\d+\b` 를 찾아 활성 키와 교차.
   `_state.json["qa_candidates"]` 에 이미 있으면 **건너뛴다** (state 무관하게 재제안 금지).
   새 후보만 `state="proposed"` 로 등록하고 `kind="qa_candidate"` 이벤트 생성.
8. 이벤트를 히스토리 줄로 렌더:
   ```
   - `MM-DD HH:MM` {⚠️ 접두 if attention}{event.text}
   ```
   `vault.append_history()` 로 primary md 전부에 append.
9. 이벤트를 `_pending.jsonl` 에 append (JSON 한 줄씩, `ticket`/`kind`/`text`/`attention`/`at` 포함).
10. `state.save()`.
11. 오늘자 daily 파일이 **있으면** `## 변경 로그` 섹션에 같은 줄을 append. 없으면 건너뛴다 (브리핑이 만든다).

### 에러

- 어떤 API 실패든 **exit 0**. `_state.json` 의 `last_error` 에 메시지, `consecutive_errors` 증가.
- 성공하면 `consecutive_errors = 0`, `last_error = None`.
- `consecutive_errors >= 3` 이면 `osascript -e 'display notification ...'` 호출.
- Figma `403 Invalid token` 은 흔하다 (PAT 만료). Figma만 건너뛰고 나머지는 정상 진행한다. **전체를 실패시키지 마라.**
- 부분 실패해도 성공한 부분의 diff·저장은 수행한다.

### 출력

stdout에 사람이 읽을 요약. 토큰·비밀값을 절대 찍지 마라.
```
[2026-09-04 14:07] 활성 5 · parked 37 · 이벤트 3
  CWEB-1547  status 개발 준비 → 진행 중
  CWEB-1547  ⚠️ Confluence `5919834330` v43 → v44
  WV2Q-53784 추적 시작 접수
  md 없음: CWEB-1549, CWEB-1550, WV2Q-53784
```
