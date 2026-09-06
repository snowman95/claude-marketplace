---
name: daily-brief
description: >-
  어제 한 일·오늘 할 일을 브리핑하고 daily/YYYY-MM-DD.md 를 생성한다.
  launchd가 평일 08:03에 호출하거나 `/daily-brief` 로 수동 실행.
disable-model-invocation: true
---

# daily-brief

## 경계

- **Jira 쓰기 금지.** 상태 변경·코멘트·이슈 링크 생성을 하지 않는다. 읽기 전용.
- 티켓 md의 손으로 쓴 섹션(Research·Plan·Decision Log·문의·Blocked)을 수정하지 않는다.
- 백로그 티켓의 md를 자동 생성하지 않는다. 목록으로 안내만 한다.

## 절차

### 1. 최신 상태 확보

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/daily-report/poll.py
```

브리핑 직전 1회. 실패해도 계속 진행하되 daily에 ⚠️로 남긴다.

### 2. 입력 수집

| 입력 | 경로 |
|------|------|
| 어제 daily | `{vault}/daily/{어제}.md` (없으면 생략) |
| 이벤트 큐 | `{vault}/daily/_pending.jsonl` |
| 현재 상태 | `{vault}/daily/_state.json` |
| 커밋 | config의 `repos` 각각 `git log --author=<email> --since=<어제 08:00> --format='%h %s'` |

### 3. 작성

`{vault}/daily/{오늘}.md` 를 아래 순서로 만든다. 섹션 순서를 바꾸지 않는다 — 아침에 위에서부터 읽는 파일이다.

```markdown
---
date: YYYY-MM-DD
generated_at: <ISO8601 KST>
active: <n>
blocked: <n>
needs_attention: <n>
parked: <n>
---

# YYYY-MM-DD (요일)

## 오늘 할 일
## 어제 한 일
## ⚠️ 판단 필요 (n)
## 진행 중 (n)
## 배포 대기 (n)
## md 없는 활성 티켓 (n)
## 변경 로그 (오늘)
## 히스토리
```

> 각 섹션의 작성 규칙 → `REFERENCE.md`

### 4. Slack 발송

브리핑 요약을 본인 DM으로 보낸다. **파일 전문을 그대로 붙여넣지 마라** — 아침에 폰으로 30초 안에 읽히는 분량이 기준이다.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/daily-report/send_brief.py --date <오늘>
```

본문은 stdin으로 넘긴다. 스크립트가 발송 후 `ts` 를 `_state.json` 의 `slack` 키에 기록하고,
낮 폴링이 그 `ts` 에 스레드로 변경분을 덧붙인다.

> 메시지 포맷·스레드 규칙 → `REFERENCE.md`

**발송이 실패해도 브리핑은 성공이다.** 파일은 이미 만들어졌다. 실패는 stdout에 한 줄 남기고 넘어간다.

### 5. 마무리

- `_pending.jsonl` 을 `_pending.{어제}.jsonl` 로 로테이트
- 생성한 파일의 절대 경로를 stdout에 출력 (launchd 로그에 남는다)

## 재실행

같은 날 다시 돌리면 `## 변경 로그` 섹션의 누적 내용은 **보존**하고 그 앞 섹션들만 다시 만든다.
하루 동안 폴링이 쌓은 로그를 브리핑 재실행이 지우면 안 된다.
