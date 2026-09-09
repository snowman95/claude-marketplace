"""heartbeat.py 판정 로직과 poll.py 배선 테스트.

실제 Slack·실제 vault 를 건드리지 않는다. vault 는 tmp_path 아래에 만들고
알림은 기록만 하는 가짜로 갈아끼운다.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import heartbeat
import notify as notify_mod
import poll
import state as state_mod

KST = timezone(timedelta(hours=9))

WEDNESDAY = "2026-09-09"
THURSDAY = "2026-09-10"
SATURDAY = "2026-09-12"
SUNDAY = "2026-09-13"
WEEK = "2026-W37"


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}:00+09:00")


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "projects"
    (root / "daily").mkdir(parents=True)
    (root / "weekly").mkdir(parents=True)
    return root


# 정상 브리핑의 최소 형태: 필수 섹션 두 개 + min_lines(20) 이상.
BRIEF_BODY = "\n".join(
    ["# {day}", "", "## 네가 할 일", ""]
    + [f"- 할 일 {i}" for i in range(1, 11)]
    + ["", "## 진행 중", ""]
    + [f"- CWEB-{1500 + i} 진행 중" for i in range(1, 11)]
    + ["", "## 변경 로그", ""]
)


def brief(vault, day, body=None, sent=True):
    """오늘자 브리핑. 기본은 '정상 + Slack 발행됨'."""
    path = vault / "daily" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BRIEF_BODY.format(day=day) if body is None else body, encoding="utf-8")
    if sent:
        publish(vault, day)
    return path


def publish(vault, day):
    """`_state.json` 에 발행 기록만 얹는다 — 기존 상태(래치)는 건드리지 않는다."""
    path = vault / "daily" / "_state.json"
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data["slack"] = {"date": day, "ts": "1756950000.000100"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def weekly(vault, week=WEEK):
    path = vault / "weekly" / f"{week}.md"
    path.write_text(f"# {week}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# check() — 브리핑
# ---------------------------------------------------------------------------

def test_before_deadline_is_not_a_miss(vault):
    assert heartbeat.check(vault, at(WEDNESDAY, "09:29"), {}) == []


def test_after_deadline_without_brief_is_a_miss(vault):
    weekly(vault)

    misses = heartbeat.check(vault, at(WEDNESDAY, "09:31"), {})

    assert len(misses) == 1
    assert misses[0].kind == "brief_missing"
    assert misses[0].date == WEDNESDAY
    assert "09:30" in misses[0].text
    assert f"daily/{WEDNESDAY}.md" in misses[0].text


def test_after_deadline_with_brief_is_not_a_miss(vault):
    brief(vault, WEDNESDAY)
    weekly(vault)

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}) == []


def test_weekend_never_reports_a_brief_miss(vault):
    weekly(vault)

    for day in (SATURDAY, SUNDAY):
        kinds = [m.kind for m in heartbeat.check(vault, at(day, "23:00"), {})]
        assert not set(kinds) & set(heartbeat.BRIEF_KINDS)


def test_only_today_is_judged(vault):
    """어제 브리핑이 없어도 오늘 것이 있으면 조용하다."""
    brief(vault, THURSDAY)
    weekly(vault)

    assert heartbeat.check(vault, at(THURSDAY, "18:00"), {}) == []


def test_deadline_comes_from_config(vault):
    weekly(vault)
    cfg = {"brief_deadline": "11:00"}

    assert heartbeat.check(vault, at(WEDNESDAY, "10:00"), cfg) == []

    misses = heartbeat.check(vault, at(WEDNESDAY, "11:30"), cfg)
    assert [m.kind for m in misses] == ["brief_missing"]
    assert "11:00" in misses[0].text


def test_garbage_deadline_falls_back_to_default(vault):
    weekly(vault)
    cfg = {"brief_deadline": "9시"}

    assert heartbeat.check(vault, at(WEDNESDAY, "09:29"), cfg) == []

    misses = heartbeat.check(vault, at(WEDNESDAY, "09:31"), cfg)
    assert [m.kind for m in misses] == ["brief_missing"]
    assert "09:30" in misses[0].text


@pytest.mark.parametrize("value", [None, "", "25:00", "09:70", 930, [], "09-30"])
def test_no_deadline_input_crashes(vault, value):
    weekly(vault)

    misses = heartbeat.check(vault, at(WEDNESDAY, "09:31"), {"brief_deadline": value})

    assert [m.kind for m in misses] == ["brief_missing"]


def test_config_object_with_heartbeat_table_is_accepted(vault):
    weekly(vault)

    class Cfg:
        heartbeat = {"brief_deadline": "11:00"}

    assert heartbeat.check(vault, at(WEDNESDAY, "10:00"), Cfg()) == []


# ---------------------------------------------------------------------------
# check() — 브리핑 3단계 (없음 / 부실 / 미발송)
# ---------------------------------------------------------------------------

def only(misses):
    assert len(misses) == 1, [m.kind for m in misses]
    return misses[0]


def test_zero_byte_brief_is_partial(vault):
    weekly(vault)
    brief(vault, WEDNESDAY, body="")

    miss = only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}))

    assert miss.kind == "brief_partial"
    assert miss.date == WEDNESDAY


def test_brief_without_required_sections_is_partial(vault):
    """줄 수는 충분한데 섹션이 없다 — 다른 문서가 그 이름으로 놓인 경우."""
    weekly(vault)
    brief(vault, WEDNESDAY, body="\n".join(f"- 줄 {i}" for i in range(60)))

    miss = only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}))

    assert miss.kind == "brief_partial"
    assert "필수 섹션" in miss.text


def test_brief_shorter_than_min_lines_is_partial(vault):
    """섹션 제목까지만 쓰고 죽은 경우."""
    weekly(vault)
    brief(vault, WEDNESDAY, body=f"# {WEDNESDAY}\n\n## 네가 할 일\n\n- 하나\n")

    miss = only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}))

    assert miss.kind == "brief_partial"
    assert "3줄" in miss.text  # 빈 줄은 세지 않는다
    assert "20줄" in miss.text


def test_either_required_section_is_enough(vault):
    weekly(vault)
    body = "\n".join(["## 진행 중"] + [f"- CWEB-{i}" for i in range(40)])
    brief(vault, WEDNESDAY, body=body)

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}) == []


def test_min_lines_comes_from_config(vault):
    weekly(vault)
    brief(vault, WEDNESDAY, body=f"## 진행 중\n\n- CWEB-1547\n")

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {"min_lines": 2}) == []

    miss = only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {"min_lines": 3}))
    assert miss.kind == "brief_partial"
    assert "3줄" in miss.text


def test_generous_min_lines_flags_an_otherwise_healthy_brief(vault):
    weekly(vault)
    brief(vault, WEDNESDAY)

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}) == []
    assert only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {"min_lines": 500})).kind == (
        "brief_partial"
    )


@pytest.mark.parametrize("value", [None, "", "많이", True, -1, []])
def test_garbage_min_lines_falls_back_to_default(vault, value):
    weekly(vault)
    brief(vault, WEDNESDAY)

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {"min_lines": value}) == []


def test_healthy_brief_without_a_publish_record_is_unsent(vault):
    """파일은 썼지만 Slack 발행에 실패한 경우 — 사용자에겐 여전히 '안 왔다'."""
    weekly(vault)
    brief(vault, WEDNESDAY, sent=False)

    miss = only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}))

    assert miss.kind == "brief_unsent"
    assert "Slack" in miss.text
    assert f"daily/{WEDNESDAY}.md" in miss.text


def test_stale_publish_record_is_unsent(vault):
    weekly(vault)
    brief(vault, WEDNESDAY, sent=False)
    publish(vault, THURSDAY)  # 어제(다른 날) 기록만 남아 있다

    assert only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {})).kind == "brief_unsent"


def test_healthy_and_published_brief_is_not_a_miss(vault):
    weekly(vault)
    brief(vault, WEDNESDAY)

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}) == []


def test_injected_state_is_used_instead_of_the_file(vault):
    weekly(vault)
    brief(vault, WEDNESDAY, sent=False)

    state = {"slack": {"date": WEDNESDAY, "ts": "1.1"}}
    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}, state=state) == []


@pytest.mark.parametrize("state", [{"slack": "쓰레기"}, {"slack": {"ts": "1.1"}}, {}])
def test_unusable_publish_record_reads_as_unsent(vault, state):
    weekly(vault)
    brief(vault, WEDNESDAY, sent=False)

    assert only(heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}, state=state)).kind == (
        "brief_unsent"
    )


def test_corrupt_state_file_does_not_cry_unsent(vault):
    """판단이 안 서면 조용히 있는다 — 오탐이 알림을 무의미하게 만든다."""
    weekly(vault)
    brief(vault, WEDNESDAY, sent=False)
    (vault / "daily" / "_state.json").write_text("{망가짐", encoding="utf-8")

    assert heartbeat.check(vault, at(WEDNESDAY, "09:31"), {}) == []


def test_each_brief_kind_has_its_own_wording(vault):
    weekly(vault)
    now = at(WEDNESDAY, "09:31")

    missing = only(heartbeat.check(vault, now, {}))
    brief(vault, WEDNESDAY, body="", sent=False)
    partial = only(heartbeat.check(vault, now, {}))
    brief(vault, WEDNESDAY, sent=False)
    unsent = only(heartbeat.check(vault, now, {}))

    heads = [heartbeat.render(m).splitlines()[0] for m in (missing, partial, unsent)]
    assert len(set(heads)) == 3
    assert all(head.startswith("🔴") for head in heads)
    assert len({m.text for m in (missing, partial, unsent)}) == 3


# ---------------------------------------------------------------------------
# check() — 주간
# ---------------------------------------------------------------------------

def test_saturday_without_weekly_is_a_miss(vault):
    misses = [m for m in heartbeat.check(vault, at(SATURDAY, "10:00"), {}) if m.kind == "weekly"]

    assert len(misses) == 1
    assert misses[0].date == SATURDAY
    assert f"weekly/{WEEK}.md" in misses[0].text


def test_saturday_with_weekly_is_not_a_miss(vault):
    weekly(vault)

    assert heartbeat.check(vault, at(SATURDAY, "10:00"), {}) == []


def test_midweek_does_not_check_weekly(vault):
    brief(vault, WEDNESDAY)

    assert heartbeat.check(vault, at(WEDNESDAY, "18:00"), {}) == []


def test_weekly_day_comes_from_config(vault):
    brief(vault, WEDNESDAY)
    cfg = {"weekly_day": "wed"}

    misses = heartbeat.check(vault, at(WEDNESDAY, "18:00"), cfg)

    assert [m.kind for m in misses] == ["weekly"]


def test_garbage_weekly_day_falls_back_to_saturday(vault):
    brief(vault, WEDNESDAY)

    assert heartbeat.check(vault, at(WEDNESDAY, "18:00"), {"weekly_day": "언젠가"}) == []
    assert [m.kind for m in heartbeat.check(vault, at(SATURDAY, "10:00"), {"weekly_day": "언젠가"})] == [
        "weekly"
    ]


def test_missing_vault_dirs_report_misses_without_crashing(tmp_path):
    misses = heartbeat.check(tmp_path / "nope", at(SATURDAY, "10:00"), {})

    assert [m.kind for m in misses] == ["weekly"]


# ---------------------------------------------------------------------------
# render()
# ---------------------------------------------------------------------------

def test_render_matches_the_agreed_shape(vault):
    weekly(vault)
    miss = heartbeat.check(vault, at(WEDNESDAY, "09:31"), {})[0]

    text = heartbeat.render(miss, "마지막 폴링은 정상 (활성 5 · parked 36).")

    assert text.splitlines() == [
        "🔴 브리핑 미발행 — 2026-09-09 (수)",
        "09:30 이 지났는데 daily/2026-09-09.md 가 없다.",
        "마지막 폴링은 정상 (활성 5 · parked 36).",
        "→ 로그 확인: ~/.local/log/daily-report/brief.log",
    ]


# ---------------------------------------------------------------------------
# latch()
# ---------------------------------------------------------------------------

def test_latch_sends_once_then_stays_quiet(vault):
    weekly(vault)
    now = at(WEDNESDAY, "09:31")
    misses = heartbeat.check(vault, now, {})
    data = {}

    assert heartbeat.latch(data, misses, now) == misses
    assert list(data["heartbeat"]["brief_missing"]) == [WEDNESDAY]
    assert heartbeat.latch(data, misses, at(WEDNESDAY, "10:31")) == []


def test_latch_clears_when_the_brief_shows_up(vault):
    weekly(vault)
    now = at(WEDNESDAY, "09:31")
    data = {}
    heartbeat.latch(data, heartbeat.check(vault, now, {}), now)
    assert data["heartbeat"]["brief_missing"]

    brief(vault, WEDNESDAY)
    later = at(WEDNESDAY, "10:31")

    assert heartbeat.latch(data, heartbeat.check(vault, later, {}), later) == []
    assert data["heartbeat"] == {}


def test_latch_reopens_on_the_next_day(vault):
    weekly(vault)
    data = {}
    first = at(WEDNESDAY, "09:31")
    heartbeat.latch(data, heartbeat.check(vault, first, {}), first)

    second = at(THURSDAY, "09:31")
    pending = heartbeat.latch(data, heartbeat.check(vault, second, {}), second)

    assert [m.date for m in pending] == [THURSDAY]
    assert list(data["heartbeat"]["brief_missing"]) == [THURSDAY]


def test_latch_treats_a_kind_change_as_a_new_alert(vault):
    """missing 을 알린 뒤 파일이 생겨 unsent 가 되면 그건 새 사고다."""
    weekly(vault)
    data = {}
    first = at(WEDNESDAY, "09:31")
    pending = heartbeat.latch(data, heartbeat.check(vault, first, {}), first)
    assert [m.kind for m in pending] == ["brief_missing"]

    brief(vault, WEDNESDAY, sent=False)
    later = at(WEDNESDAY, "10:31")
    pending = heartbeat.latch(data, heartbeat.check(vault, later, {}), later)

    assert [m.kind for m in pending] == ["brief_unsent"]
    assert list(data["heartbeat"]) == ["brief_unsent"]  # 해소된 kind 는 남지 않는다


def test_latch_survives_a_corrupt_state_value(vault):
    weekly(vault)
    now = at(WEDNESDAY, "09:31")
    data = {"heartbeat": "쓰레기"}

    assert heartbeat.latch(data, heartbeat.check(vault, now, {}), now)
    assert isinstance(data["heartbeat"], dict)


# ---------------------------------------------------------------------------
# poll.py 배선
# ---------------------------------------------------------------------------

class FakeJira:
    def __init__(self):
        self.fail = None

    def __call__(self, site, email, token):
        return self

    def search(self, jql, fields, max_results=100):
        if self.fail is not None:
            raise self.fail
        return []


class RecordingNotifier:
    def __init__(self, boom=False):
        self.sent = []
        self.boom = boom

    def send(self, text, thread_ts=None):
        self.sent.append((text, thread_ts))
        if self.boom:
            raise RuntimeError("slack down")
        return "1.1"

    def update(self, ts, text):
        return False


class Rig:
    def __init__(
        self,
        tmp_path,
        monkeypatch,
        heartbeat_table='[heartbeat]\nbrief_deadline = "09:30"\n',
        notify_table="",
    ):
        self.vault = tmp_path / "projects"
        self.daily = self.vault / "daily"
        self.daily.mkdir(parents=True)
        (self.vault / "weekly").mkdir(parents=True)
        (self.vault / "weekly" / f"{WEEK}.md").write_text("# w\n", encoding="utf-8")
        self.config = tmp_path / "config.toml"
        self.config.write_text(
            "\n".join(
                [
                    f'vault = "{self.vault}"',
                    'site = "example.atlassian.net"',
                    'email = "me@example.com"',
                    "parked_statuses = []",
                    "qa_projects = []",
                    "qa_lookback_days = 7",
                    "repos = []",
                    notify_table,
                    heartbeat_table,
                ]
            ),
            encoding="utf-8",
        )
        self.jira = FakeJira()
        self.notifier = RecordingNotifier()
        monkeypatch.setattr(poll, "JiraClient", self.jira)
        monkeypatch.setattr(poll, "load_token", lambda email: "atl-token")
        monkeypatch.setattr(poll, "load_figma_token", lambda: None)
        monkeypatch.setattr(poll, "_build_notifier", lambda cfg: self.notifier)
        monkeypatch.setattr(poll.subprocess, "run", lambda *a, **k: None)
        self._monkeypatch = monkeypatch

    def run(self, day=WEDNESDAY, hhmm="09:31", dry_run=False):
        self._monkeypatch.setattr(poll, "_now", lambda date_str: at(day, hhmm))
        argv = ["--config", str(self.config)]
        if dry_run:
            argv.append("--dry-run")
        return poll.main(argv)

    @property
    def state_path(self):
        return self.daily / "_state.json"

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


def test_poll_sends_a_new_message_when_the_brief_is_missing(rig, capsys):
    assert rig.run() == 0

    assert len(rig.notifier.sent) == 1
    text, thread_ts = rig.notifier.sent[0]
    assert thread_ts is None  # 스레드 루트가 없다 — 새 메시지로 보낸다
    assert text.startswith("🔴 브리핑 미발행 — 2026-09-09 (수)")
    assert f"daily/{WEDNESDAY}.md" in text
    assert "brief.log" in text
    assert "자기감시: 브리핑 미발행" in capsys.readouterr().out


def test_poll_stays_quiet_when_the_brief_exists(rig, capsys):
    brief(rig.vault, WEDNESDAY)

    assert rig.run() == 0

    assert rig.notifier.sent == []
    assert "자기감시: 정상" in capsys.readouterr().out


def test_poll_sends_only_once_a_day(rig):
    rig.run()
    rig.run(hhmm="10:31")

    assert len(rig.notifier.sent) == 1
    assert list(rig.state()["heartbeat"]["brief_missing"]) == [WEDNESDAY]


def test_poll_clears_the_latch_when_the_brief_lands_late(rig):
    rig.run()
    brief(rig.vault, WEDNESDAY)

    rig.run(hhmm="10:31")

    assert len(rig.notifier.sent) == 1
    assert rig.state()["heartbeat"] == {}


def test_poll_sends_again_the_next_day(rig):
    rig.run()

    rig.run(day=THURSDAY)

    assert len(rig.notifier.sent) == 2
    assert rig.notifier.sent[1][0].startswith("🔴 브리핑 미발행 — 2026-09-10 (목)")
    assert list(rig.state()["heartbeat"]["brief_missing"]) == [THURSDAY]


def test_dry_run_neither_sends_nor_latches(rig, capsys):
    assert rig.run(dry_run=True) == 0

    assert rig.notifier.sent == []
    assert not rig.state_path.exists()
    out = capsys.readouterr().out
    assert "[dry-run] 알림(new message)" in out
    assert "🔴 브리핑 미발행" in out


def test_notifier_blowing_up_does_not_kill_the_poll(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.notifier.boom = True

    assert rig.run() == 0
    assert rig.state()["heartbeat"]["brief_missing"]  # 발송 실패해도 래치는 선다


def test_heartbeat_runs_even_when_jira_is_down(rig, capsys):
    rig.jira.fail = RuntimeError("jira down")

    assert rig.run() == 0

    assert len(rig.notifier.sent) == 1
    assert "마지막 폴링" in rig.notifier.sent[0][0]
    assert "자기감시: 브리핑 미발행" in capsys.readouterr().out


def test_broken_config_deadline_does_not_break_the_poll(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, heartbeat_table='[heartbeat]\nbrief_deadline = "9시"\n')

    assert rig.run(hhmm="09:29") == 0
    assert rig.notifier.sent == []

    assert rig.run(hhmm="09:31") == 0
    assert len(rig.notifier.sent) == 1


def test_config_without_heartbeat_table_still_watches(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, heartbeat_table="")

    assert rig.run() == 0

    assert len(rig.notifier.sent) == 1


def test_poll_reports_the_new_brief_kinds(rig, capsys):
    brief(rig.vault, WEDNESDAY, body="", sent=False)

    assert rig.run() == 0

    assert rig.notifier.sent[0][0].startswith("🔴 브리핑 부실")
    assert "자기감시: 브리핑 부실" in capsys.readouterr().out
    assert list(rig.state()["heartbeat"]) == ["brief_partial"]


def test_poll_treats_a_kind_change_as_a_new_alert(rig):
    """미발행으로 한 번 울린 뒤 파일이 생겨 미발송이 되면 다시 울린다."""
    rig.run()
    brief(rig.vault, WEDNESDAY, sent=False)

    rig.run(hhmm="10:31")

    kinds = [text.splitlines()[0] for text, _ in rig.notifier.sent]
    assert len(kinds) == 2
    assert kinds[0].startswith("🔴 브리핑 미발행")
    assert kinds[1].startswith("🔴 브리핑 미발송")
    assert list(rig.state()["heartbeat"]) == ["brief_unsent"]


def test_poll_min_lines_comes_from_config(tmp_path, monkeypatch):
    rig = Rig(
        tmp_path,
        monkeypatch,
        heartbeat_table='[heartbeat]\nbrief_deadline = "09:30"\nmin_lines = 500\n',
    )
    brief(rig.vault, WEDNESDAY)

    assert rig.run() == 0

    assert rig.notifier.sent[0][0].startswith("🔴 브리핑 부실")
    assert "500줄" in rig.notifier.sent[0][0]


# ---------------------------------------------------------------------------
# 주말
# ---------------------------------------------------------------------------

def test_weekend_poll_runs_to_the_end(rig, capsys):
    (rig.vault / "weekly" / f"{WEEK}.md").unlink()

    assert rig.run(day=SATURDAY, hhmm="10:00") == 0

    out = capsys.readouterr().out
    assert "주말 — 이벤트 알림 억제" in out
    assert rig.state()["polled_at"]  # state 갱신은 주말에도 한다
    assert "자기감시: 주간 리포트 미발행" in out
    # 🔴 등급은 주말에도 나간다 — 시스템이 죽은 건 주말에도 알아야 한다
    assert len(rig.notifier.sent) == 1
    assert rig.notifier.sent[0][0].startswith("🔴 주간 리포트 미발행")


def test_weekend_does_not_expect_a_brief(rig):
    assert rig.run(day=SUNDAY, hhmm="10:00") == 0

    assert rig.notifier.sent == []


def test_weekend_suppresses_event_thread_replies(rig):
    events = [state_mod.Event("CWEB-1547", "status", "**status** 진행 중 → 리뷰중", False)]

    poll._notify_events(
        rig.notifier, {"slack": {"date": SATURDAY, "ts": "1.1"}}, events,
        at(SATURDAY, "10:00"), False,
    )
    assert rig.notifier.sent == []

    poll._notify_events(
        rig.notifier, {"slack": {"date": WEDNESDAY, "ts": "1.1"}}, events,
        at(WEDNESDAY, "10:00"), False,
    )
    assert len(rig.notifier.sent) == 1  # 평일엔 그대로 답글이 간다


def test_consecutive_failure_alert_still_fires_on_the_weekend(rig):
    rig.jira.fail = RuntimeError("jira down")

    for _ in range(3):
        assert rig.run(day=SATURDAY, hhmm="10:00") == 0

    assert any(
        text.startswith("🔴 daily-report 폴링 3회 연속 실패")
        for text, _ in rig.notifier.sent
    )


# ---------------------------------------------------------------------------
# 2차 채널 (구멍 2)
# ---------------------------------------------------------------------------

def banner_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(poll.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    return calls


def test_heartbeat_alert_also_goes_to_the_fallback_channel(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, notify_table='[notify]\nchannel = "slack"\n')
    banners = banner_recorder(monkeypatch)

    assert rig.run() == 0

    assert len(rig.notifier.sent) == 1  # 1차 = Slack
    assert len(banners) == 1  # 2차 = macOS 배너
    assert any("브리핑 미발행" in str(part) for part in banners[0])


def test_fallback_still_fires_when_the_primary_is_dead(tmp_path, monkeypatch):
    """Slack 봇 토큰이 만료돼도 경고가 조용히 사라지지 않는다."""
    rig = Rig(tmp_path, monkeypatch, notify_table='[notify]\nchannel = "slack"\n')
    rig.notifier.boom = True
    banners = banner_recorder(monkeypatch)

    assert rig.run() == 0

    assert len(banners) == 1


def test_empty_fallback_list_means_one_channel(tmp_path, monkeypatch):
    rig = Rig(
        tmp_path,
        monkeypatch,
        heartbeat_table='[heartbeat]\nbrief_deadline = "09:30"\nfallback = []\n',
        notify_table='[notify]\nchannel = "slack"\n',
    )
    banners = banner_recorder(monkeypatch)

    assert rig.run() == 0

    assert len(rig.notifier.sent) == 1
    assert banners == []


class AlarmCfg:
    def __init__(self, notify=None, heartbeat=None):
        self.notify = notify or {}
        self.heartbeat = heartbeat if heartbeat is not None else {}


def test_alarm_defaults_to_a_second_channel():
    alarm = poll._build_alarm(AlarmCfg({"channel": "slack"}), RecordingNotifier())

    assert isinstance(alarm, notify_mod.MultiNotifier)
    assert [type(n).__name__ for n in alarm.notifiers] == [
        "RecordingNotifier",
        "OsascriptNotifier",
    ]


def test_alarm_skips_a_fallback_that_matches_the_primary():
    """1차가 이미 osascript 면 배너를 두 번 띄우지 않는다."""
    primary = RecordingNotifier()

    assert poll._build_alarm(AlarmCfg({}, {"fallback": ["osascript"]}), primary) is primary


def test_alarm_ignores_unknown_fallback_channels():
    primary = RecordingNotifier()
    cfg = AlarmCfg({"channel": "slack"}, {"fallback": ["telegram", "  "]})

    assert poll._build_alarm(cfg, primary) is primary


def test_alarm_survives_a_garbage_fallback_value():
    primary = RecordingNotifier()
    cfg = AlarmCfg({"channel": "slack"}, {"fallback": "osascript"})

    alarm = poll._build_alarm(cfg, primary)

    assert isinstance(alarm, notify_mod.MultiNotifier)
