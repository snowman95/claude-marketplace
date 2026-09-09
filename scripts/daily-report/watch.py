"""감시 계층 — 규칙 W1~W8 과 반복 억제.

폴링은 "무엇이 바뀌었나"를 본다. 감시는 **"무엇이 바뀌지 않았나"** 를 본다.
배포일이 지났는데 티켓이 안 닫혔고, ⚠️ 를 며칠째 안 봤고, 문의가 답이 없는
것 — 아무 일도 일어나지 않았기 때문에 히스토리에는 한 줄도 안 남는 것들이다.

설계에서 실전으로 세 번 되돌아온 지점들:

- **해소 마커는 `✅` 다.** 이벤트 본문이 `v26 → v44` 처럼 `→` 를 품기 때문에
  `→` 로 해소를 판정하면 W4 가 영원히 0건이 된다. 실제로 그렇게 만들었다.
- **W1~W3 은 (프로젝트, 버전) 단위로 집계한다.** 티켓별로 만들면 릴리즈 하나가
  27줄이 된다. 원인이 하나면 알림도 하나다.
- **`today` 는 주입받는다.** 이 모듈은 시계를 읽지 않는다. 규칙이 전부 날짜
  경계에 걸려 있어서, 시계를 직접 읽으면 재현이 불가능해진다.

`watch_ignore` 가 붙은 티켓은 전 규칙에서 빠진다. "방치"와 "의도적 대기"를
구분하지 못하면 이 계층은 곧 무시당하고, 무시당하는 경보는 없는 것보다 나쁘다.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import vault as vault_mod
from releases import parse_fix_version

KST = timezone(timedelta(hours=9))

DEFAULTS = {
    "deploy_soon_days": 3,
    "deploy_stale_days": 30,
    "attention_stale_days": 3,
    "attention_urgent_days": 7,
    "inquiry_silent_days": 3,
    "blocked_long_days": 7,
    "ticket_stale_days": 14,
    "parked_stale_days": 30,
}

RED = "red"
YELLOW = "yellow"
EMOJI = {RED: "🔴", YELLOW: "🟡"}

ATTENTION = "⚠️"
RESOLVED = "✅"

# poll.py 가 쓰는 히스토리 줄만 센다: "- `09-04 19:07` ⚠️ ...".
# 사람이 손으로 쓴 메모와 안내 blockquote 는 타임스탬프가 없어 여기서 걸러진다.
STAMP_RE = re.compile(r"^\s*[-*+]\s*`(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})`")

HEADING_RE = re.compile(r"^#{1,2} ")
NUMBER_RE = re.compile(r"(\d+)")
BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s*")
COMMENT_RE = re.compile(r"\s+#")

# 템플릿만 남은 섹션. 라벨만 있고 `:` 로 끝나는 줄도 빈 것으로 본다.
EMPTY_WORDS = {"없음", "해당없음", "해당 없음", "n/a", "na", "none", "null", "tbd", "-"}

# 포인터 문장 판정 — `[[문서]]` + 위임 표현 + 항목 라벨 없음.
WIKILINK_RE = re.compile(r"\[\[[^\[\]]+\]\]")
ITEM_LABEL_RE = re.compile(r"\*\*[^*]+\*\*\s*[:：]")
DELEGATION_WORDS = ("관리", "참조", "에서 본다")

DONE_CATEGORIES = {"done", "완료"}

IGNORE_KEY = "watch_ignore"
IGNORE_FALSY = {"", "false", "no", "0", "none", "null", "~", "off"}

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Alert:
    rule: str
    subject: str
    level: str
    text: str
    days: int
    tickets: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Row:
    """규칙이 필요한 형태로 정규화한 티켓 하나."""

    key: str
    entry: dict
    paths: tuple
    parked: bool
    done: bool
    updated: date | None
    release: tuple | None


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def evaluate(tickets, releases, today, cfg, mds) -> list[Alert]:
    """경보 목록. 입력을 변경하지 않고 예외를 던지지 않는다."""
    rows = []
    for key, entry in _entries(tickets):
        paths = tuple((mds or {}).get(key) or ())
        if ignore_reason(paths):
            continue  # 의도적 대기는 방치가 아니다
        rows.append(_row(key, entry, paths, cfg))

    alerts = _release_alerts(rows, releases or {}, today, cfg)
    for row in rows:
        alerts.extend(_ticket_alerts(row, today, cfg))
    return sorted(alerts, key=lambda a: (a.rule, _natural(a.subject)))


def threshold(cfg, key) -> int:
    """`[watch]` 값 > DEFAULTS. 음수·비정수는 설정 실수로 보고 기본값을 쓴다."""
    default = DEFAULTS[key]
    table = _watch_table(cfg)
    value = table.get(key)
    if value is None or isinstance(value, bool):
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def ignore_reason(paths) -> str | None:
    """md frontmatter 의 `watch_ignore` 사유. 없거나 falsy 면 None."""
    for path in paths or []:
        reason = _ignore_text(_frontmatter_value(path, IGNORE_KEY))
        if reason:
            return reason
    return None


# ---------------------------------------------------------------------------
# W1~W3 — (프로젝트, 버전) 단위 집계
# ---------------------------------------------------------------------------

def _release_alerts(rows, releases, today, cfg) -> list[Alert]:
    soon = threshold(cfg, "deploy_soon_days")
    stale = threshold(cfg, "deploy_stale_days")
    groups: dict[tuple, list[_Row]] = {}
    for row in rows:
        # 표에 없는 fixVersion 은 건너뛴다. 일정을 모르는 것은 경보가 아니다.
        if row.release and row.release in releases:
            groups.setdefault(row.release, []).append(row)

    alerts = []
    for key in sorted(groups):
        release = releases[key]
        members = sorted(groups[key], key=lambda r: _natural(r.key))
        subject = f"{release.project}{release.version}"
        label = f"{release.project} {release.version}"

        pending = tuple(r.key for r in members if not r.done)
        overdue = False
        if release.prod_deploy and pending:
            delta = (release.prod_deploy - today).days
            if delta < 0:
                overdue = True
                alerts.append(_release_alert(
                    "W1", subject, label,
                    f"배포일 {release.prod_deploy:%m-%d} {-delta}일 경과",
                    "미완료", pending, -delta,
                    _w1_level(release, -delta, stale),
                ))
            elif delta <= soon:  # W1 과 상호배타
                alerts.append(_release_alert(
                    "W2", subject, label,
                    f"배포일 {release.prod_deploy:%m-%d} D-{delta}",
                    "미완료", pending, delta, RED,
                ))

        # parked 는 개발 단계가 아니다. 적체는 W8 이 따로 본다.
        developing = tuple(r.key for r in members if not r.done and not r.parked)
        # W1 이 떴으면 W3 는 같은 티켓·같은 건수를 반복한다 — 배포일이 지났으면 QA
        # 시작일도 지났으니 W3 는 W1 의 부분집합이다. W2 는 다르다: 배포는 아직
        # 안 지났고 QA 는 시작됐을 수 있으므로 두 사실이 겹치지 않는다.
        if release.qa_start and developing and not overdue:
            days = (today - release.qa_start).days
            if days >= 0:
                phrase = "오늘" if days == 0 else f"{days}일 경과"
                alerts.append(_release_alert(
                    "W3", subject, label,
                    f"QA 시작 {release.qa_start:%m-%d} {phrase}",
                    "개발 단계", developing, days, RED,
                ))
    return alerts


def _w1_level(release, over, stale) -> str:
    """🔴 는 절대 접히지 않는다. 접히지 않는 경보에는 만료가 있어야 한다.

    이미 나간 릴리즈(`비고` 에 `배포완료`)나 경과가 `deploy_stale_days` 를 넘은
    릴리즈는 티켓 하나가 남아 있어도 오늘 손댈 일이 아니다. 🟡 로 내려 접힘
    대상에 넣는다. 6일 지난 것은 그대로 🔴 로 남는다.
    """
    if bool(getattr(release, "released", False)) or over > stale:
        return YELLOW
    return RED


def _release_alert(rule, subject, label, head, noun, keys, days, level) -> Alert:
    text = (
        f"{EMOJI[level]} {rule} [{label}] {head} "
        f"— {noun} {len(keys)}건 ({_representative(keys)})"
    )
    return Alert(rule, subject, level, text, days, tuple(keys))


# ---------------------------------------------------------------------------
# W4~W8 — 티켓 단위
# ---------------------------------------------------------------------------

def _ticket_alerts(row, today, cfg) -> list[Alert]:
    alerts = []
    alerts.extend(_w4(row, today, cfg))
    alerts.extend(_w5(row, today, cfg))
    alerts.extend(_w6(row, today, cfg))
    alerts.extend(_w7(row, today, cfg))
    alerts.extend(_w8(row, today, cfg))
    return alerts


def _w4(row, today, cfg) -> list[Alert]:
    """미처리 ⚠️ 방치. 해소는 `✅` 로만 판정한다 (`→` 는 본문에 흔하다)."""
    ages = _attention_ages(row.paths, today)
    if not ages:
        return []
    worst = max(ages)
    if worst < threshold(cfg, "attention_stale_days"):
        return []
    level = RED if worst >= threshold(cfg, "attention_urgent_days") else YELLOW
    body = f"미처리 {ATTENTION} {len(ages)}건 · 최장 {worst}일 방치"
    return [_ticket_alert("W4", row.key, level, body, worst)]


def _w5(row, today, cfg) -> list[Alert]:
    """문의 무응답. Jira 코멘트는 조회하지 않고 `updated` 를 프록시로 쓴다.

    parked 는 제외한다. 배포대기는 내 손을 떠난 상태라서, 그 티켓의 문의가
    미해결이어도 지금 내가 할 일이 없다 — W3·W7 이 parked 를 빼는 것과 같은
    이유다. 적체 자체는 W8 이 담당하므로 역할이 비지도 않는다.
    """
    if row.parked or row.updated is None or not _has_inquiry(row.paths):
        return []
    days = (today - row.updated).days
    if days < threshold(cfg, "inquiry_silent_days"):
        return []
    body = f"문의 미해결 · Jira 무응답 {days}일"
    return [_ticket_alert("W5", row.key, YELLOW, body, days)]


def _w6(row, today, cfg) -> list[Alert]:
    started = _to_date(row.entry.get("blocked_since"))
    if started is None:
        return []
    days = (today - started).days
    if days < threshold(cfg, "blocked_long_days"):
        return []
    body = f"blocked {days}일 경과 ({started.isoformat()} 부터)"
    return [_ticket_alert("W6", row.key, YELLOW, body, days)]


def _w7(row, today, cfg) -> list[Alert]:
    if row.updated is None or row.done or row.parked:
        return []
    days = (today - row.updated).days
    if days < threshold(cfg, "ticket_stale_days"):
        return []
    body = f"{days}일간 갱신 없음 ({row.entry.get('status') or '상태 미상'})"
    return [_ticket_alert("W7", row.key, YELLOW, body, days)]


def _w8(row, today, cfg) -> list[Alert]:
    if not row.parked or row.updated is None:
        return []
    days = (today - row.updated).days
    if days < threshold(cfg, "parked_stale_days"):
        return []
    body = f"배포대기 {days}일 ({row.entry.get('status') or '상태 미상'})"
    return [_ticket_alert("W8", row.key, YELLOW, body, days)]


def _ticket_alert(rule, key, level, body, days) -> Alert:
    return Alert(rule, key, level, f"{EMOJI[level]} {rule} [{key}] {body}", days, (key,))


# ---------------------------------------------------------------------------
# 반복 억제
# ---------------------------------------------------------------------------

def partition(alerts, seen, today) -> tuple[list, list]:
    """(신규, 접힘). red 는 절대 접지 않고, 월요일이면 전부 펼친다."""
    lookup = seen if isinstance(seen, dict) else {}
    expand_all = today.weekday() == 0  # 주 1회 직면
    fresh, folded = [], []
    for alert in alerts or []:
        if expand_all or alert.level == RED or not _was_seen(lookup, alert):
            fresh.append(alert)
        else:
            folded.append(alert)
    return fresh, folded


def update_seen(seen, alerts, today) -> dict:
    """지금 걸린 것만 남긴다. 해소되면 사라지고, 처음 본 날짜는 유지한다."""
    lookup = seen if isinstance(seen, dict) else {}
    stamp = today.isoformat()
    out: dict[str, dict[str, str]] = {}
    for alert in alerts or []:
        rules = lookup.get(alert.subject)
        first = rules.get(alert.rule) if isinstance(rules, dict) else None
        out.setdefault(alert.subject, {})[alert.rule] = (
            first if _is_iso_date(first) else stamp
        )
    return out


def fold_lines(alerts) -> list[str]:
    """접힌 경보를 규칙별 한 줄로. 이미 아는 것에 화면을 내주지 않는다."""
    groups: dict[str, list[Alert]] = {}
    for alert in alerts or []:
        groups.setdefault(alert.rule, []).append(alert)
    lines = []
    for rule in sorted(groups):
        members = groups[rule]
        subjects = sorted({a.subject for a in members}, key=_natural)
        emoji = EMOJI.get(members[0].level, "")
        lines.append(
            f"{emoji} {rule} 계속 {len(subjects)}건 ({_representative(subjects)})"
        )
    return lines


def _was_seen(seen, alert) -> bool:
    rules = seen.get(alert.subject)
    return isinstance(rules, dict) and bool(rules.get(alert.rule))


def _is_iso_date(value) -> bool:
    return isinstance(value, str) and bool(ISO_DATE_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# 티켓 정규화
# ---------------------------------------------------------------------------

def _entries(tickets) -> list[tuple[str, dict]]:
    """dict[key]=entry 도, entry 리스트도 받는다."""
    if isinstance(tickets, dict):
        items = list(tickets.items())
    else:
        items = [(None, entry) for entry in (tickets or [])]

    out = []
    for key, entry in items:
        if not isinstance(entry, dict):
            continue
        key = str(key or entry.get("key") or "").strip()
        if key:
            out.append((key, entry))
    return out


def _row(key, entry, paths, cfg) -> _Row:
    return _Row(
        key=key,
        entry=entry,
        paths=paths,
        parked=_is_parked(entry, cfg),
        done=_is_done(entry),
        updated=_to_date(entry.get("updated")),
        release=parse_fix_version(entry.get("fix_version")),
    )


def _is_parked(entry, cfg) -> bool:
    """엔트리의 플래그가 우선. 없으면 config 의 상태 목록으로 판정한다."""
    if "parked" in entry:
        return bool(entry["parked"])
    statuses = {
        str(s).strip().lower() for s in (_attr(cfg, "parked_statuses") or [])
    }
    return str(entry.get("status") or "").strip().lower() in statuses


def _is_done(entry) -> bool:
    if entry.get("done") is True:
        return True
    return str(entry.get("status_category") or "").strip().lower() in DONE_CATEGORIES


def _watch_table(cfg) -> dict:
    if cfg is None:
        return {}
    if isinstance(cfg, dict):
        nested = cfg.get("watch")
        return nested if isinstance(nested, dict) else cfg
    table = getattr(cfg, "watch", None)
    return table if isinstance(table, dict) else {}


def _attr(cfg, key):
    if cfg is None:
        return None
    if isinstance(cfg, dict):
        return cfg.get(key)
    return getattr(cfg, key, None)


# ---------------------------------------------------------------------------
# md 읽기 — 전부 실패 허용
# ---------------------------------------------------------------------------

def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""  # iCloud 미동기화·권한 문제는 조용히 넘긴다


def _section(path, header) -> list[str]:
    """`## 헤더` 아래 다음 1~2단 헤딩까지. 없으면 빈 리스트."""
    lines = _read(path).split("\n")
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index + 1
            break
    if start is None:
        return []
    out = []
    for line in lines[start:]:
        if HEADING_RE.match(line):
            break
        out.append(line)
    return out


def _attention_ages(paths, today) -> list[int]:
    """히스토리의 미처리 ⚠️ 줄 나이(일). 타임스탬프 없는 줄은 세지 않는다."""
    ages = []
    for path in paths:
        for line in _section(path, vault_mod.HISTORY_HEADER):
            if ATTENTION not in line or RESOLVED in line:
                continue
            stamp = _stamp(line, today)
            if stamp is None:
                continue
            ages.append((today - stamp).days)
    return ages


def _stamp(line, today) -> date | None:
    """`MM-DD HH:MM` → 오늘 기준 가장 가까운 과거 연도의 날짜."""
    match = STAMP_RE.match(line)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    for year in (today.year, today.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # 2월 29일이 없는 해
        if candidate <= today:
            return candidate
    return None


def _has_inquiry(paths) -> bool:
    """해소되지 않은 문의가 한 줄이라도 있는지.

    줄 끝의 `✅` 는 W4 와 같은 해소 마커다. 모든 문의 줄이 해소되면 문의가 없는
    것과 같다 — 이 경로가 없으면 W5 는 한 번 켜지고 영구 🟡 로 남는다.
    """
    for path in paths:
        for line in _section(path, vault_mod.BLOCKED_HEADER):
            if _is_content(line) and RESOLVED not in line:
                return True
    return False


def _is_content(line) -> bool:
    """템플릿·안내·`없음`·포인터는 내용이 아니다."""
    text = line.strip()
    if not text or text.startswith(">"):
        return False
    text = BULLET_RE.sub("", text)
    if _is_pointer(text):
        return False
    text = text.replace("**", "").replace("`", "")
    text = text.replace("*", "").strip()
    if not text or text.endswith(":") or text.endswith("："):
        return False
    if not text.strip("-–—~_ "):
        return False
    return text.lower() not in EMPTY_WORDS


def _is_pointer(text) -> bool:
    """문의가 아니라 「문의는 저기 있다」고 말하는 한 줄.

    `## 문의·Blocked` 가 실제 문의 대신 다른 문서를 가리키는 경우가 있다:

        전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` 에서 관리한다.

    이건 문의가 없다는 뜻이다. 다만 실제 문의도 위키링크를 자주 물고 오므로
    (`- **문의 내용**: [[WWSP-1820]] Q29 기준이 바뀌었는지`) 조건을 좁힌다 —
    항목 라벨이 없고 위임 표현만 있는 줄. 여기서 공격적으로 굴면 W5 가 죽는다.
    """
    if not WIKILINK_RE.search(text):
        return False
    if ITEM_LABEL_RE.search(text):
        return False  # 문의 항목 형식을 갖췄으면 실제 문의다
    return any(word in text for word in DELEGATION_WORDS)


def _frontmatter_value(path, key) -> str | None:
    """최상위 frontmatter 키 하나. 중첩된 동명 키는 보지 않는다."""
    lines = _read(path).split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    prefix = key + ":"
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        if line[:1].isspace():
            continue
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def _ignore_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text[:1] in ("\"", "'"):
        quote = text[0]
        end = text.find(quote, 1)
        text = text[1:end] if end != -1 else text[1:]
    else:
        text = COMMENT_RE.split(text, maxsplit=1)[0].strip()
    return None if text.lower() in IGNORE_FALSY else text


# ---------------------------------------------------------------------------
# 날짜·표현
# ---------------------------------------------------------------------------

def _to_date(value) -> date | None:
    """ISO 문자열/date/datetime → KST 날짜. 판단이 안 서면 None."""
    if isinstance(value, datetime):
        return _kst(value).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return _kst(datetime.fromisoformat(text)).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _kst(parsed) -> datetime:
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _natural(text) -> tuple:
    """자연순 정렬 키. WPQ-9 가 WPQ-100 앞에 오고, 타입이 섞여도 안전하다."""
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in NUMBER_RE.split(str(text))
        if part != ""
    )


def _representative(keys) -> str:
    keys = list(keys)
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    return f"{keys[0]} 외 {len(keys) - 1}건"
