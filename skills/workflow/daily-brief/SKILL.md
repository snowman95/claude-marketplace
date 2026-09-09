---
name: daily-brief
description: >-
  선행 조사까지 끝낸 일일 브리핑을 만들어 daily/YYYY-MM-DD.md 에 쓰고 Slack DM 으로 보낸다.
  launchd가 평일 08:03에 호출하거나 `/daily-brief` 로 수동 실행.
disable-model-invocation: true
---

# daily-brief

## 목적 — 먼저 이걸 읽어라

일일 브리핑은 **"변경 감지 알림"이 아니다.**
감지·조사·구현은 **내가 다 하고**, 사람에게는 **사람만 할 수 있는 일**만 남긴다.

| 내가 한다 | 사람이 한다 |
|---|---|
| 문서 읽기·diff·요약 | 외부(기획·디자인·BE) 문의 |
| `ticket-pull`, 코드 작성, 자체 리뷰, 커밋 | 스펙 변경 수용 여부 **결정** |
| 놓친 것 세기 | PR 승인·머지·배포 |
| | 우선순위 재조정 |

**"확인해라", "읽어봐라" 를 사람에게 시키지 마라.**
브리핑에 그런 문장이 있으면 **아직 내 일이 안 끝난 것이다.** 돌아가서 조사를 마치고 결과를 적어라.

감지만 해서 넘기는 브리핑은 사람의 할 일 목록을 늘릴 뿐이다. 그러면 브리핑이 없는 것만 못하다.

## 경계

- **Jira 쓰기 금지.** 상태 변경·코멘트·이슈 링크 생성을 하지 않는다. 읽기 전용.
- **`git push` 금지. PR 생성 금지.** 커밋까지만 한다.
- **`daily/releases.md` 쓰기 금지.** 사람이 관리하는 파일이다. 읽기만 한다.
- 티켓 md의 손으로 쓴 섹션(Research·Plan·Decision Log·문의·Blocked)을 수정하지 않는다.

## 스크립트 경로

스크립트는 **`~/.local/share/daily-report/`** 에 있다. 플러그인 자동갱신 밖으로 옮겼으므로
`${CLAUDE_PLUGIN_ROOT}/scripts/...` 는 없는 경로다. 쓰지 마라.

## Step 1: 상태 갱신

```bash
python3 ~/.local/share/daily-report/poll.py
```

브리핑 직전 1회. **실패해도 계속 진행하되** daily 파일에 ⚠️ 로 남긴다 (무엇이 왜 실패했는지 한 줄).

입력은 이렇게 모인다.

| 입력 | 경로 |
|---|---|
| 어제 daily | `{vault}/daily/{어제}.md` (없으면 생략) |
| 이벤트 큐 | `{vault}/daily/_pending.jsonl` |
| 현재 상태 | `{vault}/daily/_state.json` (`tickets`·`watch`·`decisions`) |
| 릴리즈 일정 | `{vault}/daily/releases.md` (읽기 전용) |
| 커밋 | config `repos` 각각 `git log --author=<email> --since='<어제> 08:00' --format='%h %s'` |

## Step 2: 선행 조사 — **이 스킬의 본체**

브리핑 문장을 쓰기 전에 조사를 끝낸다. 이 Step 이 실행 시간의 대부분이다.

| 상황 | 할 일 |
|---|---|
| md 없는 활성 티켓 | **`ticket-pull` 을 그냥 실행한다.** 사람에게 `/ticket-pull` 을 시키지 마라 |
| 변경 감지된 티켓 (미처리 `⚠️`) | **`ticket-advance` 를 호출한다.** as-is/to-be 정리부터 커밋까지 갈 수 있으면 간다 |
| PR 신규 코멘트 | 읽고 요약한다. 반영 가능한 지적이면 `ticket-advance` 로 넘긴다 |
| Jira 신규 코멘트 | 읽고 요약한다. 문의 답이 왔으면 결정으로 올리지 말고 **반영한다** |
| 각 리포 | `git log --author --since='<어제> 08:00'` 로 어제 활동 확인 |

조사 결과가 **사람의 판단을 요구할 때만** 「네가 할 일」로 올린다.
내가 답을 낼 수 있는 것은 답을 내고 「내가 해둔 것」에 적는다.

`ticket-advance` 가 중단(⏸)으로 끝났으면 그 중단 사유가 곧 「네가 할 일 › 결정」 항목이다.
선택지와 추천을 그대로 옮긴다.

## Step 3: 작성

`{vault}/daily/{오늘}.md` 를 아래 순서로 만든다. **섹션 순서를 바꾸지 않는다** — 아침에 위에서부터 읽는 파일이다.

```markdown
---
date: YYYY-MM-DD
generated_at: <ISO8601 KST>
active: <n>
blocked: <n>
decisions_open: <n>
watch_red: <n>
watch_yellow: <n>
---

# YYYY-MM-DD (요일)

## 네가 할 일
### 결정
### 문의
### 승인·배포

## 놓친 것
### 🔴
### 🟡

## 내가 해둔 것

## 진행 중

## 참고

## 릴리즈 일정

## 변경 로그 (오늘)
```

> 각 섹션의 작성 규칙·표기 규칙 → `REFERENCE.md`
> 「놓친 것」의 감시 규칙 → `WATCH.md`

## Step 4: Slack 발송

```bash
python3 ~/.local/share/daily-report/send_brief.py --date <오늘>
```

본문은 **stdin** 으로 넘긴다. 파일 전문을 그대로 붙여넣지 마라 —
**아침에 폰으로 30초 안에 읽히는 분량**이 기준이다.

스크립트가 발송 후 `ts` 를 `_state.json` 의 `slack` 키에 기록하고, 낮 폴링이 그 `ts` 에 스레드로 변경분을 덧붙인다.

**발송이 실패해도 브리핑은 성공이다.** 파일은 이미 만들어졌다. 실패는 stdout 에 한 줄 남기고 넘어간다.

> 메시지 포맷·스레드 규칙 → `REFERENCE.md`

## Step 5: 마무리

- `_pending.jsonl` 을 `_pending.{어제}.jsonl` 로 로테이트
- 생성한 파일의 **절대 경로를 stdout 에 출력** (launchd 로그에 남는다)

## 재실행

같은 날 다시 돌리면 **아래 둘은 보존**하고 나머지 섹션만 다시 만든다.

- `## 변경 로그 (오늘)` — 하루 동안 폴링이 쌓은 로그를 브리핑 재실행이 지우면 안 된다
- `## 네가 할 일 › 결정` 의 **기존 번호와 `↳ 답:` 내용** — 번호가 결정 id 다 (`{날짜}#{번호}`)

새 결정 항목은 기존 번호 뒤에 이어 붙인다. **번호를 재정렬하지 마라.**
