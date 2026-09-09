"""내 열린 PR 목록 — 감시 규칙 W9 의 입력.

감시 8개는 전부 Jira 티켓과 릴리즈 일정만 봤다. 그래서 **1년 넘게 열려 있는
PR 을 시스템이 한 번도 말하지 않았다** — 사람이 손으로 `gh pr list` 를 쳐서
발견했고, 손으로 친 것은 재현되지 않는다. 이 모듈이 그 조회를 고정한다.

설계에서 되돌아온 지점들:

- **`gh` CLI 를 쓴다.** 자격증명이 이미 있어서 새 토큰을 만들지 않는다.
  토큰을 하나 더 만들면 만료·보관·회수를 또 관리해야 한다.
- **어떤 실패도 밖으로 새지 않는다.** `gh` 가 없든, 인증이 끊겼든, JSON 이
  깨졌든 결과는 **빈 리스트 + stderr 한 줄** 이다. PR 조회 실패가 폴링을
  죽이면 감시 규칙 8개가 같이 죽는다 — 못 보던 것 하나를 얻으려고 보던 것
  여덟 개를 잃는 거래다.
- **`today` 는 주입받는다.** 시계를 읽지 않는다. W9 가 전부 날짜 경계에
  걸려 있어서, 여기서 오늘 날짜를 직접 읽으면 재현이 불가능해진다.
- **stderr 는 그대로 찍지 않는다.** 앞 200자로 자르고 개행을 접는다. `gh` 가
  토큰을 뱉을 일은 없지만, 로그에 무엇이 들어갈지는 이쪽이 정한다.
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

GH = "gh"
GIT = "git"

# `gh` 는 네트워크를 탄다. 타임아웃이 없으면 폴링이 한 시간짜리로 늘어난다.
TIMEOUT = 20
LIMIT = "100"

# 목록 조회에 담는 필드. **`commits`·`reviews` 를 여기 넣지 마라.**
# `--limit 100` 과 곱해지면 GitHub GraphQL 이 거부한다 (실측):
#
#   GraphQL: By the time this query traverses to the authors connection, it is
#   requesting up to 1,000,000 possible nodes which exceeds the maximum limit
#   of 500,000.
#
# 목록 전체가 빈손으로 돌아오므로, 무거운 필드 하나 때문에 PR 감시가 통째로
# 사라진다. `--limit` 을 낮춰 피하면 PR 이 많은 사람의 목록이 잘린다 — 조용히
# 잘리는 목록은 조용히 틀린 경보를 만든다.
LIST_FIELDS = (
    "number",
    "title",
    "headRefName",
    "createdAt",
    "isDraft",
    "mergeable",
    "reviewDecision",
)

# W9c("변경요청 뒤로 커밋이 없다") 판정에만 필요한 필드. `reviewDecision` 이
# `CHANGES_REQUESTED` 인 PR 에만 `gh pr view` 로 따로 묻는다 — 실측 11건 중
# 0건이라 대개 호출이 한 번도 일어나지 않는다.
DETAIL_FIELDS = ("commits", "reviews")

CHANGES_REQUESTED = "CHANGES_REQUESTED"

STDERR_LIMIT = 200


@dataclass(frozen=True)
class PullRequest:
    repo: str          # "owner/name"
    number: int
    title: str
    branch: str
    created: date
    draft: bool
    mergeable: str     # "MERGEABLE" | "CONFLICTING" | "UNKNOWN" | ""
    review: str        # "APPROVED" | "CHANGES_REQUESTED" | "REVIEW_REQUIRED" | ""
    last_commit: date | None   # 마지막 커밋 날짜 (W9c 판정용)
    # 마지막 `CHANGES_REQUESTED` 리뷰 날짜. `reviewDecision` 은 새 커밋이
    # 올라와도 그대로 남아서, 이 날짜 없이는 "그 뒤 커밋이 없다"를 판정할 수
    # 없다. 못 얻으면 None 이고, 그때 W9c 는 스스로 빠진다.
    review_at: date | None = None

    @property
    def subject(self) -> str:
        """경보의 dedup·seen 키. 리포가 달라도 번호가 겹치므로 슬러그를 붙인다."""
        return f"{self.repo}#{self.number}"


def repo_slug(path) -> str | None:
    """로컬 리포 경로 → "owner/name". 판단이 안 서면 None.

    설정에 GitHub 슬러그를 따로 받지 않으려고 `repos`(로컬 경로)에서 유도한다.
    설정 키가 하나 늘면 두 곳이 어긋날 수 있고, 어긋난 쪽은 아무도 안 고친다.
    """
    if not path:
        return None
    url = _run([GIT, "-C", str(path), "remote", "get-url", "origin"])
    if url is None:
        return None  # origin 없는 로컬 리포는 흔하다. 경보가 아니다.
    return _slug(url)


def list_open_prs(slugs, today) -> list[PullRequest]:
    """내 열린 PR 전부. **어떤 실패에도 예외를 던지지 않고 빈 리스트를 준다.**"""
    targets = []
    for slug in slugs or []:
        text = str(slug or "").strip()
        if text and text not in targets:
            targets.append(text)
    if not targets:
        return []

    if not shutil.which(GH):
        print(f"  {GH} CLI 를 찾을 수 없어 PR 감시를 건너뜁니다.", file=sys.stderr)
        return []

    found: list[PullRequest] = []
    for slug in targets:
        try:
            found.extend(_prs(slug, today))
        except Exception as exc:  # 예측하지 못한 것까지 여기서 멈춘다
            _warn(f"pr list {slug}", f"{type(exc).__name__}: {exc}")
    return found


# ---------------------------------------------------------------------------
# gh 호출
# ---------------------------------------------------------------------------

def _prs(slug, today) -> list[PullRequest]:
    label = f"pr list {slug}"
    raw = _run(_list_command(slug), label=label)
    if raw is None or not raw.strip():
        return []

    try:
        rows = json.loads(raw)
    except (ValueError, TypeError) as exc:
        # 명령은 성공했고 출력이 이상한 것이다. 다시 물어도 같은 답이 온다.
        _warn(label, f"{type(exc).__name__}: {exc}")
        return []
    if not isinstance(rows, list):
        _warn(label, f"목록이 아닌 응답: {type(rows).__name__}")
        return []

    found = []
    for row in rows:
        pull = _pull_request(slug, row, today)
        if pull is None:
            continue
        if pull.review == CHANGES_REQUESTED:
            pull = _detailed(slug, pull, today)
        found.append(pull)
    return found


def _detailed(slug, pull, today) -> PullRequest:
    """커밋·리뷰 날짜를 채운다. 못 채우면 원본을 그대로 — W9c 만 빠진다."""
    label = f"pr view {slug}#{pull.number}"
    raw = _run(_view_command(slug, pull.number), label=label)
    if raw is None or not raw.strip():
        return pull
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        _warn(label, f"{type(exc).__name__}: {exc}")
        return pull
    if not isinstance(data, dict):
        return pull
    return replace(
        pull,
        last_commit=_last_commit(data.get("commits"), today),
        review_at=_review_at(data.get("reviews"), today),
    )


def _list_command(slug) -> list[str]:
    return [
        GH, "pr", "list",
        "--repo", slug,
        "--author", "@me",
        "--state", "open",
        "--limit", LIMIT,
        "--json", ",".join(LIST_FIELDS),
    ]


def _view_command(slug, number) -> list[str]:
    return [
        GH, "pr", "view", str(number),
        "--repo", slug,
        "--json", ",".join(DETAIL_FIELDS),
    ]


def _run(argv, label=None) -> str | None:
    """stdout, 또는 실패면 None. `label` 이 있을 때만 stderr 에 한 줄 남긴다."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=TIMEOUT
        )
    except Exception as exc:  # OSError·TimeoutExpired·그 밖의 것
        if label:
            _warn(label, f"{type(exc).__name__}: {exc}")
        return None
    if getattr(result, "returncode", 0) != 0:
        if label:
            _warn(label, result.stderr or result.stdout)
        return None
    return result.stdout or ""


def _warn(label, message):
    """앞 200자만. 로그에 무엇이 들어갈지는 호출된 명령이 아니라 이쪽이 정한다."""
    text = " ".join(str(message or "").split())[:STDERR_LIMIT]
    print(f"  {GH} {label} 실패: {text}".rstrip(": "), file=sys.stderr)


# ---------------------------------------------------------------------------
# 행 파싱 — 모르는 값은 빈 문자열이나 None 으로 둔다
# ---------------------------------------------------------------------------

def _pull_request(slug, row, today) -> PullRequest | None:
    if not isinstance(row, dict):
        return None
    number = _int(row.get("number"))
    if number is None:
        return None  # 번호가 없으면 subject 를 만들 수 없다
    return PullRequest(
        repo=slug,
        number=number,
        title=_text(row.get("title")),
        branch=_text(row.get("headRefName")),
        created=_day(row.get("createdAt"), today) or today,
        draft=bool(row.get("isDraft")),
        mergeable=_text(row.get("mergeable")).upper(),
        review=_text(row.get("reviewDecision")).upper(),
        # 커밋·리뷰 날짜는 목록에 없다. 필요한 PR 만 뒤에서 따로 채운다.
        last_commit=None,
        review_at=None,
    )


def _last_commit(commits, today) -> date | None:
    days = []
    for commit in commits if isinstance(commits, list) else []:
        if not isinstance(commit, dict):
            continue
        day = _day(commit.get("committedDate") or commit.get("authoredDate"), today)
        if day:
            days.append(day)
    return max(days) if days else None


def _review_at(reviews, today) -> date | None:
    """마지막 `CHANGES_REQUESTED` 리뷰 날짜. 다른 상태는 세지 않는다."""
    days = []
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, dict):
            continue
        if _text(review.get("state")).upper() != CHANGES_REQUESTED:
            continue
        day = _day(review.get("submittedAt"), today)
        if day:
            days.append(day)
    return max(days) if days else None


def _day(value, today) -> date | None:
    """ISO 타임스탬프 → KST 날짜. 미래는 오늘로 누른다.

    `gh` 는 UTC 로 준다. UTC 15:00 은 KST 로 다음 날이므로 변환하지 않으면
    경과일이 하루 어긋난다. 미래 날짜는 음수 경과일을 만들어 규칙을 이상하게
    만들므로 오늘로 눌러 둔다 — 규칙은 산수만 하게 남긴다.
    """
    parsed = _parse(value)
    if parsed is None:
        return None
    if isinstance(today, date) and parsed > today:
        return today
    return parsed


def _parse(value) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).date()


def _int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


# ---------------------------------------------------------------------------
# 원격 URL 파싱
# ---------------------------------------------------------------------------

def _slug(url) -> str | None:
    """`https://host/owner/name.git` · `git@host:owner/name.git` → "owner/name"."""
    text = str(url or "").strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    text = text.rstrip("/")
    if not text:
        return None
    if "://" in text:
        text = text.split("://", 1)[1]
    if "@" in text:
        text = text.split("@", 1)[1]  # user:token@host 의 자격증명을 버린다
    parts = [part for part in text.replace(":", "/").split("/") if part]
    if len(parts) < 3 or "." not in parts[-3]:
        return None  # host/owner/name 세 조각이 아니면 원격 URL 이 아니다
    return f"{parts[-2]}/{parts[-1]}"
