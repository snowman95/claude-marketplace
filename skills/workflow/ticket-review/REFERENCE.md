# ticket-review — Phase 상세

## Phase R0: PR head checkout

1. 워크스페이스가 멀티 루트면 어느 경로가 해당 리포인지 사용자에게 확인.
2. **GitHub + `gh`**: `gh pr checkout <PR URL 또는 번호>`
3. **GitHub 외**: `git fetch origin merge-requests/<id>/head:<local-branch>` 후 checkout.
4. 미커밋 변경 있으면 stash/커밋 여부 사용자 확인 (임의 덮어쓰기 금지).
5. checkout 후 `git status`·브랜치명이 PR `headRefName`과 맞는지 확인.

## Phase R1: 티켓·문서 정렬

- 티켓 md 없으면 ticket-pull로 생성.
- ticket-workflow Phase 0~2 적용. 이미 Research·Plan이 있고 사용자가 "기존 문서로 리뷰"면 재작성하지 않고 읽기만.
- Phase 5(구현)는 수행하지 않는다.
- **버그 티켓**: QA 명확성 게이트(이슈·원인·해결·기대 결과)가 정리돼 있는지 확인. 비어 있으면 보완 요청.

## Phase R2: PR 메타 수집

```bash
gh pr view <URL> --json title,body,baseRefName,headRefName,commits,files,additions,deletions,url,author
```

Plan "수정 파일 경로"와 files 목록 1차 대조 (누락·추가 파일 표시).

## Phase R3: diff 확보

**기본: 티켓 변경분만 리뷰한다.** PR 전체 diff(`origin/<base>...HEAD`)는 동봉 커밋·다른 티켓 변경을 포함하므로 1차 스코프로 쓰지 않는다.

1. PR 커밋 목록에서 **티켓 키가 없는·다른 Jira 키 커밋**을 식별한다.
2. 티켓 변경분 diff:
   ```bash
   git fetch origin <baseRefName>
   # 예: CWEB-1456 커밋(962d462) 제외, 이후 4커밋만
   git diff <스코프외_마지막커밋>..HEAD
   ```
3. 커밋 메시지에 티켓 키가 없으면 `git show --stat <sha>`로 파일별 소속을 판별한다.
4. Plan "수정 파일 경로"와 **변경분 diff** 파일 목록을 대조한다.

diff가 크면 Plan "구현 단계"·"수정 파일 경로" 순으로 범위를 좁혀 읽는다. OpenAPI 재생성 커밋에 동반 변경(#1702 등)이 섞이면 **티켓 직접 의존 파일만** 깊게 리뷰하고 나머지는 "동봉, 미검토"로 기록한다.

## Phase R4: 7개 축 리뷰

| 축 | 확인 내용 |
|----|-----------|
| **이행** | Plan 단계·체크리스트 항목 ↔ diff 매핑 |
| **범위** | Plan에 없는 변경: 의도적 확장인지 불필요한 확장인지 |
| **누락** | Plan·완료 기준 대비 미구현·테스트·타입·에러 처리 누락 |
| **리스크** | 회귀, 보안, 성능, 다국어 규칙 위반 여부 |
| **일관성** | 기존 패턴·architecture·module research와의 정합성 |
| **품질·패턴** | 더 나은 관용구, 중복 제거, 경계 책임 분리 |
| **가독성·유지보수** | 네이밍, 함수 크기, 조건 단순화, 매직 값 상수화 |
| **대안·트레이드오프** | 현재 접근 vs 대안, 어느 쪽이 더 나은지 조건부 판단 (선택 제안) |

출력 톤: 증거와 함께 질문·권고·선택 제안 구분. "반드시 바꿔야 한다"와 제안을 섞지 않는다.

## Phase R5: 티켓 md 기록 템플릿

`## 문의·Blocked` **앞**에 추가:

```markdown
## PR 리뷰: #{number}

- **PR**: <전체 URL>
- **리뷰일**: YYYY-MM-DD
- **로컬 checkout**: `{headRefName}`
- **base → head**: `{baseRefName}` → `{headRefName}`

### 요약
한 단락.

### Plan 대비 매핑
- [ ] 체크리스트/Plan 항목 ↔ 커밋·파일

### 이슈 (심각도)
- **Must fix**: …
- **Should fix**: …
- **Nit / 질문**: …

### 제안 (선택 — 패턴·가독성·트레이드오프)
…

### 다음 액션
…
```

선택 frontmatter 추가: `last_pr_review_url`, `last_pr_review_at` (ISO).  
리뷰 섹션에 **리뷰 diff** 범위(제외 커밋·포함 커밋 SHA)를 반드시 명시한다.  
`## 문의·Blocked` 본문은 절대 덮어쓰지 않는다.

## Phase R6: HTML 렌더링

티켓 md 기록 완료 후 `render-html` 스킬을 호출해 리뷰 결과를 브라우저에 띄운다.
