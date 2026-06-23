# Agent Skills — Progressive Disclosure

[agentskills.io](https://agentskills.io) 스펙과 [best practices](https://agentskills.io/skill-creation/best-practices)를 바탕으로, 스킬 문서를 어떻게 쪼개고 언제 로드할지 정리한 노하우.

컨텍스트 최적화([context-optimization.md](./context-optimization.md))와 짝으로 보면 좋다.

---

## 3단계 로드 모델

| 단계 | 내용 | 시점 |
|------|------|------|
| 1. Metadata | `name`, `description` | 스킬 목록에 항상 노출 (~100 tokens) |
| 2. Instructions | `SKILL.md` 본문 | 스킬 **활성화** 시 로드 (< 5,000 tokens 권장) |
| 3. Resources | `references/`, `scripts/`, `assets/` | **해당 Step에서만** Read |

핵심: 파일을 나눴어도 SKILL.md가 "시작 시 전부 Read"라고 쓰면 3단계 이점이 사라진다.

---

## 권장 디렉터리 구조

```
skill-name/
├── SKILL.md              # 워크플로우 + Gotchas + when-to-load
├── references/
│   ├── inputs.md         # 입력·행동 규칙 (초기 Step)
│   ├── <domain>.md       # 구현 상세 (중간 Step)
│   ├── storybook.md      # (선택) Storybook 등 별도 도메인
│   └── figma-connect.md  # (선택) Code Connect 등
└── scripts/
```

**상세 문서는 전부 `references/`에 둔다.** 스킬 루트에는 `SKILL.md`와 `scripts/`만 남기는 것이 일관적이다.

스펙은 `references/`(복수) 디렉터리를 권장한다. 루트의 `REFERENCE.md` 단일 파일도 동작하지만, 신규 스킬은 `references/` + when-to-load를 우선한다.

---

## SKILL.md에 넣을 것 / 빼낼 것

### SKILL.md (항상 로드)

- 전제 조건·입력 경로
- **단계별 워크플로우** (Step 1, 2, 3…)
- **Gotchas** 5~10줄 — 에이전트가 틀리기 쉬운 비자명 규칙
- **when-to-load** — 각 Step에서 어떤 reference를 Read할지
- 검증 루프 (type-check, lint, 사용자 승인 게이트)

### references/ (필요할 때만 로드)

- 파일별 코드 작성 레시피 (types, css, hooks…)
- 입력 명세 테이블·행동 규칙·Fix Loop
- Storybook, Figma Code Connect 등 **도메인별** 상세 문서
- 긴 코드 예시·엣지케이스

---

## when-to-load 작성법

**나쁜 예** — generic 포인터:

```markdown
상세 규칙: reference.md 참고
```

**좋은 예** — Step과 트리거를 묶음:

```markdown
## Step 1 — 컨텍스트 수집
5. `$SKILL_DIR/references/inputs.md` Read

## Step 3 — 코드 생성
→ `$SKILL_DIR/references/web-codegen.md` Read

## Step 4 — Stories
→ `$SKILL_DIR/references/storybook.md` Read
```

best practices 원문: *"Read `references/api-errors.md` **if** the API returns a non-200"* — **언제** 읽을지가 핵심이다.

---

## Gotchas는 SKILL.md에 요약

agentskills.io best practices: gotcha는 에이전트가 상황을 인지하기 전에 봐야 한다.

reference 깊숙이만 두면 Step 5(css) 전까지 로드되지 않는다. SKILL.md 상단에 짧게:

```markdown
## Gotchas (css.ts·tsx 작성 전 확인)
- Loading vs Disabled: isPending일 때 disabled 함께 전달 금지
- Outline OFF: border:none 금지 → transparent border 유지
- 아이콘: resolve_icon.py --strict 필수
```

상세 예시·코드는 `references/web-codegen.md`에 둔다.

---

## 파일 분할 기준 — sweet spot

### 적절한 분할 단위 (4덩어리)

| 덩어리 | 예 | 로드 시점 |
|--------|-----|-----------|
| 파이프라인 계약 | `references/inputs.md` | Step 1 |
| 구현 레시피 | `references/web-codegen.md` | 코드 생성 Step |
| Storybook | `references/storybook.md` | Story Step |
| Code Connect | `references/figma-connect.md` | Publish Step |

### 과한 분할 (피할 것)

파일 **확장자** 기준 3분할 (`web-ui.md` / `web-css.md` / `web-hooks.md`):

- 전체 codegen 시 결국 **다 읽음** → Read 횟수만 증가
- tsx와 css 규칙이 쪼개져 **Base UI·Loading/Disabled** 같은 흐름이 끊김
- 96줄짜리 "남은 것 모음" 파일이 생김

**판단 질문**: "이 파일을 안 읽고 해당 Step을 끝낼 수 있는가?"

- Yes → 분리 가치 있음 (`references/storybook.md`, `references/figma-connect.md`)
- No → 한 파일로 (`web-codegen.md`, ~350줄 이하 권장)

### reference 인덱스 파일

`reference.md`가 SKILL.md의 when-to-load와 **중복**이면 삭제하고 SKILL.md에만 둔다.

---

## 사례: cds-codegen (myproject_ds)

CDS 컴포넌트 생성 스킬을 정리하며 얻은 교훈.

### Before (문제)

- `codegen.md` + `reference.md` 이중 구조, 레거시 경로 혼재
- Step 1에서 `reference.md`(471줄) + `storybook.md`(334줄) **통째 Read** → ~800줄 선로드
- 3-way split 후에도 Step마다 Read 반복, 총량은 비슷

### After (현재)

```
cds-codegen/
├── SKILL.md              (131줄) — Gotchas + Step 1~6
├── references/
│   ├── inputs.md         ( 87줄) — Step 1
│   ├── web-codegen.md    (348줄) — Step 3
│   ├── storybook.md      — Step 4~5
│   └── figma-connect.md  — Step 6
└── scripts/
```

| 시점 | 로드량 |
|------|--------|
| Step 1 직후 | ~87줄 |
| Step 3 | +348줄 |
| Step 4~6 | storybook / figma (필요 시) |

### 파이프라인 스킬 분리 (coherent units)

한 스킬에 get-data + codegen + qa를 넣지 않고 4스킬로 분리 — agentskills "coherent unit" 원칙과 일치:

```
cds-get-data → cds-codegen → cds-qa → cds-patch
```

---

## 체크리스트 (스킬 작성·리뷰 시)

- [ ] `SKILL.md` 500줄 이하
- [ ] `description`에 **무엇을** + **언제** 쓰는지 키워드 포함
- [ ] Step별 **when-to-load** 명시 (시작 시 전량 Read 금지)
- [ ] Gotchas가 SKILL.md에 5~10줄 요약
- [ ] reference 파일 각각 **한 도메인**, ideally < 400줄
- [ ] 같은 내용이 두 파일에 없음 (Stories 규칙은 `references/storybook.md`만)
- [ ] `scripts/`에 반복 로직이 있으면 문서 대신 스크립트로
- [ ] Fix Loop·patch 스킬도 수정 대상 reference만 Read

---

## 참고 링크

- [Specification — Progressive disclosure](https://agentskills.io/specification#progressive-disclosure)
- [Best practices for skill creators](https://agentskills.io/skill-creation/best-practices)
- [context-optimization.md](./context-optimization.md) — RTK, CLAUDE.md 경량화
