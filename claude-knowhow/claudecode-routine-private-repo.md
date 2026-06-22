# Claude Code 루틴에서 Private GitHub Repo 접근 설정

## 문제

Claude.ai 루틴 편집 시 저장소 선택 목록에 private repo가 나타나지 않음.

## 원인

Claude.ai 커넥터(설정 → 커넥터 → GitHub 연동)는 **OAuth 웹 앱** 방식으로 연결되며, 이 방식은 **public repo만** 접근 가능.

## 해결 방법

**GitHub App 설치** 방식으로 연결해야 private repo 접근 가능.

### 설치 순서

1. 브라우저에서 아래 URL 접속:
   ```
   https://github.com/apps/claude
   ```
2. **Install** 클릭
3. 설치 대상 계정/조직 선택
4. **Repository access** 설정:
   - `All repositories` — 모든 repo (public + private) 접근
   - `Only select repositories` — 특정 repo만 선택
5. **Install & Authorize** 클릭

### 설치 후

- Claude.ai 루틴 편집 → 저장소 선택 드롭다운에 private repo가 나타남

## 참고: OAuth vs GitHub App 비교

| 방식 | 경로 | Private Repo |
|------|------|-------------|
| OAuth 커넥터 | claude.ai → 설정 → 커넥터 → GitHub 연동 | ❌ 불가 |
| GitHub App 설치 | github.com/apps/claude | ✅ 가능 |

## 주의

- GitHub App 설치 후 기존 OAuth 커넥터와 **별도로** 동작함
- GitHub → Settings → Applications → **Installed GitHub Apps** 탭에서 설치 확인 및 권한 수정 가능

---

# Claude Code 루틴 실행 환경 네트워크 설정

## 문제

루틴 실행 시 외부 호스트(naver.com, google trends 등)에 접근 실패 — `x-deny-reason: host_not_allowed`.  
기본 egress 정책이 화이트리스트 방식으로, pypi.org·github.com 등 일부만 허용됨.

## 해결 방법

### 설정 경로

1. [claude.ai/code](https://claude.ai/code) 접속
2. 상단 클라우드/환경 아이콘 클릭 → 환경 선택기 열림
3. 사용 중인 환경 우측 **기어 아이콘** 클릭 → 편집 다이얼로그
4. **Network access** → `Custom` 선택
5. "Also include default list of common package managers" 체크 유지 (pypi.org·github.com 등 기존 허용 유지)
6. **Allowed domains** 입력란에 도메인 추가 후 저장

### naver-blog 스킬용 허용 도메인

```
*.naver.com
trends.google.com
news.google.com
api.signal.bz
k-skill-proxy.nomadamas.org
commons.wikimedia.org
api.pexels.com
api.unsplash.com
```

> `*.naver.com` 하나로 search.naver.com, m.blog.naver.com, openapi.naver.com 모두 커버.

### 루틴으로 실행 중인 경우

루틴 설정 화면에서도 연결된 환경의 네트워크 설정을 동일하게 변경해야 함.

### 저장 후

환경 캐시 재빌드(수 분 소요) 완료 후 루틴 재실행.
