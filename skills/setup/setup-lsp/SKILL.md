---
name: setup-lsp
description: Claude Code 개발 환경을 구성합니다 — LSP 활성화 및 TypeScript 언어 서버 설정.
disable-model-invocation: true
---

# setup

## LSP 환경 구성

LSP 활성화 이점:
- 코드 위치 검색: Grep(30~60초) → ~50ms, 100% 정확도
- 수정 후 타입 에러·누락 import를 한 턴 안에 즉시 수정 가능

사용자에게 아래 4단계를 순서대로 안내합니다. 사용자가 재시작 완료를 확인하면 완료됩니다.

**1. `~/.claude/settings.json`에 기능 플래그 추가**
```json
{ "env": { "ENABLE_LSP_TOOL": "1" } }
```

**2. TypeScript 언어 서버 전역 설치**
```bash
npm i -g typescript-language-server typescript
```

**3. 플러그인 설치**
```bash
claude plugin marketplace update claude-plugins-official
claude plugin install typescript-lsp
```

설치 후 `claude plugin list`로 상태 확인. `disabled`이면:
```bash
claude plugin enable typescript-lsp
```

**4. Claude Code 재시작** — 재시작 후 백그라운드에서 LSP 인덱싱이 시작됩니다.
