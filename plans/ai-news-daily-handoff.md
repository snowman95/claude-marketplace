# Handoff: AI Agent 데일리 뉴스 레포트 서비스

## 컨텍스트

사용자가 AI Agent 트렌드를 매일 텔레그램으로 받아보는 자동화 서비스 구현을 계획 중입니다.
`/grill-me` 세션에서 주요 결정 사항을 확정했으며, 구현 위치 결정 직전에 이 문서를 작성합니다.

---

## 확정된 결정 사항

| 항목 | 결정 |
|------|------|
| 전송 채널 | 텔레그램 |
| 전송 시간 | 매일 오전 8시 |
| 모니터링 소스 | Anthropic 블로그/뉴스, OpenAI 블로그/뉴스, Cursor 블로그 (3곳) |
| 레포트 언어 | 한국어 요약 |
| 요약 깊이 | 항목당 3~5줄 + 원문 링크 |
| 필터링 | 없음 (소스 자체가 AI 관련 전문) |
| AI API 사용 | 사용 안 함 |

---

## 미확정 항목 (다음 세션에서 이어서 결정)

- **구현 위치**: 권장은 pipeline 프로젝트(`/Users/jh.han/Documents/GitHub/pipeline/`) 추가. 사용자 확인 필요.
- **중복 제거**: 이미 전송한 기사를 다음 날 다시 보내지 않으려면 상태 저장(파일 or DB) 방식 결정 필요.
- **RSS vs 크롤링**: 각 소스의 RSS 피드 존재 여부 확인 필요 (Anthropic, OpenAI, Cursor).

---

## 관련 인프라 (pipeline 프로젝트 기준)

- 스케줄러: `scheduler/engine.py` (APScheduler AsyncIOScheduler)
- 텔레그램: `shared/telegram.py`
- 스케줄 설정: `config/schedules.yaml`
- 서비스 디렉토리: `services/`

새 서비스라면 `services/ainews/` 형태로 추가하고 `config/schedules.yaml`에 8시 크론 항목을 등록하는 패턴을 따릅니다.

---

## 구현 시 참고할 RSS 피드 후보

- Anthropic: `https://www.anthropic.com/news` (RSS 여부 확인 필요)
- OpenAI: `https://openai.com/news/` (RSS 여부 확인 필요)
- Cursor: `https://www.cursor.com/blog` (RSS 여부 확인 필요)

RSS가 없으면 `feedparser` + HTML 파싱 or `requests` + BeautifulSoup으로 크롤링.

---

## 다음 세션 권장 진행 순서

1. 구현 위치 최종 확정 (pipeline 프로젝트 추가 여부)
2. 각 소스 RSS 피드 존재 여부 확인
3. `/ticket-workflow` (범용 모드)로 구현 계획 수립
4. pipeline 프로젝트에 `services/ainews/` 서비스 추가

---

## Suggested Skills

- `/ticket-workflow` — 범용 모드로 구현 계획(Research → Plan → 구현) 진행
- `/grill-me` — 미확정 항목(중복 제거, RSS vs 크롤링) 추가 결정이 필요하면 재사용
