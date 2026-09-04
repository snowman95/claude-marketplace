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
import subprocess  # noqa: F401 — notify.OsascriptNotifier 가 쓰는 모듈을 테스트가 여기서 대체한다
import sys
import tempfile
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path

import notify as notify_mod
import state as state_mod
import vault as vault_mod
from atlassian import ConfluenceClient, JiraClient
from config import load_config, load_figma_token, load_token
from figma import FigmaClient

KST = timezone(timedelta(hours=9))

STATE_NAME = "_state.json"
PENDING_NAME = "_pending.jsonl"
DAILY_LOG_HEADER = "## 변경 로그"

JIRA_FIELDS = ["summary", "status", "updated", "fixVersions", "issuetype", "parent"]
PARKED_FIELDS = ["status"]
QA_FIELDS = ["summary", "description", "created"]

TICKET_KEY_RE = re.compile(r"\b(?:CWEB|WPQ|WV2Q|WWSP)-\d+\b")
HEADING_RE = re.compile(r"^#{1,2} ")

ERROR_THRESHOLD = 3
NOTIFY_TITLE = "daily-report"
SLACK_KEY = "slack"
NOTIFIED_KEY = "notified_error_at"
ERROR_HEADLINE = "🔴 daily-report 폴링 {n}회 연속 실패"


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main(argv=None):
    args = _parse_args(argv)
    now = _now(args.date)
    if now.weekday() >= 5:
        print(f"[{now:%Y-%m-%d %H:%M}] 주말 — 건너뜀")
        return 0

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
        _finish(state_path, data, now, errors, dry_run, notifier)
        _report(now, len(old_tickets), 0, [], [], dry_run, errors)
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
            cfg, issue, mds[key], declared[key], versions, modified, old
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
    _finish(state_path, data, now, errors, dry_run, notifier)
    _notify_events(notifier, data, events, now, dry_run)

    no_md = [key for key in keys if not mds[key]]
    _report(now, len(active), len(parked), events, no_md, dry_run, errors)
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

def _build_ticket(cfg, issue, paths, declared, versions, modified, old):
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    old_links = (old or {}).get("links") or {}

    return {
        "status": status.get("name") or "",
        "status_category": (status.get("statusCategory") or {}).get("name") or "",
        "updated": fields.get("updated") or "",
        "summary": fields.get("summary") or "",
        "blocked": _blocked(paths),
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
# 출력물
# ---------------------------------------------------------------------------

def _render(event, now):
    mark = "⚠️ " if event.attention else ""
    return f"- `{now:%m-%d %H:%M}` {mark}{event.text}"


def _append_pending(path, events, now, dry_run):
    if not events or dry_run:
        return False
    stamp = now.isoformat()
    payload = "".join(
        json.dumps(
            {
                "ticket": event.ticket,
                "kind": event.kind,
                "text": event.text,
                "attention": event.attention,
                "at": stamp,
            },
            ensure_ascii=False,
        )
        + "\n"
        for event in events
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


def _report(now, active_n, parked_n, events, no_md, dry_run, errors):
    tag = "[dry-run] " if dry_run else ""
    print(f"{tag}[{now:%Y-%m-%d %H:%M}] 활성 {active_n} · parked {parked_n} · 이벤트 {len(events)}")
    width = max((len(e.ticket) for e in events), default=0)
    for event in events:
        mark = "⚠️ " if event.attention else ""
        print(f"  {event.ticket.ljust(width)}  {mark}{event.text.replace('**', '')}")
    if no_md:
        print(f"  md 없음: {', '.join(no_md)}")
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
# 알림
# ---------------------------------------------------------------------------

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
    """
    if not events:
        return
    slack = data.get(SLACK_KEY)
    if not isinstance(slack, dict):
        return
    ts = str(slack.get("ts") or "").strip()
    if not ts or str(slack.get("date") or "") != f"{now:%Y-%m-%d}":
        return
    _deliver(notifier, "\n".join(_slack_line(e, now) for e in events), ts, dry_run)


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
