"""자기감시 — 살아 있는 폴링이 죽은 브리핑을 알아챈다.

브리핑은 `claude -p /daily-brief` 로 돌아서 클로드 인증이 끊기면 조용히
실패한다(2026-09-09: `401 OAuth access token has been revoked`). 로그에만 남고
아무도 모른다. 폴링은 Atlassian 토큰만 쓰므로 그때도 살아 있다. 그래서 감시는
폴링이 한다.

브리핑은 세 가지로 다르게 깨진다 — **파일 존재만 보면 뒤의 둘을 정상으로 센다.**
없음(`brief_missing`) / 부실(`brief_partial`: 필수 섹션 없음·본문 미달) /
미발송(`brief_unsent`: 파일은 멀쩡한데 `_state.json["slack"]["date"]` 가 오늘이
아니다). 사용자 입장에서 뒤의 둘도 "브리핑이 안 왔다" 다.

판정은 전부 순수 함수다. `now` 를 주입받고 내부에서 시계를 읽지 않는다.
발송·저장은 호출자(poll.py)가 한다.
"""

import json
import re
from dataclasses import dataclass
from datetime import date as date_cls, time
from pathlib import Path

# 브리핑은 세 가지로 다르게 깨진다. "파일이 있다"만 보면 뒤의 둘을 정상으로 센다.
KIND_BRIEF_MISSING = "brief_missing"   # 파일이 없다
KIND_BRIEF_PARTIAL = "brief_partial"   # 파일이 있으나 중간에 끊겼다
KIND_BRIEF_UNSENT = "brief_unsent"     # 파일은 멀쩡한데 Slack 에 안 갔다
KIND_WEEKLY = "weekly"
BRIEF_KINDS = (KIND_BRIEF_MISSING, KIND_BRIEF_PARTIAL, KIND_BRIEF_UNSENT)
KINDS = BRIEF_KINDS + (KIND_WEEKLY,)

DAILY_DIR = "daily"
WEEKLY_DIR = "weekly"
STATE_NAME = "_state.json"
SLACK_KEY = "slack"

DEFAULT_BRIEF_DEADLINE = time(9, 30)
DEFAULT_WEEKLY_DAY = 5  # 토요일
DEFAULT_MIN_LINES = 20
DEFAULT_FALLBACK = ("osascript",)

# 브리핑이 끝까지 쓰였는지 보는 표지. 둘 중 하나도 없으면 중간에 끊긴 것이다.
REQUIRED_SECTIONS = ("## 네가 할 일", "## 진행 중")

STATE_KEY = "heartbeat"

LABELS = {
    KIND_BRIEF_MISSING: "브리핑 미발행",
    KIND_BRIEF_PARTIAL: "브리핑 부실",
    KIND_BRIEF_UNSENT: "브리핑 미발송",
    KIND_WEEKLY: "주간 리포트 미발행",
}
HEADLINE_MARK = "🔴"
LOG_HINT = "→ 로그 확인: ~/.local/log/daily-report/brief.log"
OK_LABEL = "정상"

WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_WEEKDAY_NAMES = {
    "mon": 0, "monday": 0, "월": 0, "월요일": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "화": 1, "화요일": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "수": 2, "수요일": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "목": 3, "목요일": 3,
    "fri": 4, "friday": 4, "금": 4, "금요일": 4,
    "sat": 5, "saturday": 5, "토": 5, "토요일": 5,
    "sun": 6, "sunday": 6, "일": 6, "일요일": 6,
}


@dataclass(frozen=True)
class Miss:
    kind: str
    date: str
    text: str


def check(vault, now, cfg, state=None) -> list[Miss]:
    """오늘 나와야 했는데 안 나온 산출물 목록.

    과거는 보지 않는다. 지난 미발행을 매일 다시 알리면 노이즈가 되고, 이미
    알림을 한 번 받은 뒤라 새 정보도 없다.

    `state` 는 `_state.json` 의 내용이다. 주면 그것을, 안 주면 vault 에서 읽는다
    (호출자가 이미 들고 있는 값을 다시 읽어 어긋나는 일을 막는다).
    """
    vault = Path(vault)
    settings = _settings(cfg)
    today = now.date()
    misses = []

    if today.weekday() < 5:  # 브리핑은 평일에만 나온다
        deadline = _deadline(settings)
        if now.time() >= deadline:
            miss = _brief_miss(vault, today.isoformat(), deadline, settings, state)
            if miss is not None:
                misses.append(miss)

    if today.weekday() >= _weekly_day(cfg, settings):
        week = _week(today)
        if not _exists(vault / WEEKLY_DIR / f"{week}.md"):
            misses.append(
                Miss(
                    KIND_WEEKLY,
                    today.isoformat(),
                    f"주간 리포트가 없다 — {WEEKLY_DIR}/{week}.md",
                )
            )

    return misses


def _brief_miss(vault: Path, stamp: str, deadline: time, settings: dict, state) -> Miss | None:
    """없음 → 부실 → 미발송 순으로 한 단계만 판정한다.

    세 상태는 서로 배타적이다. 같은 날 두 건을 올리면 알림이 겹친다.
    """
    path = vault / DAILY_DIR / f"{stamp}.md"
    if not _exists(path):
        return Miss(
            KIND_BRIEF_MISSING,
            stamp,
            f"{deadline:%H:%M} 이 지났는데 {DAILY_DIR}/{stamp}.md 가 없다.",
        )

    text = _read(path)
    if text is None:
        return None  # 읽지 못한 것을 부실로 몰지 않는다 — 오탐이 된다

    flaw = _flaw(text, _min_lines(settings))
    if flaw:
        return Miss(
            KIND_BRIEF_PARTIAL,
            stamp,
            f"{DAILY_DIR}/{stamp}.md 는 있는데 {flaw} — 브리핑이 중간에 끊겼다.",
        )

    if not _published(vault, stamp, state):
        return Miss(
            KIND_BRIEF_UNSENT,
            stamp,
            f"{DAILY_DIR}/{stamp}.md 는 정상인데 Slack 에 안 갔다 — "
            f"발행 기록({STATE_NAME} 의 {SLACK_KEY}.date)이 오늘이 아니다.",
        )
    return None


def _flaw(text: str, min_lines: int) -> str:
    """부실한 이유. 멀쩡하면 빈 문자열."""
    if not any(section in text for section in REQUIRED_SECTIONS):
        return f"필수 섹션이 없다 ({' / '.join(REQUIRED_SECTIONS)})"
    filled = len([line for line in text.splitlines() if line.strip()])
    if filled < min_lines:
        return f"본문이 {filled}줄뿐이다 (최소 {min_lines}줄)"
    return ""


def _published(vault: Path, stamp: str, state) -> bool:
    """오늘자 브리핑이 Slack 으로 나갔는지. 판단이 안 서면 나간 것으로 본다."""
    data = _state_data(vault, state)
    if data is None:
        return True
    slack = data.get(SLACK_KEY)
    if not isinstance(slack, dict):
        return False
    return str(slack.get("date") or "") == stamp


def _state_data(vault: Path, state) -> dict | None:
    """주입된 state > vault 의 `_state.json`. 읽다 깨지면 None(판단 불가)."""
    if isinstance(state, dict):
        return state
    path = vault / DAILY_DIR / STATE_NAME
    if not _exists(path):
        return {}  # 아직 아무것도 발행되지 않았다 — 판단 가능하다
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else {}


def render(miss: Miss, note: str = "") -> str:
    """알림 본문. 첫 줄이 헤드라인, 마지막 줄이 로그 경로."""
    lines = [f"{HEADLINE_MARK} {LABELS.get(miss.kind, miss.kind)} — {_stamp(miss.date)}", miss.text]
    if note:
        lines.append(note)
    lines.append(LOG_HINT)
    return "\n".join(lines)


def label(misses) -> str:
    """stdout 요약 한 줄에 쓸 문구."""
    if not misses:
        return OK_LABEL
    seen = []
    for miss in misses:
        text = LABELS.get(miss.kind, miss.kind)
        if text not in seen:
            seen.append(text)
    return " · ".join(seen)


def latch(data: dict, misses, now) -> list[Miss]:
    """아직 안 보낸 Miss 만 돌려주고 `data[STATE_KEY]` 를 갱신한다.

    래치를 **발송 전에** 세운다. 발송 성공 여부와 무관하게 같은 날 두 번
    울리지 않는 쪽을 택한다 — 도배보다 한 번의 유실이 낫다.
    해소된(=이제 파일이 있는) 종류는 래치에서 지워 다음 미발행 때 다시 울린다.
    """
    previous = data.get(STATE_KEY)
    if not isinstance(previous, dict):
        previous = {}
    missing = {}
    for miss in misses:
        missing.setdefault(miss.kind, miss)

    fresh = {}
    pending = []
    for kind in KINDS:
        miss = missing.get(kind)
        if miss is None:
            continue  # 해소 — 래치를 남기지 않는다
        seen = previous.get(kind)
        sent_at = seen.get(miss.date) if isinstance(seen, dict) else None
        if sent_at:
            fresh[kind] = {miss.date: sent_at}
            continue
        fresh[kind] = {miss.date: f"sent at {now.isoformat(timespec='seconds')}"}
        pending.append(miss)

    if fresh or STATE_KEY in data:
        data[STATE_KEY] = fresh
    return pending


# ---------------------------------------------------------------------------
# 설정 읽기 — 잘못된 값은 기본값으로 내려간다. 감시가 설정 때문에 죽으면 안 된다.
# ---------------------------------------------------------------------------

def _settings(cfg) -> dict:
    """`[heartbeat]` 테이블. Config 객체·raw dict·테이블 자체 모두 받는다."""
    table = _get(cfg, STATE_KEY)
    if isinstance(table, dict):
        return table
    return cfg if isinstance(cfg, dict) else {}


def _deadline(settings: dict) -> time:
    matched = _HHMM_RE.match(str(settings.get("brief_deadline") or "").strip())
    if not matched:
        return DEFAULT_BRIEF_DEADLINE
    hour, minute = int(matched.group(1)), int(matched.group(2))
    if hour > 23 or minute > 59:
        return DEFAULT_BRIEF_DEADLINE
    return time(hour, minute)


def _min_lines(settings: dict) -> int:
    """`[heartbeat] min_lines` — 브리핑을 '부실'로 볼 줄 수 기준. 기본 20."""
    value = settings.get("min_lines")
    if isinstance(value, bool) or value is None:
        return DEFAULT_MIN_LINES
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_MIN_LINES
    return number if number >= 0 else DEFAULT_MIN_LINES


def fallbacks(cfg) -> list[str]:
    """`[heartbeat] fallback` — 자기감시 알림을 함께 보낼 2차 채널 이름들.

    Slack 봇 토큰이 만료되면 경고가 조용히 사라진다. 그래서 키를 생략하면
    2차 채널이 **있는** 쪽이 기본값이고, 끄려면 빈 리스트를 명시해야 한다.
    """
    settings = _settings(cfg)
    if not isinstance(settings, dict) or "fallback" not in settings:
        return list(DEFAULT_FALLBACK)
    value = settings.get("fallback")
    if value is None:
        return list(DEFAULT_FALLBACK)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_FALLBACK)
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _weekly_day(cfg, settings: dict) -> int:
    """`[heartbeat] weekly_day` > `[weekly] day` > 토요일."""
    for value in (settings.get("weekly_day"), _get(_get(cfg, WEEKLY_DIR), "day")):
        day = _as_weekday(value)
        if day is not None:
            return day
    return DEFAULT_WEEKLY_DAY


def _as_weekday(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 6 else None
    name = str(value).strip().lower()
    return _WEEKDAY_NAMES.get(name)


def _get(obj, key):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ---------------------------------------------------------------------------
# 잡동사니
# ---------------------------------------------------------------------------

def _week(day: date_cls) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _exists(path: Path) -> bool:
    """iCloud 미동기화·권한 오류를 '없음'으로 보지 않는다 — 오탐을 만들 수 있다."""
    try:
        return path.exists()
    except OSError:
        return True


def _read(path: Path) -> str | None:
    """본문. 읽지 못하면 None — '부실'로 오해하지 않게 호출자가 물러난다."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _stamp(value: str) -> str:
    try:
        day = date_cls.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{day.isoformat()} ({WEEKDAY_KO[day.weekday()]})"
