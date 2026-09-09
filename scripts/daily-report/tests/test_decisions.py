"""결정 회신 루프 — 파서(decisions.py)와 폴링 배선(poll.py).

브리핑의 `↳ 답:` 이 유일한 회신 경로다 (Slack 봇은 발신 전용). 그래서 이 파일이
검증하는 것은 두 가지다.
- 손으로 쓴 줄을 **놓치지 않고, 없는 답을 만들지도 않는지** (parse)
- 같은 답으로 **두 번 일하지 않는지** (state·락·spawn)

실제 `claude` 를 띄우지 않고, 실제 vault·API 를 건드리지 않는다. `tests/conftest.py`
의 `spawns` 픽스처가 `subprocess.Popen` 을 전 테스트에서 가로막고 있다.
"""

import json

import pytest

import decisions as dec
import poll
import state as state_mod

TODAY = "2026-09-04"        # 금요일
YESTERDAY = "2026-09-03"
BRIEFING_TS = "1788484474.799609"


def write(tmp_path, body, name=f"{TODAY}.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse — 답의 유무
# ---------------------------------------------------------------------------

BODY = """\
---
date: 2026-09-04
---

# 2026-09-04 (금)

## 네가 할 일

### 결정

> `↳ 답:` 뒤에 한 줄 적으면 다음 폴링이 읽어서 처리한다.
> 빈칸이면 미응답으로 남는다.

1. **[shop 3.3.0] [[CWEB-1547]] D-01 결정문과 코드가 다르다**
   D-01은 평탄화 순번으로 결정했는데 코드는 조합 키를 쓴다.
   → **추천: 코드 유지 + D-01 갱신.**
   ↳ 답: 추천대로 간다

2. **[shop 3.3.0] [[CWEB-1550]] 로그 스펙을 내가 옮길까**
   시트에만 있다.
   ↳ 답:

### 문의

1. **기획 유지은** — [[CWEB-1547]] Q4
"""


def test_parse_reads_answer_and_blank(tmp_path):
    items = dec.parse(write(tmp_path, BODY))

    assert [d.id for d in items] == ["2026-09-04#1", "2026-09-04#2"]
    assert [d.index for d in items] == [1, 2]
    assert [d.date for d in items] == [TODAY, TODAY]
    assert [d.ticket for d in items] == ["CWEB-1547", "CWEB-1550"]
    assert items[0].answer == "추천대로 간다"
    assert items[1].answer == ""


def test_parse_drops_markdown_emphasis_from_the_title(tmp_path):
    items = dec.parse(write(tmp_path, BODY))

    assert items[0].title == "[shop 3.3.0] [[CWEB-1547]] D-01 결정문과 코드가 다르다"
    assert "**" not in items[0].title


def test_answered_and_pending_split_the_list(tmp_path):
    items = dec.parse(write(tmp_path, BODY))

    assert [d.index for d in dec.answered(items)] == [1]
    assert [d.index for d in dec.pending(items)] == [2]


def test_parse_joins_a_multiline_answer(tmp_path):
    body = """\
### 결정

1. **여러 줄로 답한다**
   설명.
   ↳ 답: 첫 줄이고
      둘째 줄이며
      셋째 줄이다
"""
    (item,) = dec.parse(write(tmp_path, body))

    assert item.answer == "첫 줄이고 둘째 줄이며 셋째 줄이다"


def test_parse_survives_blank_lines_between_items(tmp_path):
    body = """\
### 결정


1. **첫 항목**

   설명 한 줄.

   ↳ 답: 첫 답


2. **둘째 항목**

   ↳ 답: 둘째 답

"""
    items = dec.parse(write(tmp_path, body))

    assert [d.answer for d in items] == ["첫 답", "둘째 답"]


def test_parse_stops_at_the_next_item(tmp_path):
    """빈 줄이 답을 끊지 않는다 — 하지만 다음 번호 항목은 끊는다."""
    body = """\
### 결정

1. **첫 항목**
   ↳ 답: 내 답
2. **둘째 항목**
   ↳ 답: 남의 답
"""
    items = dec.parse(write(tmp_path, body))

    assert [d.answer for d in items] == ["내 답", "남의 답"]


def test_parse_stops_at_the_next_header(tmp_path):
    body = """\
### 결정

1. **항목**
   ↳ 답: 내 답

## 다음 섹션

본문이 딸려 들어오면 안 된다.
"""
    (item,) = dec.parse(write(tmp_path, body))

    assert item.answer == "내 답"


def test_parse_ignores_an_unindented_continuation(tmp_path):
    body = """\
### 결정

1. **항목**
   ↳ 답: 내 답
남의 문단이다
"""
    (item,) = dec.parse(write(tmp_path, body))

    assert item.answer == "내 답"


# ---------------------------------------------------------------------------
# parse — 없는 것
# ---------------------------------------------------------------------------

def test_parse_without_the_section_is_empty(tmp_path):
    body = "# 2026-09-04\n\n## 진행 중\n\n1. **항목**\n   ↳ 답: 답\n"

    assert dec.parse(write(tmp_path, body)) == []


def test_parse_of_a_missing_file_is_empty_and_raises_nothing(tmp_path):
    assert dec.parse(tmp_path / "nope.md") == []


def test_parse_of_a_directory_raises_nothing(tmp_path):
    assert dec.parse(tmp_path) == []


def test_decision_log_header_is_not_the_decision_section(tmp_path):
    """티켓 md 의 `## 결정 사항 (Decision Log)` 을 물면 안 된다."""
    body = "## 결정 사항 (Decision Log)\n\n1. **D-01**\n   ↳ 답: 아니다\n"

    assert dec.parse(write(tmp_path, body)) == []


def test_empty_section_is_empty(tmp_path):
    body = "### 결정\n\n> 없음\n\n### 문의\n"

    assert dec.parse(write(tmp_path, body)) == []


# ---------------------------------------------------------------------------
# parse — 표기의 흔들림
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mark", ["↳", "→", "->"])
def test_all_three_answer_marks_are_accepted(tmp_path, mark):
    body = f"### 결정\n\n1. **항목**\n   {mark} 답: 받아들인다\n"

    (item,) = dec.parse(write(tmp_path, body))

    assert item.answer == "받아들인다"


@pytest.mark.parametrize(
    "line, expected",
    [
        ("   ↳ 답:", ""),
        ("   ↳ 답:   ", ""),
        ("   ↳ 답: \t ", ""),
        ("   ↳ 답: x", "x"),
    ],
)
def test_only_whitespace_after_the_colon_is_unanswered(tmp_path, line, expected):
    body = f"### 결정\n\n1. **항목**\n{line}\n"

    (item,) = dec.parse(write(tmp_path, body))

    assert item.answer == expected


@pytest.mark.parametrize(
    "form, expected",
    [
        ("[[CWEB-1547]]", "CWEB-1547"),
        ("<https://x.example/browse/CWEB-1547|CWEB-1547>", "CWEB-1547"),
        ("[[WV2Q-53784]]", "WV2Q-53784"),
        ("CWEB-1547", ""),  # 맨 키는 오탐이 많아 받지 않는다
        ("티켓 없음", ""),
    ],
)
def test_ticket_key_extraction(tmp_path, form, expected):
    body = f"### 결정\n\n1. **{form} 제목**\n   ↳ 답: 답\n"

    (item,) = dec.parse(write(tmp_path, body))

    assert item.ticket == expected


def test_ticket_key_is_found_in_the_body_too(tmp_path):
    body = "### 결정\n\n1. **제목만 있다**\n   [[CWEB-1550]] 이 막고 있다.\n   ↳ 답: 답\n"

    (item,) = dec.parse(write(tmp_path, body))

    assert item.ticket == "CWEB-1550"


# ---------------------------------------------------------------------------
# 해시 — 처리 완료 마커는 답이 아니다
# ---------------------------------------------------------------------------

def test_hash_changes_when_the_answer_changes():
    assert dec.hash_answer("A 로 간다") != dec.hash_answer("B 로 간다")
    assert len(dec.hash_answer("A 로 간다")) == 12


def test_hash_is_the_raw_answer_so_old_state_still_matches():
    """이미 `_state.json` 에 이 값으로 쌓인 기록이 있다. 정규화하면 다 되살아난다."""
    import hashlib

    raw = "A 로 간다 ✅ D-03 기록"
    assert dec.hash_answer(raw) == hashlib.sha256(raw.encode()).hexdigest()[:12]


def test_answer_key_ignores_the_applied_marker():
    """`decision-apply` 가 붙인 `✅ D-03 기록` 때문에 재처리되면 한 바퀴 헛돈다."""
    assert dec.answer_key("A 로 간다") == dec.answer_key("A 로 간다 ✅ D-03 기록")
    assert dec.answer_key("A 로 간다") != dec.answer_key("B 로 간다")


def test_answer_key_ignores_whitespace():
    assert dec.answer_key("A 로  간다 ") == dec.answer_key("A 로 간다")


def test_an_answer_that_is_only_a_marker_has_no_key():
    """마커뿐인 답까지 같은 키로 묶으면 서로 다른 답이 같아 보인다."""
    assert dec.answer_key("✅ D-03 기록") == ""
    assert dec.answer_key("") == ""


# ---------------------------------------------------------------------------
# poll.py 배선 — 장비
# ---------------------------------------------------------------------------

SECTION = """\
# {date}

## 네가 할 일

### 결정

1. **[shop 3.3.0] [[CWEB-1547]] D-01 정합성**
   설명 한 줄.
   ↳ 답: {first}

2. **[shop 3.3.0] [[CWEB-1550]] 로그 스펙을 내가 옮길까**
   ↳ 답: {second}

## 진행 중
"""


class FakeJira:
    def __call__(self, site, email, token):
        return self

    def search(self, jql, fields, max_results=100):
        return []


class FakeConfluence:
    def __call__(self, site, email, token):
        return self

    def page_versions(self, ids):
        return {}


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text, thread_ts=None):
        self.sent.append({"text": text, "thread_ts": thread_ts})
        return BRIEFING_TS

    def update(self, ts, text):
        return False

    @property
    def texts(self):
        return [call["text"] for call in self.sent]


class Rig:
    """폴링을 tmp_path 안에 가둔다. API·vault·프로세스를 건드리지 않는다."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.vault = tmp_path / "projects"
        self.daily = self.vault / "daily"
        self.daily.mkdir(parents=True)
        self.log = tmp_path / "apply.log"
        self.claude = tmp_path / "bin" / "claude"
        self.claude.parent.mkdir(parents=True)
        self.claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.config = tmp_path / "config.toml"
        self.notifier = FakeNotifier()
        self._monkeypatch = monkeypatch
        self.settings(None)

        monkeypatch.setattr(poll, "JiraClient", FakeJira())
        monkeypatch.setattr(poll, "ConfluenceClient", FakeConfluence())
        monkeypatch.setattr(poll, "load_token", lambda email: "atl-token")
        monkeypatch.setattr(poll, "load_figma_token", lambda: None)
        monkeypatch.setattr(poll, "_build_notifier", lambda cfg: self.notifier)
        monkeypatch.setattr(poll, "_heartbeat", lambda cfg, data, now: ([], []))
        monkeypatch.setattr(poll, "APPLY_LOG", self.log)
        monkeypatch.setattr(poll.shutil, "which", lambda name: str(self.claude))
        monkeypatch.setattr(poll.subprocess, "run", lambda *a, **k: None)

    # --- 설정 -------------------------------------------------------------
    def settings(self, table):
        lines = [
            f'vault = "{self.vault}"',
            'site = "example.atlassian.net"',
            'email = "me@example.com"',
            "parked_statuses = []",
            "qa_projects = []",
            "qa_lookback_days = 7",
            "repos = []",
        ]
        if table:
            lines.append("[decisions]")
            lines += list(table)
        self.config.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def no_claude(self):
        self._monkeypatch.setattr(poll.shutil, "which", lambda name: None)
        self._monkeypatch.setattr(poll, "CLAUDE_FALLBACK", self.tmp / "nope")

    # --- 입력 -------------------------------------------------------------
    def brief(self, date=TODAY, first="추천대로", second=""):
        path = self.daily / f"{date}.md"
        path.write_text(
            SECTION.format(date=date, first=first, second=second), encoding="utf-8"
        )
        return path

    def seed(self, slack=True, decisions=None):
        data = state_mod.empty_state()
        if slack:
            data["slack"] = {"date": TODAY, "ts": BRIEFING_TS}
        if decisions is not None:
            data["decisions"] = decisions
        state_mod.save(self.state_path, data)
        return data

    def lock(self, started, pid=999):
        path = self.daily / poll.APPLY_LOCK_NAME
        path.write_text(
            json.dumps({"pid": pid, "started": started}), encoding="utf-8"
        )
        return path

    # --- 실행 -------------------------------------------------------------
    def run(self, date=TODAY, dry_run=False):
        argv = ["--config", str(self.config), "--date", date]
        if dry_run:
            argv.append("--dry-run")
        return poll.main(argv)

    # --- 산출물 -----------------------------------------------------------
    @property
    def state_path(self):
        return self.daily / "_state.json"

    @property
    def lock_path(self):
        return self.daily / poll.APPLY_LOCK_NAME

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def recorded(self):
        return self.state().get("decisions") or {}

    def pending(self):
        path = self.daily / "_pending.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


def clock(minutes_ago):
    """`--date TODAY` 로 고정된 폴링 시각 기준 n분 전의 ISO 문자열."""
    from datetime import datetime, timedelta

    now = datetime.now(poll.KST).replace(
        year=2026, month=9, day=int(TODAY.split("-")[2])
    )
    return (now - timedelta(minutes=minutes_ago)).isoformat()


# ---------------------------------------------------------------------------
# poll.py 배선 — 새 답
# ---------------------------------------------------------------------------

def test_new_answer_becomes_event_state_thread_reply_and_spawn(rig, spawns, capsys):
    rig.brief(first="추천대로 간다")
    rig.seed()

    assert rig.run() == 0

    (row,) = rig.pending()
    assert row["kind"] == "decision"
    assert row["ticket"] == "CWEB-1547"
    assert row["id"] == "2026-09-04#1"
    assert row["answer"] == "추천대로 간다"
    assert row["attention"] is False

    entry = rig.recorded()["2026-09-04#1"]
    assert entry["answer_hash"] == dec.hash_answer("추천대로 간다")
    assert entry["seen"].startswith(TODAY)

    assert len(rig.notifier.sent) == 1
    call = rig.notifier.sent[0]
    assert call["thread_ts"] == BRIEFING_TS
    assert "답 접수" in call["text"]
    assert "CWEB-1547" in call["text"]
    assert '"추천대로 간다"' in call["text"]

    assert len(spawns.calls) == 1
    assert "결정 회신: 1건" in capsys.readouterr().out


def test_spawn_is_detached_and_logged(rig, spawns):
    rig.brief(first="간다")
    rig.seed()

    assert rig.run() == 0

    call = spawns.calls[0]
    assert call["argv"] == [str(rig.claude), "-p", f"/decision-apply --date {TODAY}"]
    assert call["kwargs"]["start_new_session"] is True
    assert call["kwargs"]["stdin"] is not None      # /dev/null. 입력을 기다리지 않는다
    assert call["kwargs"]["stdout"] is not None     # 로그로 리다이렉트
    assert call["kwargs"]["stderr"] == poll.subprocess.STDOUT
    assert call["kwargs"]["cwd"] == str(rig.vault)
    assert rig.log.exists()

    lock = json.loads(rig.lock_path.read_text(encoding="utf-8"))
    assert lock["pid"] == spawns.pid


def test_only_answered_items_are_processed(rig, spawns):
    rig.brief(first="답 있음", second="")

    assert rig.run() == 0

    assert [row["id"] for row in rig.pending()] == ["2026-09-04#1"]
    assert list(rig.recorded()) == ["2026-09-04#1"]
    assert len(spawns.calls) == 1


def test_two_answers_are_one_thread_reply(rig, spawns):
    rig.brief(first="첫 답", second="둘째 답")
    rig.seed()

    assert rig.run() == 0

    assert len(rig.pending()) == 2
    assert len(rig.notifier.sent) == 1          # 도배하지 않는다
    assert len(rig.notifier.sent[0]["text"].split("\n")) == 2
    assert len(spawns.calls) == 1               # 스킬도 한 번만 띄운다


# ---------------------------------------------------------------------------
# poll.py 배선 — 같은 답으로 두 번 일하지 않는다
# ---------------------------------------------------------------------------

def test_same_answer_is_not_reprocessed(rig, spawns):
    rig.brief(first="추천대로")
    rig.seed()

    assert rig.run() == 0
    assert len(spawns.calls) == 1
    rig.notifier.sent.clear()

    assert rig.run() == 0

    assert len(rig.pending()) == 1              # 이벤트도 늘지 않는다
    assert rig.notifier.sent == []
    assert len(spawns.calls) == 1


def test_edited_answer_is_reprocessed(rig, spawns):
    rig.brief(first="A 로 간다")
    rig.seed()
    assert rig.run() == 0
    first_hash = rig.recorded()["2026-09-04#1"]["answer_hash"]

    rig.brief(first="다시 생각해보니 B 로 간다")
    rig.lock_path.unlink()                      # 앞 실행의 락은 자식이 끝나며 사라진다

    assert rig.run() == 0

    assert rig.recorded()["2026-09-04#1"]["answer_hash"] != first_hash
    assert [row["answer"] for row in rig.pending()] == [
        "A 로 간다",
        "다시 생각해보니 B 로 간다",
    ]
    assert len(spawns.calls) == 2


def test_edited_answer_clears_the_applied_stamp(rig):
    """마음을 바꿨으면 `decision-apply` 가 다시 기록해야 한다."""
    rig.brief(first="A 로 간다")
    rig.seed(
        decisions={
            "2026-09-04#1": {
                "answer_hash": dec.hash_answer("옛 답"),
                "applied": "2026-09-03T10:00:00+09:00",
                "decision_ref": "CWEB-1547#D-01",
            }
        }
    )

    assert rig.run() == 0

    entry = rig.recorded()["2026-09-04#1"]
    assert entry["answer_hash"] == dec.hash_answer("A 로 간다")
    assert "applied" not in entry
    assert "decision_ref" not in entry


def test_applied_marker_alone_does_not_reprocess(rig, spawns):
    """`decision-apply` 가 붙인 `✅ D-03 기록` 이 답을 바꾼 것으로 보이면 헛돈다."""
    rig.brief(first="A 로 간다")
    rig.seed()
    assert rig.run() == 0
    assert len(spawns.calls) == 1

    rig.brief(first="A 로 간다 ✅ D-03 기록")
    rig.lock_path.unlink()
    rig.notifier.sent.clear()

    assert rig.run() == 0

    assert len(rig.pending()) == 1
    assert len(spawns.calls) == 1
    assert rig.notifier.sent == []


def test_state_written_before_answer_key_existed_is_not_revived(rig, spawns):
    """재클론 이전 기록에는 `answer_key` 가 없다. 그 결정이 되살아나면 안 된다."""
    answer = "별도 스레드에서 논의하였음 ✅ D-02 기록 (D-01 대체)"
    rig.brief(first=answer)
    rig.seed(
        decisions={
            "2026-09-04#1": {
                "answer_hash": dec.hash_answer(answer),
                "seen": "2026-09-04T22:29:27+09:00",
                "applied": "2026-09-04T22:29:27+09:00",
            }
        }
    )

    assert rig.run() == 0

    assert rig.pending() == []
    assert rig.notifier.sent == []
    assert spawns.calls == []
    assert rig.recorded()["2026-09-04#1"]["applied"]   # 도장을 지우지 않는다


# ---------------------------------------------------------------------------
# poll.py 배선 — lookback
# ---------------------------------------------------------------------------

def test_yesterdays_answer_is_caught(rig, spawns):
    """금요일 브리핑에 월요일 답이 달린다. 하루만 보면 영원히 놓친다."""
    rig.brief(date=YESTERDAY, first="어제 항목에 오늘 답했다")
    rig.seed()

    assert rig.run() == 0

    assert [row["id"] for row in rig.pending()] == [f"{YESTERDAY}#1"]
    assert len(spawns.calls) == 1


def test_lookback_window_is_configurable(rig, spawns):
    rig.settings(["lookback_days = 1"])
    rig.brief(date=YESTERDAY, first="어제 답")

    assert rig.run() == 0

    assert rig.pending() == []
    assert spawns.calls == []


def test_answers_are_reported_oldest_first(rig):
    rig.brief(date=YESTERDAY, first="어제 답")
    rig.brief(date=TODAY, first="오늘 답")
    rig.seed()

    assert rig.run() == 0

    assert [row["id"] for row in rig.pending()] == [
        f"{YESTERDAY}#1",
        f"{TODAY}#1",
    ]


# ---------------------------------------------------------------------------
# poll.py 배선 — 발송 규칙
# ---------------------------------------------------------------------------

def test_without_a_briefing_root_nothing_is_sent(rig, spawns):
    rig.brief(first="답")
    rig.seed(slack=False)

    assert rig.run() == 0

    assert rig.pending()                    # 기록은 남는다
    assert rig.notifier.sent == []          # 루트가 없으면 스레드도 없다
    assert len(spawns.calls) == 1           # 처리는 그래도 돈다


def test_stale_briefing_root_sends_nothing(rig):
    rig.brief(first="답")
    data = state_mod.empty_state()
    data["slack"] = {"date": YESTERDAY, "ts": BRIEFING_TS}
    state_mod.save(rig.state_path, data)

    assert rig.run() == 0

    assert rig.notifier.sent == []


def test_no_answer_sends_nothing(rig, spawns):
    rig.brief(first="", second="")
    rig.seed()

    assert rig.run() == 0

    assert rig.pending() == []
    assert rig.notifier.sent == []
    assert spawns.calls == []
    assert not rig.lock_path.exists()


# ---------------------------------------------------------------------------
# poll.py 배선 — dry-run
# ---------------------------------------------------------------------------

def test_dry_run_writes_sends_and_spawns_nothing(rig, spawns, capsys):
    rig.brief(first="추천대로")
    rig.seed()
    before = rig.state_path.read_bytes()

    assert rig.run(dry_run=True) == 0

    assert rig.state_path.read_bytes() == before
    assert rig.pending() == []
    assert rig.notifier.sent == []
    assert spawns.calls == []
    assert not rig.lock_path.exists()
    assert not rig.log.exists()
    out = capsys.readouterr().out
    assert "결정 회신: 1건" in out           # 계산은 한다
    assert "[dry-run]" in out


# ---------------------------------------------------------------------------
# poll.py 배선 — 자동 처리 안전장치
# ---------------------------------------------------------------------------

def test_auto_apply_false_records_but_never_spawns(rig, spawns, capsys):
    rig.settings(["auto_apply = false"])
    rig.brief(first="추천대로")
    rig.seed()

    assert rig.run() == 0

    assert rig.pending()
    assert rig.notifier.sent                # 접수 확인은 그대로 간다
    assert spawns.calls == []
    assert not rig.lock_path.exists()
    assert "auto_apply = false" in capsys.readouterr().out


def test_a_fresh_lock_blocks_the_spawn(rig, spawns, capsys):
    rig.brief(first="추천대로")
    rig.seed()
    rig.lock(clock(5))

    assert rig.run() == 0

    assert rig.pending()                    # 기록·발송은 막지 않는다
    assert spawns.calls == []
    assert "이미 실행 중" in capsys.readouterr().out


def test_an_expired_lock_is_treated_as_dead(rig, spawns):
    rig.brief(first="추천대로")
    rig.seed()
    rig.lock(clock(31))

    assert rig.run() == 0

    assert len(spawns.calls) == 1
    assert json.loads(rig.lock_path.read_text(encoding="utf-8"))["pid"] == spawns.pid


def test_lock_expiry_is_configurable(rig, spawns):
    rig.settings(["apply_lock_minutes = 120"])
    rig.brief(first="추천대로")
    rig.seed()
    rig.lock(clock(31))

    assert rig.run() == 0

    assert spawns.calls == []


def test_an_unreadable_lock_does_not_block_forever(rig, spawns):
    rig.brief(first="추천대로")
    rig.seed()
    rig.lock_path.write_text("쓰레기", encoding="utf-8")

    assert rig.run() == 0

    assert len(spawns.calls) == 1


def test_spawn_failure_keeps_exit_zero_and_saves_state(rig, spawns, capsys):
    rig.brief(first="추천대로")
    rig.seed()
    spawns.error = OSError("no fork for you")

    assert rig.run() == 0

    assert rig.recorded()["2026-09-04#1"]["answer_hash"]
    assert rig.pending()
    assert not rig.lock_path.exists()       # 실패하면 락을 놓는다
    assert "spawn 실패" in capsys.readouterr().err


def test_missing_claude_only_warns(rig, spawns, capsys):
    rig.brief(first="추천대로")
    rig.seed()
    rig.no_claude()

    assert rig.run() == 0

    assert spawns.calls == []
    assert not rig.lock_path.exists()       # 띄우지 못했으면 락을 남기지 않는다
    assert rig.pending()
    assert "claude" in capsys.readouterr().err


def test_the_fallback_binary_is_used_when_path_has_none(rig, spawns, monkeypatch):
    monkeypatch.setattr(poll.shutil, "which", lambda name: None)
    monkeypatch.setattr(poll, "CLAUDE_FALLBACK", rig.claude)
    rig.brief(first="추천대로")
    rig.seed()

    assert rig.run() == 0

    assert spawns.calls[0]["argv"][0] == str(rig.claude)


# ---------------------------------------------------------------------------
# poll.py 배선 — 실패해도 폴링은 산다
# ---------------------------------------------------------------------------

def test_a_broken_briefing_does_not_kill_the_poll(rig, monkeypatch, capsys):
    rig.brief(first="추천대로")
    rig.seed()

    def boom(path):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(poll.decisions_mod, "parse", boom)

    assert rig.run() == 0

    assert rig.state()["consecutive_errors"] == 0   # API 실패로 세지 않는다
    assert "결정 회신 감지 실패" in capsys.readouterr().err


def test_answers_are_processed_even_when_jira_is_down(rig, monkeypatch, spawns):
    """Jira 가 죽은 날에도 답은 처리한다 — 결정 회신은 로컬 파일만 읽는다."""

    class Broken:
        def __call__(self, site, email, token):
            return self

        def search(self, jql, fields, max_results=100):
            raise RuntimeError("jira down")

    monkeypatch.setattr(poll, "JiraClient", Broken())
    rig.brief(first="추천대로")
    rig.seed()

    assert rig.run() == 0

    assert [row["id"] for row in rig.pending()] == ["2026-09-04#1"]
    assert rig.notifier.sent
    assert len(spawns.calls) == 1


def test_config_without_a_decisions_table_still_runs(rig, spawns):
    rig.settings(None)
    rig.brief(first="추천대로")
    rig.seed()

    assert rig.run() == 0

    assert len(spawns.calls) == 1


# ---------------------------------------------------------------------------
# config 패스스루
# ---------------------------------------------------------------------------

BASE_CONFIG = (
    'vault = "/tmp/v"\nsite = "s"\nemail = "e"\n'
    "parked_statuses = []\nqa_projects = []\nqa_lookback_days = 7\nrepos = []\n"
)


def test_decisions_table_is_passed_through(tmp_path):
    import config as cfgmod

    path = tmp_path / "c.toml"
    path.write_text(
        BASE_CONFIG + "[decisions]\nlookback_days = 3\nauto_apply = false\n"
        "apply_lock_minutes = 90\n",
        encoding="utf-8",
    )

    assert cfgmod.load_config(path).decisions == {
        "lookback_days": 3,
        "auto_apply": False,
        "apply_lock_minutes": 90,
    }


def test_decisions_defaults_to_empty(tmp_path):
    import config as cfgmod

    path = tmp_path / "c.toml"
    path.write_text(BASE_CONFIG, encoding="utf-8")

    assert cfgmod.load_config(path).decisions == {}


def test_example_config_documents_the_decisions_table():
    import config as cfgmod

    text = cfgmod.DEFAULT_CONFIG.with_name("config.example.toml").read_text("utf-8")

    assert "[decisions]" in text
    for key in ("lookback_days", "auto_apply", "apply_lock_minutes"):
        assert key in text


def test_poll_defaults_when_the_table_is_absent():
    assert poll._lookback_days({}) == poll.DEFAULT_LOOKBACK_DAYS
    assert poll._lock_minutes({}) == poll.DEFAULT_LOCK_MINUTES
    assert poll._enabled(None) is True


@pytest.mark.parametrize("value", [False, "false", "no", "off", "0", ""])
def test_auto_apply_off_switches(value):
    assert poll._enabled(value) is False


@pytest.mark.parametrize("value", [True, "true", "yes", "1"])
def test_auto_apply_on_switches(value):
    assert poll._enabled(value) is True


@pytest.mark.parametrize("bad", ["딸기", None, {}])
def test_garbage_thresholds_fall_back_to_defaults(bad):
    assert poll._lookback_days({"lookback_days": bad}) == poll.DEFAULT_LOOKBACK_DAYS
    assert poll._lock_minutes({"apply_lock_minutes": bad}) == poll.DEFAULT_LOCK_MINUTES
