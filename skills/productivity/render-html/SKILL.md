---
name: render-html
description: >-
  Use when a skill produces a structured result (review, plan, report)
  that should be rendered as a self-contained HTML file and opened in the browser.
---

# render-html

구조화된 문서를 HTML 파일로 저장하고 브라우저에 띄운다.

## Steps

1. **템플릿 확인** — 호출 스킬 폴더에 `template.html`이 있으면 읽어서 플레이스홀더를 치환한다. 없으면 Step 1b로.
   - 플레이스홀더는 `{{KEY}}` 형식. 템플릿 내 모든 플레이스홀더를 전달받은 내용으로 채운다.

   **1b. 템플릿 없음** — 인라인 CSS로 직접 HTML을 생성한다:
   - 외부 CDN·폰트·이미지 금지
   - `@media (prefers-color-scheme: dark)` 다크모드 지원
   - 반응형 (`max-width`, `rem` 단위)

2. **Save** — `/tmp/YYYY-MM-DD-{slug}.html` 경로에 저장. slug는 문서 제목에서 파생.

3. **Open** — `open {절대경로}` 실행.

**완료 기준**: 브라우저에 파일이 열린다.
