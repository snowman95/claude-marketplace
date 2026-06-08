---
name: md-to-slides
description: 마크다운 파일을 Figma Slides 발표자료로 자동 변환한다. 파일 경로를 받아 내용을 분석하고 6~10개 슬라이드를 다크 테마로 생성한다. Use when user provides a .md file and wants a presentation, slides deck, or 발표자료.
---

# md-to-slides

마크다운 문서 → Figma Slides 발표자료 자동 변환.

## Quick Start

```
/md-to-slides /path/to/README.md
```

## Workflow

### 1. 파일 읽기 & 슬라이드 계획

Read the markdown file. 구조를 파악해 6~10개 슬라이드 계획:

| 마크다운 패턴 | 슬라이드 레이아웃 |
|------------|----------------|
| 최상위 H1 | 표지 슬라이드 (항상 첫 슬라이드) |
| H2 섹션 | 슬라이드 1개 (내용 많으면 분리) |
| 비교 테이블 (before/after) | 2-column Before/After |
| 3개 항목 나열 | 3-column 카드 |
| 단계별 흐름 | 수평 파이프라인 박스 + 화살표 |
| 계층/레이어 테이블 | full-width 행 + 컬러 좌측 바 |
| 코드 블록 | 어두운 배경 코드 패널 |
| 문제/이슈 섹션 | 마지막 슬라이드 (빨간 액센트) |

**항상 포함:**
- 슬라이드 1: 표지 (H1 제목 + 핵심 한 줄 요약)
- 마지막: 요약 / 미해결 과제 / 다음 단계

### 2. Figma Slides 파일 생성

1. `/figma-create-new-file` 스킬 로드
2. `whoami`로 planKey 확인 (개인 팀 키 사용)
3. `create_new_file` 호출: `editorType: "slides"`, 파일명은 md 파일명 기반

### 3. 슬라이드 생성

1. `/figma-use-slides` 스킬 로드
2. `use_figma`로 전체 슬라이드 한 번에 생성

**필수 규칙 (위반 시 레이아웃 깨짐):**
- 폰트 `loadFontAsync` 먼저 → 텍스트 생성 순서
- `parent.appendChild(node)` 먼저 → x/y 설정은 그 다음
- W=1920, H=1080, PAD=120 고정

디자인 상수·헬퍼 함수는 [DESIGN.md](DESIGN.md) 참조.

### 4. 검증 & 반환

- 첫 슬라이드 + 무작위 1개 스크린샷 확인
- Figma Slides URL 반환

## 액센트 컬러 할당

슬라이드 왼쪽 8px 바로 슬라이드 주제를 색으로 구분:

| 주제 | 컬러 |
|------|------|
| 중립/주요 개념 | blue |
| 문제/이슈/과제 | red |
| 기존 방식/주의 | orange |
| 개선/성공/장점 | green |
| 표지 | blue (기본) |

## See Also

- [DESIGN.md](DESIGN.md) — 컬러 팔레트, 헬퍼 함수, 레이아웃 패턴 코드
