---
name: ticket-links
description: >-
  티켓 md의 링크 레지스트리(Jira·Confluence·Figma)를 조회·등록·갱신한다.
  `/ticket-links {KEY}` 조회, `{KEY} 갱신` 최신화, `{KEY} add {URL}` 등록.
disable-model-invocation: true
---

# ticket-links

## 경계

- 티켓 md의 frontmatter `links:` 블록과 `## 변경 히스토리` 만 수정한다.
- 손으로 쓴 섹션(Research·Plan·Decision Log·문의·Blocked)을 건드리지 않는다.
- 기존 애드혹 링크 키(`related_doc`, `api_spec_e9`, `confluence_spec_url`, `epic_relates` …)를 **삭제하지 않는다.** `links:` 와 병존시킨다.

## 모드

### 조회 — `/ticket-links CWEB-1547`

md의 `links:` 를 읽고 각 항목의 최신성을 표로 보여준다. 원본을 받아오지 않는다 (버전만 확인).

```
| 종류 | 제목 | 등록 버전 | 현재 | 상태 |
|---|---|---|---|---|
| Confluence | 배송비쿠폰 상세기획 | v43 | v44 | ⚠️ 갱신 필요 |
| Confluence | E9 장바구니 쿠폰 견적 | v13 | v13 | 최신 |
```

`links:` 가 없으면 기존 애드혹 키에서 URL을 찾아 **마이그레이션 후보**로 제시하고, 사용자 승인 후 `links:` 를 만든다.

### 갱신 — `/ticket-links CWEB-1547 갱신`

1. 조회를 먼저 수행해 뒤처진 항목을 특정한다.
2. Confluence 본문을 받아 로컬 md를 갱신한다. **`docs-pull-all` 스크립트를 재사용한다** — 마크다운 변환과 `## 메모` 보존 정책이 거기 이미 구현돼 있다.

```bash
python3 ~/.claude/skills/docs-pull-all/scripts/pull.py --ids <page_id> --vault <프로젝트 vault 경로>
```

3. 갱신 전후를 비교해 **무엇이 바뀌었는지** 요약한다. 단순 오타·서식 변경과 스펙 변경을 구분해서 말한다.
4. 스펙 변경이면 `## 결정 사항 (Decision Log)` 에 넣을 항목을 제안한다. 제안만 하고, 사용자 승인 없이 쓰지 않는다.
5. `links:` 의 `version` / `last_modified` 를 최신값으로 갱신한다.
6. `## 변경 히스토리` 의 해당 `⚠️` 줄 끝에 **`✅`** 처리 표시를 붙인다 (`✅ D-03 으로 반영` 또는 `✅ 서식 변경, 영향 없음`).
   `→` 를 쓰지 마라 — 이벤트 본문(`v26 → v44`)과 구분이 안 되고 감시(W4)가 전부 해소로 오판한다.

### 등록 — `/ticket-links CWEB-1547 add <URL>`

URL 패턴으로 종류를 판별해 `links:` 에 추가한다.

| 패턴 | 종류 | 추출 |
|---|---|---|
| `…/wiki/spaces/{space}/pages/{id}` | confluence | `id`, 제목·버전은 API로 |
| `…/figma.com/design/{key}/…?node-id={node}` | figma | `file_key`, `node_id` |
| `…/browse/{KEY}` | jira | frontmatter `url:` 이 비어있을 때만 채운다 |

등록 직후의 버전·수정시각을 함께 기록한다. 그래야 다음 폴링이 "변경됨"으로 오탐하지 않는다.

## Figma 주의

Figma PAT는 만료된다. `403 Invalid token` 이면 사용자에게 재발급을 안내하고,
Figma 항목은 건너뛴 채 Confluence 갱신만 마친다. 전체를 실패시키지 않는다.
