# snowman95's Claude Code Marketplace

여러 PC에서 Claude Code 스킬/플러그인을 공유하기 위한 개인 마켓플레이스.

---

## Quick start — 새 PC 셋업

```bash
# 1. GitHub 로그인
gh auth login

# 2. git이 gh 토큰을 자격증명으로 쓰도록 설정 (private repo 대비)
gh auth setup-git

# 3. Claude Code의 github source가 SSH로 시도하는 걸 HTTPS로 자동 변환
git config --global url."https://github.com/".insteadOf "git@github.com:"

# 4. 이 마켓플레이스 등록
claude plugin marketplace add snowman95/claude-marketplace

# 5. 원하는 플러그인 설치 (예시)
claude plugin install mattpocock-skills@snowman95-marketplace
```

3번을 빠뜨리면 `github` source 플러그인 설치 시 `Permission denied (publickey)`로 실패합니다.

---

## 일상 명령어

```bash
# 등록된 마켓플레이스 보기
claude plugin marketplace list

# 마켓플레이스 변경사항 가져오기 (marketplace.json이 바뀐 후)
claude plugin marketplace update snowman95-marketplace

# 설치된 플러그인 보기
claude plugin list

# 플러그인 상세 (스킬/에이전트/토큰 비용)
claude plugin details <plugin-name>

# 새 commit으로 플러그인 업데이트
claude plugin update <plugin-name>

# 제거
claude plugin uninstall <plugin-name>
```

Claude Code 안에서는 `claude plugin` 대신 `/plugin` 슬래시 명령으로 동일하게 사용 가능.

---

## 개념 정리

### Marketplace ≠ Plugin

| | Marketplace | Plugin |
|---|---|---|
| 매니페스트 | `.claude-plugin/marketplace.json` | `.claude-plugin/plugin.json` |
| 역할 | 플러그인 목록(카탈로그) | 실제 스킬/에이전트/훅 묶음 |
| 등록 | `claude plugin marketplace add` | `claude plugin install` |

**중요**: GitHub repo에 `plugin.json`만 있고 `marketplace.json`이 없으면 그건 마켓플레이스가 아니라 단일 플러그인입니다. `marketplace add`로 등록할 수 없고, **다른 마켓플레이스의 항목으로 참조**해야 합니다.

예시: `mattpocock/skills`는 plugin (마켓플레이스가 아님) → 이 마켓플레이스의 `plugins[]` 항목으로 등록함.

### 지원되는 `source` 타입

`marketplace.json`의 각 plugin 항목에서 쓸 수 있는 source는 4가지:

| 타입 | 형태 | 용도 |
|---|---|---|
| **로컬 경로 (문자열)** | `"source": "./plugins/my-plugin"` | 이 마켓플레이스 repo 안의 디렉토리 |
| **github** | `{ "source": "github", "repo": "owner/repo" }` (+ 선택: `commit`, `sha`) | repo 루트 전체가 하나의 plugin일 때 (예: mattpocock/skills) |
| **git-subdir** | `{ "source": "git-subdir", "url": "https://...", "path": "plugins/X", "ref": "main" }` (+ 선택: `sha`) | 다른 repo 안의 **서브디렉토리**가 하나의 plugin일 때 |
| **url** | `{ "source": "url", "url": "..." }` | tarball/zip URL (드물게 사용) |

---

## Recipe: 남의 GitHub repo를 내 마켓플레이스에 참조 등록 (기본 — 자동 업데이트)

대부분의 개인 사용 케이스에서는 **commit을 pin 하지 않는 것**을 권장합니다.
원작자의 기본 브랜치를 추적하므로 `claude plugin update <name>` 한 줄로 최신 변경을 받을 수 있습니다.

### 1. `marketplace.json`의 `plugins` 배열에 항목 추가

`mattpocock/skills` (repo 루트가 plugin)를 예시로:

```json
{
  "name": "mattpocock-skills",
  "description": "...",
  "author": { "name": "Matt Pocock" },
  "category": "productivity",
  "source": {
    "source": "github",
    "repo": "mattpocock/skills"
  },
  "homepage": "https://github.com/mattpocock/skills"
}
```

### 2. push & 설치

```bash
cd ~/claude-marketplace
git add . && git commit -m "Add mattpocock-skills" && git push

claude plugin marketplace update snowman95-marketplace
claude plugin install mattpocock-skills@snowman95-marketplace
```

### 3. 나중에 새 commit으로 업데이트하려면

```bash
claude plugin marketplace update snowman95-marketplace
claude plugin update mattpocock-skills
```

`marketplace.json`을 건드릴 필요 없음.

---

## Recipe (Alternative): commit을 pin 해서 등록

특정 버전에 **고정**시키고 싶을 때 사용. `marketplace.json`을 직접 수정해야만 업데이트되므로 변경이 명시적이고 감사 가능해집니다.

### 언제 pin을 쓰나

- **조직 환경 / 컴플라이언스**: 새 버전이 보안 리뷰, QA, SBOM 검증 등을 통과해야만 배포 허용
- **재현성이 중요한 환경**: 모든 팀원/CI/서버가 정확히 같은 commit을 쓰도록 보장
- **공급망 보안**: 원작자 계정이 탈취되거나 의도적으로 악의적 commit이 push 되어도 기존 pin은 영향 없음
- **신뢰도가 낮은 외부 repo**: 잘 모르는 제3자 코드를 끌어다 쓸 때 안전판
- **공식 카탈로그 운영**: 외부 기여를 받는 마켓플레이스라면 pin이 거의 필수 (공식 anthropics/claude-plugins-official도 모든 항목이 pin)

### 1. 최신 commit SHA 받기

```bash
gh api repos/mattpocock/skills/commits/main --jq '.sha'
```

### 2. `marketplace.json`에 `commit`과 `sha` 추가

```json
{
  "name": "mattpocock-skills",
  "description": "...",
  "source": {
    "source": "github",
    "repo": "mattpocock/skills",
    "commit": "e3b90b5238f38cdea5996e16861dcae28ef52eda",
    "sha":    "e3b90b5238f38cdea5996e16861dcae28ef52eda"
  }
}
```

**⚠️ 중요**: `commit`과 `sha` **둘 다 동일한 commit SHA**를 넣습니다.
`sha`를 tree SHA(`gh api repos/.../commits/main --jq '.commit.tree.sha'`로 나오는 값)로 넣으면 `Cannot switch branch to a non-commit` 에러가 납니다.

### 3. push & 설치 — 위와 동일

### 4. 새 버전으로 bump 하려면 (수동, 검증 절차 후)

```bash
gh api repos/mattpocock/skills/commits/main --jq '.sha'   # 새 SHA 확인
# (조직 환경) 코드 리뷰, 보안 스캔, 변경점 검토 등 검증 절차 수행
# marketplace.json의 commit/sha 두 곳 다 새 값으로 수정
git commit -am "Bump mattpocock-skills to <new-sha>" && git push
claude plugin marketplace update snowman95-marketplace
claude plugin update mattpocock-skills
```

이 PR/commit 자체가 "이 버전이 검증되었다"는 감사 로그가 됩니다.

---

## Recipe: 내가 만든 스킬을 이 마켓플레이스로 배포

### 1. 디렉토리 구조 만들기

```
plugins/my-plugin/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── my-skill/
        └── SKILL.md
```

### 2. `plugins/my-plugin/.claude-plugin/plugin.json`

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "...",
  "skills": ["./skills/my-skill"]
}
```

### 3. `plugins/my-plugin/skills/my-skill/SKILL.md`

```markdown
---
name: my-skill
description: 언제 이 스킬이 trigger 되어야 하는지 명확히
---

(스킬 본문)
```

### 4. 루트 `marketplace.json`에 등록

```json
{
  "name": "my-plugin",
  "description": "...",
  "source": "./plugins/my-plugin"
}
```

### 5. push, 그 다음 각 PC에서

```bash
claude plugin marketplace update snowman95-marketplace
claude plugin install my-plugin@snowman95-marketplace
```

---

## 스킬 작성 가이드라인 — 경량화가 기본 원칙

> **핵심 원칙**: 모든 설치된 스킬의 `description`은 **매 세션의 시스템 프롬프트에 항상 포함**됩니다.
> 즉, 스킬 하나하나가 **모든 대화에 영구적인 토큰 비용**을 부과합니다.
> "있으면 좋은" 정도로는 들이지 말 것. **확실히 자주 쓸 것만, 그것도 최대한 가볍게.**

### 1. 경량 스킬 vs 헤비 스킬 — 좋은 예와 나쁜 예

**👍 좋은 예: `grill-me` (mattpocock-skills)**

본문 단 3줄로 "사용자에게 끈질기게 인터뷰해서 숨겨진 맥락 끌어내기"라는 목적을 완벽히 달성:

```markdown
Interview me relentlessly about every aspect of this plan until we reach a
shared understanding. Walk down each branch of the design tree, resolving
dependencies between decisions one-by-one. For each question, provide your
recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the
codebase instead.
```

LLM의 추론 능력을 신뢰하고, 절차를 시시콜콜 지시하지 않음.
같은 목적이라면 이렇게 짧게 쓰는 것이 항상 우선.

**👎 나쁜 예: 헤비 스킬 (예: `ouroboros` 류)**

같은 "인터뷰로 숨은 맥락 파악" 목적인데 수백 줄짜리 단계별 가이드, 페르소나 정의,
state machine, 산출물 템플릿 등으로 부풀린 형태.
LLM이 이미 잘 하는 일을 굳이 손잡고 끌어주려다 토큰만 잡아먹습니다.

**판단 기준**: 같은 결과를 더 짧은 글로 얻을 수 있다면 그 짧은 글이 정답.

### 2. SKILL.md 작성 규칙

| 규칙 | 기준 |
|---|---|
| **SKILL.md 길이** | 100줄 이하 목표. 50줄 이하면 더 좋음. 10줄짜리 `grill-me`가 모범. |
| **본문 1줄** | "이 한 줄이 사라지면 스킬 의도가 망가지나?" 자문. 아니면 삭제. |
| **절차 나열** | LLM이 스스로 추론 가능한 단계는 적지 말 것. 사람이 봐도 의외인 단계만 명시. |
| **체크리스트/템플릿** | 정말 매번 깜빡하는 항목만. 일반 상식은 빼기. |
| **외부 리소스** | 100줄 넘으면 `REFERENCE.md`/`EXAMPLES.md`/`scripts/`로 분리 (progressive disclosure). |

### 3. `description` 필드가 가장 중요

스킬의 frontmatter `description`은 **에이전트가 그 스킬을 호출할지 말지 결정하는 유일한 근거**입니다 (본문은 호출된 후에야 읽힘).

**형식**:
- 최대 1024자
- 3인칭
- **1번째 문장**: 무엇을 하는가
- **2번째 문장**: `Use when [구체적인 트리거]` — 키워드, 상황, 파일 종류 등

**좋은 예**:
```
Extract text and tables from PDF files, fill forms, merge documents.
Use when working with PDF files or when user mentions PDFs, forms, or document extraction.
```

**나쁜 예**:
```
Helps with documents.
```
→ 다른 문서 관련 스킬과 구분 불가. 에이전트가 호출 안 함.

### 4. 디렉토리 구조 (progressive disclosure)

```
skill-name/
├── SKILL.md         # 필수. 가장 짧게.
├── REFERENCE.md     # 100줄 넘는 상세 — 필요할 때만 LLM이 읽음
├── EXAMPLES.md      # 케이스별 예시 — 필요할 때만 LLM이 읽음
└── scripts/         # 결정적 작업(검증/포매팅/파싱) 스크립트
    └── helper.js
```

**스크립트를 둘 때**: 결정적 연산(스키마 검증, 포맷 변환, 파일 파싱)은 LLM이 매번 재생성하기보단 스크립트로 빼는 것이 토큰과 정확도 둘 다에 이득.

### 5. 추가 전 체크리스트 (마켓플레이스에 올리기 전에)

- [ ] **description**에 구체적 트리거가 있나 (`Use when ...`)?
- [ ] **SKILL.md가 100줄 이하**인가?
- [ ] LLM이 알아서 할 수 있는 단계를 시시콜콜 지시하지 않았나?
- [ ] 같은 일을 하는 더 짧은 형태가 가능한가? 가능하면 그쪽으로.
- [ ] 100줄 넘는 자료는 `REFERENCE.md`/`EXAMPLES.md`로 분리했나?
- [ ] 시간 의존적인 정보 (날짜, 버전 핀 등)는 본문에서 빼고 자동 갱신 가능한 형태로 만들었나?
- [ ] 진짜 자주 쓸 것인가, 아니면 "있으면 좋은" 정도인가? 후자면 들이지 말 것.

### 6. 토큰 비용을 직접 확인

설치 후 항상:

```bash
claude plugin details <plugin-name>
```

`always-on` (매 세션 비용)과 `on-invoke` (호출 시 비용)이 표시됩니다.
스킬이 14개 있는 `mattpocock-skills`도 always-on이 ~1,353 토큰. 한두 줄짜리 description의 누적입니다.
이 값이 예상보다 크면 description이 길거나 항상 로드되는 자료가 있다는 신호.

---

## 시행착오 메모 (Troubleshooting)

### ❌ `git@github.com: Permission denied (publickey)`
**원인**: Claude Code의 `github` source가 SSH로 clone 시도. SSH 키 미설정.
**해결**: `git config --global url."https://github.com/".insteadOf "git@github.com:"` (한 번만)

### ❌ `Cannot switch branch to a non-commit 'xxxxx'`
**원인**: pin 모드에서 `sha` 필드에 tree SHA를 넣음.
**해결**: `commit`과 `sha` 둘 다 commit SHA (`gh api repos/.../commits/main --jq '.sha'` 결과)로 통일. 또는 pin이 필요 없으면 두 필드를 모두 제거.

### ❌ `This plugin uses a source type your Claude Code version does not support`
**원인**: 존재하지 않는 source 타입 사용 (예: `"source": "git"`).
**해결**: 위의 "지원되는 source 타입" 4가지 중 하나만 사용.

### ❌ `git-subdir` + `path: "."` → 루트 파일만 들어옴
**원인**: `git-subdir`는 sparse checkout. `.`로 지정 시 루트 파일만 들어오고 하위 디렉토리는 제외됨.
**해결**: repo 루트 전체가 plugin이면 `git-subdir` 대신 `github` source를 쓸 것. `git-subdir`는 진짜 서브디렉토리(`plugins/foo` 같은)에만.

### ❌ 플러그인이 설치는 되는데 "Skills (0)"
**원인**: 위 `git-subdir path="."` 케이스 — `.claude-plugin/plugin.json`이 안 들어와서 스킬이 인식 안 됨.
**확인**: `find ~/.claude/plugins -path '*<plugin>*' -name 'plugin.json'` 로 실제 파일 존재 확인.

---

## 참고 자료

- 공식 마켓플레이스 (소스 타입 패턴 참고용): https://github.com/anthropics/claude-plugins-official
- 로컬 마켓플레이스 캐시: `~/.claude/plugins/marketplaces/`
- 로컬 플러그인 캐시: `~/.claude/plugins/cache/<marketplace>/<plugin>/`
