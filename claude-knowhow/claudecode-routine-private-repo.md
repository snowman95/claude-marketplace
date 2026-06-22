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
