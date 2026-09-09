#!/usr/bin/env python3
"""daily-report 통합 폴러.

Jira·Confluence·Figma 를 읽어 `_state.json` 과 diff 하고, 변화만 티켓 md 의
`## 변경 히스토리` 에 append 한다.

두 가지를 최우선으로 지킨다.
- **쓰기 안전성.** 손으로 쓴 노트 160여 개에 append 하므로 `--dry-run` 은 단
  한 바이트도 쓰지 않는다. 판단이 서지 않는 입력에는 이벤트를 만들지 않는다.
- **조용한 실패.** launchd 가 매시 돌리므로 어떤 API 실패에도 exit 0 이고,
  실패는 `consecutive_errors` 로만 누적한다. 3회 연속이면 알림을 띄운다.

토큰은 config.py 에서만 읽고, 이 파일은 그 값을 출력·예외에 절대 싣지 않는다.
"""

import argparse
import json
import os
import re
import shutil
import subprocess  # noqa: F401 — notify.OsascriptNotifier 가 쓰는 모듈을 테스트가 여기서 대체한다
import sys
import tempfile
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path

import decisions as decisions_mod
import heartbeat as heartbeat_mod
import notify as notify_mod
import releases as releases_mod
import state as state_mod
import vault as vault_mod
import watch as watch_mod
from atlassian import ConfluenceClient, JiraClient
from config import load_config, load_figma_token, load_token
from figma import FigmaClient

KST = timezone(timedelta(hours=9))

STATE_NAME = "_state.json"
PENDING_NAME = "_pending.jsonl"
DAILY_LOG_HEADER = "## 변경 로그"

JIRA_FIELDS = ["summary", "status", "updated", "fixVersions", "issuetype", "parent"]
PARKED_FIELDS = ["status", "updated", "fixVersions"]
QA_FIELDS = ["summary", "description", "created"]

TICKET_KEY_RE = re.compile(r"\b(?:CWEB|WPQ|WV2Q|WWSP)-\d+\b")
HEADING_RE = re.compile(r"^#{1,2} ")

ERROR_THRESHOLD = 3
NOTIFY_TITLE = "daily-report"
SLACK_KEY = "slack"
WATCH_KEY = "watch"
NOTIFIED_KEY = "notified_error_at"
ERROR_HEADLINE = "🔴 daily-report 폴링 {n}회 연속 실패"
WEEKEND_LINE = "주말 — 이벤트 알림 억제"

# --- 결정 회신 -------------------------------------------------------------
# 브리핑의 `↳ 답:` 이 유일한 회신 경로다 (Slack 봇은 발신 전용). 폴링은 그 줄을
# 감지해 이벤트·알림을 남기고 `/decision-apply` 를 띄우는 방아쇠만 당긴다.
DECISIONS_KEY = "decisions"
DECISION_KIND = "decision"
DECISION_LINE = "결정 회신: {n}건"
APPLY_LOCK_NAME = "_apply.lock"
APPLY_LOG = Path("~/.local/log/daily-report/apply.log").expanduser()
CLAUDE_BIN = "claude"
CLAUDE_FALLBACK = Path("~/.local/bin/claude").expanduser()
APPLY_PROMPT = "/decision-apply --date {date}"
DEFAULT_LOOKBACK_DAYS = 7
MAX_LOOKBACK_DAYS = 60
DEFAULT_LOCK_MINUTES = 30
# 이 두 키는 답이 바뀌면 무효다. 마음을 바꿨으면 다시 기록되어야 한다.
APPLIED_KEYS = ("applied", "decision_ref")


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main(argv=None):
    args = _parse_args(argv)
    now = _now(args.date)
    # 주말에도 끝까지 돈다. 주말에 빠지면 주간 회고 미발행을 영원히 못 잡는다.
    # 대신 티켓 이벤트로 인한 스레드 답글만 억제한다 (_notify_events).
    if _weekend(now):
        print(f"[{now:%Y-%m-%d %H:%M}] {WEEKEND_LINE}")

    try:
        cfg = load_config(Path(args.config) if args.config else None)
        token = load_token(cfg.email)
    except Exception as exc:  # 설정·자격증명은 API 실패가 아니다. 눈에 띄어야 한다.
        print(f"설정/자격증명 로드 실패: {_safe(exc)}", file=sys.stderr)
        return 1

    return run(cfg, token, now, dry_run=args.dry_run)


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="티켓 상태·문서 변경 폴러")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않는다")
    parser.add_argument("--config", help="config.toml 경로")
    parser.add_argument("--date", help="기준일 YYYY-MM-DD (테스트용)")
    # 주말 가드가 없어졌으므로 no-op 이다. 이미 이 플래그로 부르는 호출자
    # (주간 회고)가 있어 받아만 준다.
    parser.add_argument(
        "--force", action="store_true", help="하위 호환용 no-op (주말에도 항상 돈다)"
    )
    return parser.parse_args(argv)


def _now(date_str):
    """기준 시각. --date 가 있으면 날짜만 갈아끼우고 시분은 현재를 쓴다."""
    now = datetime.now(KST)
    if not date_str:
        return now
    day = date_cls.fromisoformat(date_str)
    return now.replace(year=day.year, month=day.month, day=day.day)


# ---------------------------------------------------------------------------
# 본 흐름
# ---------------------------------------------------------------------------

def run(cfg, token, now, dry_run=False):
    notifier = _build_notifier(cfg)
    alarm = _build_alarm(cfg, notifier)  # 🔴 등급 전용 — Slack 하나에 걸지 않는다
    state_path = cfg.daily_dir / STATE_NAME
    data = state_mod.load(state_path)
    old_tickets = data.get("tickets") or {}
    errors = []

    jira = JiraClient(cfg.site, cfg.email, token)
    try:
        active = jira.search(_active_jql(cfg.parked_statuses), JIRA_FIELDS)
        parked = (
            jira.search(_parked_jql(cfg.parked_statuses), PARKED_FIELDS)
            if cfg.parked_statuses
            else []
        )
    except Exception as exc:
        # Jira 없이는 diff 자체가 성립하지 않는다. 상태를 그대로 두고 물러난다.
        errors.append(_safe(exc))
        misses, pending = _heartbeat(cfg, data, now)
        # 결정 회신은 로컬 파일만 읽는다. Jira 가 죽은 날에도 답은 처리한다.
        answered = _decisions_scan(cfg, data, now)
        _append_decisions(cfg.daily_dir / PENDING_NAME, answered, now, dry_run)
        _finish(state_path, data, now, errors, dry_run, alarm)
        _notify_decisions(notifier, data, answered, now, dry_run)
        _notify_heartbeat(alarm, pending, _poll_note(len(old_tickets), 0, errors), dry_run)
        _report(now, len(old_tickets), 0, [], [], dry_run, errors, misses, answered)
        _apply_decisions(cfg, answered, now, dry_run)
        return 0

    index = vault_mod.scan(cfg.vault)
    keys = [i.get("key") or "" for i in active if i.get("key")]
    mds = {key: vault_mod.primary_mds(key, index.get(key, [])) for key in keys}
    declared = {key: _declared_links(mds[key]) for key in keys}

    versions, err = _fetch_confluence(cfg, token, _collect(declared, "confluence"))
    if err:
        errors.append(err)
    modified, err = _fetch_figma(_collect(declared, "figma"))
    if err:
        errors.append(err)

    events = []
    tickets = {}
    for issue in active:
        key = issue.get("key") or ""
        if not key:
            continue
        old = old_tickets.get(key)
        tickets[key] = _build_ticket(
            cfg, issue, mds[key], declared[key], versions, modified, old, now
        )
        baseline = old if old is not None else _md_baseline(mds[key], declared[key])
        for event in state_mod.diff_ticket(baseline, tickets[key]):
            event.ticket = key  # diff_ticket 은 키를 비워둘 수 있다
            events.append(event)

    qa_events, qa_added, err = _qa_candidates(
        jira, cfg, set(tickets), data.get("qa_candidates") or {}, now
    )
    if err:
        errors.append(err)
    events.extend(qa_events)

    lines = {}
    for event in events:
        lines.setdefault(event.ticket, []).append(_render(event, now))
    for key, entries in lines.items():
        for path in mds.get(key) or []:
            vault_mod.append_history(path, entries, dry_run=dry_run)

    _append_pending(cfg.daily_dir / PENDING_NAME, events, now, dry_run)
    _append_daily_log(cfg.daily_dir, now, [line for key in lines for line in lines[key]], dry_run)

    data["tickets"] = {**old_tickets, **tickets}
    data["qa_candidates"] = {**(data.get("qa_candidates") or {}), **qa_added}
    fresh, folded = _watch(cfg, data, tickets, parked, index, now)
    misses, pending = _heartbeat(cfg, data, now)
    answered = _decisions_scan(cfg, data, now)
    _append_decisions(cfg.daily_dir / PENDING_NAME, answered, now, dry_run)
    _finish(state_path, data, now, errors, dry_run, alarm)
    _notify_events(notifier, data, events, now, dry_run)
    _notify_decisions(notifier, data, answered, now, dry_run)
    _notify_heartbeat(alarm, pending, _poll_note(len(active), len(parked), errors), dry_run)

    no_md = [key for key in keys if not mds[key]]
    _report(now, len(active), len(parked), events, no_md, dry_run, errors, misses, answered)
    _report_watch(fresh, folded)
    # 상태를 저장한 뒤에 띄운다 — 스킬이 먼저 읽어도 최신 `decisions` 를 본다.
    _apply_decisions(cfg, answered, now, dry_run)
    return 0


# ---------------------------------------------------------------------------
# JQL
# ---------------------------------------------------------------------------

def _quoted(values):
    return ", ".join('"{}"'.format(str(v).replace('"', "")) for v in values)


def _active_jql(parked_statuses):
    clauses = ["assignee = currentUser()", "statusCategory != Done"]
    if parked_statuses:
        clauses.append(f"status NOT IN ({_quoted(parked_statuses)})")
    return " AND ".join(clauses) + " ORDER BY updated DESC"


def _parked_jql(parked_statuses):
    return f"assignee = currentUser() AND status IN ({_quoted(parked_statuses)})"


def _qa_jql(projects, lookback_days):
    return (
        f"project IN ({_quoted(projects)}) "
        f"AND created >= -{int(lookback_days)}d ORDER BY created DESC"
    )


# ---------------------------------------------------------------------------
# 링크 수집·조회
# ---------------------------------------------------------------------------

def _declared_links(paths):
    """primary md 들의 `links:` 를 합친다. {confluence:{id:ver}, figma:{key:ts}}"""
    confluence = {}
    figma = {}
    for path in paths:
        links = vault_mod.read_links(path)
        for item in links.get("confluence") or []:
            page_id = str(item.get("id") or "").strip()
            if page_id:
                confluence.setdefault(page_id, item.get("version"))
        for item in links.get("figma") or []:
            file_key = str(item.get("file_key") or "").strip()
            if file_key:
                figma.setdefault(file_key, item.get("last_modified") or "")
    return {"confluence": confluence, "figma": figma}


def _collect(declared, kind):
    out = set()
    for links in declared.values():
        out.update(links[kind])
    return out


def _fetch_confluence(cfg, token, ids):
    """(버전맵, 에러). 조회할 id 가 없으면 클라이언트를 만들지도 않는다."""
    if not ids:
        return {}, None
    try:
        client = ConfluenceClient(cfg.site, cfg.email, token)
        return client.page_versions(sorted(ids)), None
    except Exception as exc:
        return None, _safe(exc)


def _fetch_figma(file_keys):
    """(mtime 맵, 에러). Figma 실패는 Figma 만 접고 나머지는 그대로 간다."""
    if not file_keys:
        return {}, None
    token = load_figma_token()
    if not token:
        return None, None  # PAT 미설정은 에러가 아니다
    client = FigmaClient(token)
    out = {}
    for file_key in sorted(file_keys):
        try:
            value = client.last_modified(file_key)
        except Exception as exc:
            # 한 번 깨지면 나머지도 깨진다. 남은 키를 두들기지 않는다.
            return out or None, _safe(exc)
        if value:
            out[file_key] = value
    return out, None


# ---------------------------------------------------------------------------
# 티켓 조립
# ---------------------------------------------------------------------------

def _build_ticket(cfg, issue, paths, declared, versions, modified, old, now):
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    old_links = (old or {}).get("links") or {}
    blocked = _blocked(paths)

    entry = {
        "status": status.get("name") or "",
        "status_category": (status.get("statusCategory") or {}).get("name") or "",
        "updated": fields.get("updated") or "",
        "summary": fields.get("summary") or "",
        "blocked": blocked,
        "fix_version": _fix_version(fields, paths),
        "md": [_rel(cfg.vault, p) for p in paths],
        "links": {
            "confluence": _merge_links(
                declared["confluence"], versions, old_links.get("confluence") or {}
            ),
            "figma": _merge_links(
                declared["figma"], modified, old_links.get("figma") or {}
            ),
        },
    }
    since = _blocked_since(old, blocked, now)
    if since:
        entry["blocked_since"] = since
    return entry


def _fix_version(fields, paths):
    """Jira fixVersions > md frontmatter.

    fixVersions 가 비어 있는 티켓이 흔하다 (기획서 target release 로만 관리).
    md 의 `fix_version:` 이 사실상 durable 선언이므로 그쪽을 폴백으로 쓴다.
    """
    names = [
        str((v or {}).get("name") or "").strip()
        for v in (fields.get("fixVersions") or [])
        if isinstance(v, dict)
    ]
    names = [name for name in names if name]
    for name in names:
        if releases_mod.parse_fix_version(name):
            return name  # 릴리즈 표와 맞물리는 것을 우선한다
    if names:
        return names[0]
    for path in paths:
        value = vault_mod.read_frontmatter(path).get("fix_version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _blocked_since(old, blocked, now):
    """blocked 가 켜진 첫 날. False→True 에 기록하고 True→False 면 지운다."""
    if not blocked:
        return ""
    previous = str((old or {}).get("blocked_since") or "").strip()
    return previous or now.date().isoformat()


def _merge_links(declared, fetched, old):
    """조회값 > 직전 상태 > md 선언값.

    조회가 실패했거나 응답에서 빠진 항목은 직전 값을 물려받는다. 값이 사라졌다
    다시 나타나는 것처럼 보이면 없는 변경이 히스토리에 남는다.
    """
    out = {}
    for key, fallback in declared.items():
        value = fetched.get(key) if fetched is not None else None
        if value is None or value == "":
            value = old.get(key)
        if value is None or value == "":
            value = fallback
        if value is None or value == "":
            continue
        out[key] = value
    return out


def _md_baseline(paths, declared):
    """`_state.json` 에 엔트리가 없을 때 쓸 베이스라인을 md 선언값으로 조립한다.

    md 가 durable 이고 `_state.json` 은 캐시다. `jira_status` 와 `links[].version`
    /`last_modified` 는 사용자가 마지막으로 확인·반영한 값이므로, state 가 없다고
    라이브 값을 그대로 베이스라인으로 박으면 그동안 밀린 드리프트가 통째로
    사라진다 — 이 시스템이 잡아야 할 가장 중요한 신호다.

    선언이 하나도 없으면 None 을 돌려준다. 그때가 진짜 '추적 시작'이다.
    """
    status = _declared_status(paths)
    links = {
        "confluence": {
            page_id: version
            for page_id, version in declared["confluence"].items()
            if _positive_int(version) is not None
        },
        "figma": {
            file_key: value for file_key, value in declared["figma"].items() if value
        },
    }
    if not status and not links["confluence"] and not links["figma"]:
        return None
    return {"status": status, "links": links}


def _declared_status(paths):
    for path in paths:
        value = vault_mod.read_frontmatter(path).get("jira_status")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _positive_int(value):
    """version 미선언은 vault 에서 0 으로 오므로 베이스라인에서 뺀다."""
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _blocked(paths):
    for path in paths:
        value = vault_mod.read_frontmatter(path).get("blocked")
        if value is not None:
            return bool(value)
    return False


def _rel(vault, path):
    try:
        return str(Path(path).relative_to(Path(vault)))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# QA 후보
# ---------------------------------------------------------------------------

def _qa_candidates(jira, cfg, active_keys, existing, now):
    if not cfg.qa_projects:
        return [], {}, None
    try:
        issues = jira.search(_qa_jql(cfg.qa_projects, cfg.qa_lookback_days), QA_FIELDS)
    except Exception as exc:
        return [], {}, _safe(exc)

    events = []
    added = {}
    for issue in issues:
        key = issue.get("key") or ""
        # 이미 아는 후보는 state 값이 무엇이든 다시 제안하지 않는다.
        if not key or key in existing or key in added or key in active_keys:
            continue
        fields = issue.get("fields") or {}
        summary = fields.get("summary") or ""
        parent, basis = _qa_parent(key, summary, _adf_text(fields.get("description")), active_keys)
        if not parent:
            continue
        added[key] = {
            "parent": parent,
            "basis": basis,
            "state": "proposed",
            "seen": now.date().isoformat(),
        }
        events.append(
            state_mod.Event(
                parent,
                "qa_candidate",
                f"**QA 후보** {key} 「{summary}」 (근거: {basis})",
                True,
            )
        )
    return events, added, None


def _qa_parent(key, summary, description, active_keys):
    for field, text in (("summary", summary), ("description", description)):
        for mentioned in TICKET_KEY_RE.findall(text):
            if mentioned != key and mentioned in active_keys:
                return mentioned, f"{field} 언급"
    return None, ""


def _adf_text(node):
    """ADF 문서에서 텍스트만 긁어낸다. 평문 description 도 그대로 통과시킨다."""
    if isinstance(node, str):
        return node
    parts = []
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            parts.append(node["text"])
        for value in node.values():
            if isinstance(value, (dict, list)):
                parts.append(_adf_text(value))
    elif isinstance(node, list):
        for item in node:
            parts.append(_adf_text(item))
    return " ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# 결정 회신
# ---------------------------------------------------------------------------

def _decision_settings(cfg):
    table = getattr(cfg, "decisions", None)
    return dict(table) if isinstance(table, dict) else {}


def _decisions_scan(cfg, data, now):
    """최근 N일 브리핑에서 **새 답**만 골라 돌려주고 state 를 갱신한다.

    어제 결정에 오늘 답할 수 있다 — 하루만 보면 금요일 항목에 월요일 달린 답을
    영원히 놓친다. 같은 답으로 두 번 일하지 않는 판정은 `answer_hash` 가 한다.

    로컬 파일 읽기라 실패의 성격이 API 실패와 다르다. `consecutive_errors` 를
    올리지 않고 stderr 한 줄만 남긴다.
    """
    try:
        settings = _decision_settings(cfg)
        table = data.get(DECISIONS_KEY)
        table = dict(table) if isinstance(table, dict) else {}
        answered = []
        for day in _lookback_dates(now, _lookback_days(settings)):
            path = cfg.daily_dir / f"{day}.md"
            for decision in decisions_mod.answered(decisions_mod.parse(path)):
                digest = decisions_mod.hash_answer(decision.answer)
                key = decisions_mod.answer_key(decision.answer)
                previous = table.get(decision.id)
                if _seen_before(previous, digest, key):
                    continue  # 같은 답이다
                table[decision.id] = _decision_entry(previous, decision, digest, key, now)
                answered.append(decision)
        data[DECISIONS_KEY] = table
        return answered
    except Exception as exc:
        print(f"  결정 회신 감지 실패: {_safe(exc)}", file=sys.stderr)
        return []


def _seen_before(previous, digest, key):
    """이 답을 이미 처리했는지.

    `answer_hash` 는 원문 해시라 `decision-apply` 가 붙인 `✅ D-NN 기록` 마커에
    흔들린다. 마커에 둔감한 `answer_key` 를 같이 보고, 둘 중 하나라도 맞으면
    처리한 것으로 본다. `answer_key` 가 없는 엔트리는 이 기능 이전에 쌓인
    기록이므로 `answer_hash` 만으로 판정된다 — 그 결정들이 되살아나지 않는다.
    """
    if not isinstance(previous, dict):
        return False
    if previous.get("answer_hash") == digest:
        return True
    return bool(key) and previous.get("answer_key") == key


def _decision_entry(previous, decision, digest, key, now):
    """답이 바뀌면 `applied` 를 지운다 — 사람은 마음을 바꿀 수 있다."""
    entry = {}
    if isinstance(previous, dict):
        entry = {k: v for k, v in previous.items() if k not in APPLIED_KEYS}
    entry["answer_hash"] = digest
    entry["answer_key"] = key
    entry["ticket"] = decision.ticket
    entry["seen"] = now.isoformat()
    return entry


def _lookback_days(settings):
    try:
        days = int(settings.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_LOOKBACK_DAYS
    return max(1, min(days, MAX_LOOKBACK_DAYS))


def _lookback_dates(now, days):
    """오래된 날부터. 답이 달린 순서가 아니라 결정이 나온 순서로 보고한다."""
    today = now.date()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def _append_decisions(path, answered, now, dry_run):
    return _append_rows(path, [_decision_row(d, now) for d in answered], dry_run)


def _decision_row(decision, now):
    return {
        "ticket": decision.ticket,
        "kind": DECISION_KIND,
        "text": _decision_text(decision),
        "attention": False,
        "id": decision.id,
        "answer": decision.answer,
        "at": now.isoformat(),
    }


def _decision_text(decision):
    return f"**결정 회신** {_decision_title(decision)}: {decision.answer}"


def _decision_title(decision):
    """Slack·로그용 제목. 위키링크 대괄호와 중복된 티켓 키를 뺀다."""
    title = decision.title.replace("[[", "").replace("]]", "")
    if decision.ticket:
        title = title.replace(decision.ticket, " ")
    return re.sub(r"\s+", " ", title).strip()


def _decision_line(decision, now):
    ticket = f"{decision.ticket} " if decision.ticket else ""
    answer = _oneline(decision.answer)
    return f"`{now:%H:%M}` 답 접수 — {ticket}{_decision_title(decision)}: \"{answer}\""


def _notify_decisions(notifier, data, answered, now, dry_run):
    """오늘 브리핑 스레드에 답글 한 건. 루트 ts 규칙은 `_notify_events` 와 같다.

    주말이라고 접지 않는다. 억제 대상은 **내가 만든 티켓 이벤트**이고, 이건
    사람이 방금 쓴 줄에 대한 접수 확인이다 — 답을 썼는데 아무 반응이 없으면
    이 경로가 살아 있는지 알 방법이 없다.
    """
    if not answered:
        return
    ts = _briefing_ts(data, now)
    if not ts:
        return
    _deliver(notifier, "\n".join(_decision_line(d, now) for d in answered), ts, dry_run)


# --- 자동 처리 -------------------------------------------------------------

def _apply_decisions(cfg, answered, now, dry_run):
    """새 답이 있으면 `/decision-apply` 를 백그라운드로 띄운다.

    폴링은 방아쇠만 당긴다. 기록·Jira 판단은 스킬이 한다. **여기서 나는 어떤
    예외도 밖으로 내보내지 않는다** — 자동 처리 실패로 폴링이 죽으면 감시·상태
    갱신까지 같이 멈춘다.
    """
    if not answered or dry_run:
        return False
    try:
        settings = _decision_settings(cfg)
        if not _enabled(settings.get("auto_apply")):
            print("  자동 처리 꺼짐 — auto_apply = false")
            return False
        lock = cfg.daily_dir / APPLY_LOCK_NAME
        holder = _lock_holder(lock, now, _lock_minutes(settings))
        if holder:
            print(f"  자동 처리 건너뜀 — 이미 실행 중 ({holder})")
            return False
        binary = _claude_path()
        if not binary:
            print(
                f"  `{CLAUDE_BIN}` 를 찾지 못해 자동 처리를 건너뛴다 "
                f"(PATH·{CLAUDE_FALLBACK} 확인)",
                file=sys.stderr,
            )
            return False
        return _spawn_apply(binary, lock, cfg.vault, now)
    except Exception as exc:  # spawn 실패가 폴링을 죽이지 않는다
        print(f"  자동 처리 실패: {_safe(exc)}", file=sys.stderr)
        return False


def _spawn_apply(binary, lock, cwd, now):
    """완전 분리해서 띄운다. 자식이 폴링을 붙잡으면 launchd 가 매시 겹친다."""
    if not _write_lock(lock, None, now):
        print("  락을 쓰지 못해 자동 처리를 건너뛴다", file=sys.stderr)
        return False  # 락 없이 띄우면 다음 폴링과 겹친다

    argv = [str(binary), "-p", APPLY_PROMPT.format(date=f"{now:%Y-%m-%d}")]
    log = None
    try:
        log = _apply_log()
        with open(os.devnull, "rb") as devnull:
            child = subprocess.Popen(
                argv,
                stdin=devnull,          # 자식이 입력을 기다리다 매달리지 않게
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # 폴링이 죽어도 같이 죽지 않는다
                cwd=str(cwd),            # 스킬이 손댈 파일이 있는 vault 안에서 돈다
                close_fds=True,
            )
    except Exception as exc:
        _release_lock(lock)
        print(f"  자동 처리 spawn 실패: {_safe(exc)}", file=sys.stderr)
        return False
    finally:
        _close(log)

    pid = getattr(child, "pid", None)
    _write_lock(lock, pid, now)  # 겹침 창을 먼저 닫고, 실제 pid 는 뜬 뒤에 채운다
    print(f"  자동 처리 spawn — /decision-apply --date {now:%Y-%m-%d} (pid {pid})")
    return True  # wait 하지 않는다. 폴링은 여기서 손을 뗀다


def _apply_log():
    """자식의 stdout·stderr 를 붙일 파일. 못 열면 /dev/null 로 내려간다."""
    try:
        APPLY_LOG.parent.mkdir(parents=True, exist_ok=True)
        return open(APPLY_LOG, "a", encoding="utf-8")
    except OSError as exc:
        print(f"  자동 처리 로그를 열지 못했다: {_safe(exc)}", file=sys.stderr)
    try:
        return open(os.devnull, "w")
    except OSError:
        return None


def _close(handle):
    try:
        if handle is not None:
            handle.close()
    except OSError:
        pass


def _claude_path():
    found = shutil.which(CLAUDE_BIN)
    if found:
        return found
    if CLAUDE_FALLBACK.exists():
        return str(CLAUDE_FALLBACK)
    return ""


def _enabled(value):
    """설정이 없으면 켜짐. 명시적으로 끈 것만 끈다."""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def _lock_minutes(settings):
    try:
        minutes = int(settings.get("apply_lock_minutes", DEFAULT_LOCK_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_LOCK_MINUTES
    return max(1, minutes)


def _lock_holder(lock, now, minutes):
    """살아 있는 락의 설명. 없거나 만료됐으면 None — 덮어써도 된다.

    자식이 죽으면서 락을 못 지우는 일이 반드시 생긴다. 만료 없는 락은 자동
    처리를 영구히 막으므로, 시작 시각이 임계를 넘긴 락은 죽은 것으로 본다.
    """
    try:
        raw = lock.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    started = _parse_iso(data.get("started"))
    if started is None:
        return None  # 읽을 수 없는 락은 붙잡고 있지 않는다
    if now - started >= timedelta(minutes=minutes):
        return None
    return f"pid {data.get('pid') or '?'} · {started:%H:%M} 시작"


def _write_lock(lock, pid, now):
    payload = json.dumps(
        {"pid": pid, "started": now.isoformat()}, ensure_ascii=False
    ) + "\n"
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(lock, payload)
    except (OSError, ValueError) as exc:
        print(f"  락 파일 쓰기 실패: {_safe(exc)}", file=sys.stderr)
        return False
    return True


def _release_lock(lock):
    try:
        lock.unlink()
    except OSError:
        pass


def _parse_iso(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed


# ---------------------------------------------------------------------------
# 감시
# ---------------------------------------------------------------------------

def _watch(cfg, data, tickets, parked, index, now):
    """감시 규칙 평가 → `_state.json["watch"]` 갱신. (신규, 접힘) 을 돌려준다.

    로컬 계산이므로 실패의 성격이 API 실패와 다르다. `consecutive_errors` 를
    올리지 않고 stderr 한 줄만 남긴다 — 감시 계층의 버그로 "폴링 3회 연속
    실패" 알림이 울리면 본체를 못 믿게 된다.
    """
    try:
        entries = {**tickets, **_parked_entries(parked, index)}
        mds = {key: vault_mod.primary_mds(key, index.get(key, [])) for key in entries}
        table = releases_mod.load_releases(cfg.daily_dir / releases_mod.RELEASES_NAME)
        today = now.date()

        alerts = watch_mod.evaluate(entries, table, today, cfg, mds)
        seen = data.get(WATCH_KEY)
        fresh, folded = watch_mod.partition(alerts, seen, today)
        data[WATCH_KEY] = watch_mod.update_seen(seen, alerts, today)
        return fresh, folded
    except Exception as exc:
        print(f"  감시 평가 실패: {_safe(exc)}", file=sys.stderr)
        return [], []


def _parked_entries(issues, index):
    """parked 티켓을 감시 입력으로만 조립한다.

    **`_state.json["tickets"]` 에는 넣지 않는다.** 수백 건이라 state 가
    부풀고, diff 대상도 아니다 (히스토리에 남길 변화가 없다). 배포일이 지난
    릴리즈에 `Ready to Deploy` 로 쌓여 있는 것이 W1 이 잡아야 할 신호라서,
    감시에는 반드시 들어와야 한다.
    """
    entries = {}
    for issue in issues:
        key = issue.get("key") or ""
        if not key:
            continue
        fields = issue.get("fields") or {}
        entries[key] = {
            "key": key,
            "status": (fields.get("status") or {}).get("name") or "",
            "updated": fields.get("updated") or "",
            "fix_version": _fix_version(fields, vault_mod.primary_mds(key, index.get(key, []))),
            "parked": True,
        }
    return entries


def _report_watch(fresh, folded):
    """신규는 개별로, 이미 걸려 있던 것은 규칙별 집계 한 줄로."""
    if not fresh and not folded:
        return
    print(f"  감시 경보: 신규 {len(fresh)} · 이어짐 {len(folded)}")
    for alert in fresh:
        print(f"    {alert.text}")
    for line in watch_mod.fold_lines(folded):
        print(f"    {line}")


# ---------------------------------------------------------------------------
# 출력물
# ---------------------------------------------------------------------------

def _render(event, now):
    mark = "⚠️ " if event.attention else ""
    return f"- `{now:%m-%d %H:%M}` {mark}{event.text}"


def _append_pending(path, events, now, dry_run):
    stamp = now.isoformat()
    return _append_rows(
        path,
        [
            {
                "ticket": event.ticket,
                "kind": event.kind,
                "text": event.text,
                "attention": event.attention,
                "at": stamp,
            }
            for event in events
        ],
        dry_run,
    )


def _append_rows(path, rows, dry_run):
    if not rows or dry_run:
        return False
    payload = "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in rows
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError:
        return False
    return True


def _append_daily_log(daily_dir, now, lines, dry_run):
    """오늘자 daily 파일이 있고 `## 변경 로그` 섹션이 있을 때만 append."""
    if not lines:
        return False
    path = daily_dir / f"{now:%Y-%m-%d}.md"
    if not path.exists():
        return False  # 브리핑이 만든다. 여기서 만들지 않는다.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False

    doc = text.split("\n")
    start = next(
        (i for i, line in enumerate(doc) if line.strip().startswith(DAILY_LOG_HEADER)),
        None,
    )
    if start is None:
        return False
    end = next(
        (i for i in range(start + 1, len(doc)) if HEADING_RE.match(doc[i])), len(doc)
    )
    while end > start + 1 and not doc[end - 1].strip():
        end -= 1
    if dry_run:
        return True
    _write_atomic(path, "\n".join(doc[:end] + list(lines) + doc[end:]).rstrip("\n") + "\n")
    return True


def _write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _report(now, active_n, parked_n, events, no_md, dry_run, errors, misses=(), answered=()):
    tag = "[dry-run] " if dry_run else ""
    print(f"{tag}[{now:%Y-%m-%d %H:%M}] 활성 {active_n} · parked {parked_n} · 이벤트 {len(events)}")
    width = max((len(e.ticket) for e in events), default=0)
    for event in events:
        mark = "⚠️ " if event.attention else ""
        print(f"  {event.ticket.ljust(width)}  {mark}{event.text.replace('**', '')}")
    if no_md:
        print(f"  md 없음: {', '.join(no_md)}")
    if answered:
        # 0건은 찍지 않는다. 매시 도는 로그에 아무 일 없었다는 줄을 늘리지 않는다.
        print(f"  {DECISION_LINE.format(n=len(answered))}")
        for decision in answered:
            print(f"    {decision.id}  {_decision_title(decision)}")
    print(f"  자기감시: {heartbeat_mod.label(misses)}")
    for error in errors:
        print(f"  실패: {error}")


# ---------------------------------------------------------------------------
# 마무리
# ---------------------------------------------------------------------------

def _finish(state_path, data, now, errors, dry_run, notifier=None):
    if errors:
        data["consecutive_errors"] = int(data.get("consecutive_errors") or 0) + 1
        data["last_error"] = " | ".join(errors)
    else:
        data["consecutive_errors"] = 0
        data["last_error"] = None
    data["polled_at"] = now.isoformat()
    data["schema"] = state_mod.SCHEMA

    alert = _error_alert(data, errors, now)

    if not dry_run:
        try:
            state_mod.save(state_path, data)
        except OSError as exc:
            print(f"  상태 저장 실패: {_safe(exc)}", file=sys.stderr)

    if alert:
        _deliver(notifier, alert, None, dry_run)


def _error_alert(data, errors, now):
    """3회 연속 실패에 딱 한 번. 보낼 본문 아니면 None.

    래치를 저장 **전에** 세워, 발송 성공 여부와 무관하게 다음 실행이 같은
    장애로 다시 울리지 않게 한다. 도배보다 한 번의 유실이 낫다.
    """
    count = int(data.get("consecutive_errors") or 0)
    if count < ERROR_THRESHOLD:
        data[NOTIFIED_KEY] = None
        return None
    if data.get(NOTIFIED_KEY):
        return None
    data[NOTIFIED_KEY] = now.isoformat()
    reason = _oneline(data.get("last_error") or (errors[0] if errors else ""))
    return f"{ERROR_HEADLINE.format(n=count)}\n{reason or '원인 미상'}"


# ---------------------------------------------------------------------------
# 자기감시
# ---------------------------------------------------------------------------

def _heartbeat(cfg, data, now):
    """(판정된 Miss 전체, 아직 안 보낸 Miss). 래치는 여기서 세운다.

    브리핑은 `claude -p` 로 돌아 인증이 끊기면 조용히 죽는다. 폴링은 그때도
    살아 있으니 살아 있는 쪽이 감시한다. **이 감시가 폴링을 죽여서는 안 된다** —
    어떤 예외도 밖으로 내보내지 않고 '이상 없음'으로 물러난다.
    """
    try:
        misses = heartbeat_mod.check(
            cfg.vault, now, getattr(cfg, "heartbeat", None), state=data
        )
        return misses, heartbeat_mod.latch(data, misses, now)
    except Exception as exc:
        print(f"  자기감시 실패: {_safe(exc)}", file=sys.stderr)
        return [], []


def _poll_note(active_n, parked_n, errors):
    """알림에 붙일 폴링 상태 한 줄. 폴링이 살아 있다는 사실이 곧 근거다."""
    if errors:
        return f"마지막 폴링은 실패 ({_oneline(errors[0])})."
    return f"마지막 폴링은 정상 (활성 {active_n} · parked {parked_n})."


def _notify_heartbeat(notifier, misses, note, dry_run):
    """브리핑이 없으니 스레드 루트도 없다. 새 메시지로 보낸다."""
    for miss in misses:
        _deliver(notifier, heartbeat_mod.render(miss, note), None, dry_run)


# ---------------------------------------------------------------------------
# 알림
# ---------------------------------------------------------------------------

def _weekend(now):
    return now.weekday() >= 5


def _build_alarm(cfg, primary):
    """🔴 등급(자기감시·연속 실패) 발송 채널.

    일반 이벤트 알림은 primary 단독으로 남긴다 — osascript 로 매시 배너가 뜨면
    안 된다. 여기만 2차 채널을 겹쳐, Slack 봇이 죽어도 경고가 살아남는다.
    """
    try:
        names = heartbeat_mod.fallbacks(getattr(cfg, "heartbeat", None))
    except Exception as exc:
        print(f"  2차 알림 채널 설정 실패 — 단일 채널로 진행: {_safe(exc)}", file=sys.stderr)
        return primary

    primary_channel = _primary_channel(cfg)
    extra = []
    for name in names:
        if name == primary_channel:
            continue  # 같은 채널로 두 번 보내지 않는다
        built = _fallback_notifier(name)
        if built is not None:
            extra.append(built)
    if not extra:
        return primary
    return notify_mod.MultiNotifier([primary] + extra)


def _primary_channel(cfg):
    """`_build_notifier` 가 고를 채널 이름. 설정이 비면 osascript 로 내려간다."""
    settings = getattr(cfg, "notify", None)
    if isinstance(settings, dict):
        channel = str(settings.get("channel") or "").strip().lower()
        if channel:
            return channel
    return notify_mod.CHANNEL_OSASCRIPT


def _fallback_notifier(name):
    """2차 채널은 자격증명이 필요 없는 것만 쓴다 — 그게 이 장치의 요점이다."""
    if name == notify_mod.CHANNEL_OSASCRIPT:
        return notify_mod.OsascriptNotifier(NOTIFY_TITLE)
    return None


def _build_notifier(cfg):
    """`[notify]` 가 비어 있으면 기존 macOS 알림으로 내려간다."""
    settings = getattr(cfg, "notify", None)
    channel = ""
    if isinstance(settings, dict):
        channel = str(settings.get("channel") or "").strip()
    if not channel:
        return notify_mod.OsascriptNotifier(NOTIFY_TITLE)
    return notify_mod.build(cfg)


def _notify_events(notifier, data, events, now, dry_run):
    """오늘 브리핑 스레드에 한 건으로 묶어 답글.

    브리핑 ts 가 없거나 어제 것이면 보내지 않는다. 폴링이 독자적으로 루트
    메시지를 만들면 하루에 스레드가 여러 개 생긴다.

    주말에는 아예 보내지 않는다. 주말에 티켓 알림이 울리는 게 원래 피하려던
    것이다 — 감시·state 갱신은 그대로 돌고 🔴 등급만 뚫고 나간다.
    """
    if not events or _weekend(now):
        return
    ts = _briefing_ts(data, now)
    if not ts:
        return
    _deliver(notifier, "\n".join(_slack_line(e, now) for e in events), ts, dry_run)


def _briefing_ts(data, now):
    """오늘 브리핑 루트 메시지의 ts. 없거나 어제 것이면 "" (보내지 않는다)."""
    slack = data.get(SLACK_KEY)
    if not isinstance(slack, dict):
        return ""
    ts = str(slack.get("ts") or "").strip()
    if not ts or str(slack.get("date") or "") != f"{now:%Y-%m-%d}":
        return ""
    return ts


def _slack_line(event, now):
    mark = "⚠️ " if event.attention else ""
    return f"`{now:%H:%M}` {mark}{event.ticket} {_mrkdwn(event.text)}".rstrip()


def _mrkdwn(text):
    """마크다운 `**bold**` 를 Slack mrkdwn `*bold*` 로."""
    return str(text).replace("**", "*")


def _deliver(notifier, text, thread_ts, dry_run):
    """알림 실패가 폴링을 죽이지 않는다. dry-run 은 절대 발송하지 않는다."""
    if dry_run:
        where = f"thread {thread_ts}" if thread_ts else "new message"
        print(f"[dry-run] 알림({where}):")
        for line in text.split("\n"):
            print(f"    {line}")
        return
    if notifier is None:
        return
    try:
        notifier.send(text, thread_ts=thread_ts)
    except Exception as exc:
        print(f"  알림 발송 실패: {_safe(exc)}", file=sys.stderr)


def _oneline(text):
    return str(text).replace("\n", " ").strip()


def _safe(exc):
    """예외를 한 줄로. 자격증명은 여기까지 오지 않는다(config.py 가 보장)."""
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]


if __name__ == "__main__":
    sys.exit(main())
