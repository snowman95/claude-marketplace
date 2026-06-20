# Claude Code 컨텍스트 최적화

Claude Code는 대화가 길어질수록 컨텍스트 토큰을 많이 소모합니다.
아래 두 가지 방법으로 토큰 낭비를 줄일 수 있습니다.

---

## 1. RTK (Rust Token Killer)

Bash 명령 출력을 자동 필터링해 Claude가 읽는 토큰을 60~90% 줄여주는 CLI 프록시.

### 설치

```bash
brew install rtk  # 또는 공식 설치 방법 참조
```

### Claude Code hook 등록

`~/.claude/settings.json`에 아래 hook 추가:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "rtk hook claude" }
        ]
      }
    ]
  }
}
```

등록 후에는 Claude Code가 Bash tool로 명령을 실행할 때 자동으로 `rtk <cmd>`로 리라이트됩니다.

### 실제 효과

```
# rtk 미적용 (raw git status)
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
...

# rtk 적용 후
* main...origin/main
(clean)
```

### 유용한 명령

```bash
rtk gain              # 누적 토큰 절약량 확인
rtk gain --history    # 명령별 절약 이력
rtk discover          # Claude Code 이력 분석 — 놓친 최적화 기회 제안
rtk proxy <cmd>       # rtk 없이 raw 실행 (디버깅용)
```

> ⚠️ `rtk gain`이 실패하면 Rust Type Kit(다른 rtk)이 설치된 것. `which rtk`로 확인.

---

## 2. CLAUDE.md 관리 원칙

CLAUDE.md는 매 대화마다 통째로 컨텍스트에 올라갑니다. 내용이 많을수록 토큰 낭비.

### 글로벌 vs 프로젝트 분리

| 파일 | 용도 |
|------|------|
| `~/.claude/CLAUDE.md` | 모든 프로젝트에 공통 적용되는 규칙 |
| `{프로젝트}/CLAUDE.md` | 해당 프로젝트에만 적용되는 규칙 |

### 제거 대상

스킬(`/skill-name`)로 분리할 수 있는 내용은 CLAUDE.md에서 삭제합니다.

**나쁜 예** — CLAUDE.md에 워크플로우 전체 기술:
```markdown
## 작업 프로세스
비사소한 구현 작업은 /ticket-workflow (Phase 0~5)를 따른다.
...긴 설명...
```

**좋은 예** — 스킬로 분리하고 CLAUDE.md는 비움:
```bash
# 스킬 호출로 대체
/ticket-workflow
```

### MCP tool은 deferred — 걱정 불필요

MCP 서버의 tool schema는 실제 사용 전까지 컨텍스트에 올라오지 않습니다 (deferred loading). Figma·Atlassian 등 MCP 서버를 많이 연결해도 사용하지 않으면 토큰 영향 없음.

반면 built-in tool (Bash, Read, Edit, Workflow 등) schema는 항상 로드됩니다 — 이건 줄일 수 없습니다.
