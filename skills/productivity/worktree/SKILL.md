---
name: worktree
description: >-
  Use when setting up an isolated git worktree before implementing code changes.
  Handles EnterWorktree tool, git fallback, .gitignore safety, and dependency install.
---

# worktree

격리된 워크트리를 생성하고 구현 준비를 완료한다.

## Step 0: 이미 워크트리 안인지 확인

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
# 서브모듈 여부도 확인
git rev-parse --show-superproject-working-tree 2>/dev/null
```

`GIT_DIR != GIT_COMMON` 이고 서브모듈이 아니면 이미 워크트리 안 → Step 2로 건너뜀.

## Step 1: 워크트리 생성

### 1a. 네이티브 툴 우선

`EnterWorktree` 툴이 있으면 사용하고 Step 2로 이동.

### 1b. git 직접 생성 (폴백)

1. `.worktrees/`가 `.gitignore`에 없으면 추가 후 커밋.
2. 브랜치명 결정: 티켓 키(`feat/WEB-123`) 또는 작업명 기반.
3. 브랜치가 이미 존재하면 `--track` 없이 체크아웃, 없으면 새로 생성:
   ```bash
   git worktree add .worktrees/{브랜치명} -b {브랜치명}
   ```
4. 권한 오류 시 현재 디렉토리에서 작업 계속 (워크트리 생성 실패 사용자에게 알림).

## Step 2: 의존성 설치

```bash
# 워크트리 디렉토리 안에서
[ -f package.json ] && npm install
[ -f Cargo.toml ]   && cargo build
[ -f requirements.txt ] && pip install -r requirements.txt
[ -f pyproject.toml ]   && poetry install
[ -f go.mod ]       && go mod download
```

## Step 3: 완료 보고

```
워크트리 준비 완료: .worktrees/{브랜치명}
브랜치: {브랜치명}
```

이후 모든 코드 변경은 워크트리 디렉토리 안에서 진행한다.
