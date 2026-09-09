"""poll.py 의 감시 계층 통합 — `--force`, parked 입력, watch 상태.

`tests/test_poll.py` 의 Rig 를 쓰지 않고 최소한의 장비를 따로 세운다. 감시가
필요한 입력(릴리즈 표·parked fixVersion·오래된 updated)이 폴링 본체 테스트와
겹치지 않고, 같은 파일을 양쪽에서 고치지 않으려는 것이다.

실제 API·실제 vault 는 건드리지 않는다.
"""

import json

import pytest

import poll

FRIDAY = "2026-09-04"
SATURDAY = "2026-09-05"

RELEASES = """\
| 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
|---|---|---|---|---|
| shop | 3.2.0 | 2026-08-10 | 2026-09-03 | QA중 |
| shop | 3.3.0 | 2026-09-14 | 2026-10-07 | 개발중 |
"""

MD_BODY = """
# {key}

## 문의·Blocked

- 없음
"""

STALE = "2026-08-10T18:22:00.000+0900"   # FRIDAY 기준 25일 전
FRESH = "2026-09-03T18:22:00.000+0900"


def issue(key, status="진행 중", category="진행 중", updated=FRESH, fix_versions=()):
    fields = {
        "summary": f"{key} 요약",
        "status": {"name": status, "statusCategory": {"name": category}},
        "updated": updated,
    }
    if fix_versions:
        fields["fixVersions"] = [{"name": name} for name in fix_versions]
    return {"key": key, "fields": fields}


class FakeJira:
    def __init__(self):
        self.constructed = 0
        self.active = []
        self.parked = []

    def __call__(self, site, email, token):
        self.constructed += 1
        return self

    def search(self, jql, fields, max_results=100):
        if "project IN" in jql:
            return []
        if "statusCategory" in jql:
            return list(self.active)
        return list(self.parked)


class FakeConfluence:
    def __call__(self, site, email, token):
        return self

    def page_versions(self, ids):
        return {}


class Rig:
    def __init__(self, tmp_path, monkeypatch):
        self.vault = tmp_path / "projects"
        self.daily = self.vault / "daily"
        self.daily.mkdir(parents=True)
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.jira = FakeJira()
        self.notifications = []
        self.config_lines = [
            f'vault = "{self.vault}"',
            'site = "example.atlassian.net"',
            'email = "me@example.com"',
            'parked_statuses = ["Ready to Deploy"]',
            "qa_projects = []",
            "qa_lookback_days = 7",
            "repos = []",
        ]

        monkeypatch.setattr(poll, "JiraClient", self.jira)
        monkeypatch.setattr(poll, "ConfluenceClient", FakeConfluence())
        monkeypatch.setattr(poll, "load_token", lambda email: "atl-token")
        monkeypatch.setattr(poll, "load_figma_token", lambda: None)
        monkeypatch.setattr(
            poll.subprocess, "run", lambda *a, **k: self.notifications.append(a[0])
        )

    # --- 입력 -------------------------------------------------------------
    def releases(self, body=RELEASES):
        (self.daily / "releases.md").write_text(body, encoding="utf-8")

    def md(self, key, frontmatter=()):
        path = self.vault / "myproject" / "tasks" / "shop3.3.0" / f"{key}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = [f"jira_key: {key}", *frontmatter]
        path.write_text(
            "---\n" + "\n".join(head) + "\n---\n" + MD_BODY.format(key=key),
            encoding="utf-8",
        )
        return path

    def parked_release(self, count, version="shop3.2.0", first=9000):
        self.jira.parked = [
            issue(
                f"WPQ-{first + i}",
                status="Ready to Deploy",
                fix_versions=(version,),
            )
            for i in range(count)
        ]

    # --- 실행 -------------------------------------------------------------
    @property
    def config(self):
        path = self.tmp / "config.toml"
        path.write_text("\n".join(self.config_lines) + "\n", encoding="utf-8")
        return path

    def run(self, date=FRIDAY, dry_run=False, force=False):
        argv = ["--config", str(self.config), "--date", date]
        if dry_run:
            argv.append("--dry-run")
        if force:
            argv.append("--force")
        return poll.main(argv)

    # --- 산출물 -----------------------------------------------------------
    @property
    def state_path(self):
        return self.daily / "_state.json"

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# --force
# ---------------------------------------------------------------------------

def test_force_runs_on_a_weekend(rig):
    """주간 회고가 토요일에 `--force` 로 돌린다. 끝까지 돌아야 한다.

    주말 가드 자체는 이후 다른 작업에서 제거됐다. 여기서 지키는 계약은
    "`--force` 로 부르면 주말에도 폴링이 완주한다" 하나다.
    """
    rig.jira.active = [issue("CWEB-1547")]

    assert rig.run(date=SATURDAY, force=True) == 0

    assert rig.jira.constructed == 1
    assert rig.state_path.exists()
    assert set(rig.state()["tickets"]) == {"CWEB-1547"}


def test_force_is_accepted_without_error(rig):
    rig.jira.active = [issue("CWEB-1547")]
    assert rig.run(date=SATURDAY, force=True) == 0
    assert rig.run(date=FRIDAY, force=True) == 0


def test_force_on_a_weekday_changes_nothing(rig):
    rig.jira.active = [issue("CWEB-1547")]
    assert rig.run(force=True) == 0
    assert rig.jira.constructed == 1


# ---------------------------------------------------------------------------
# parked 입력
# ---------------------------------------------------------------------------

def test_parked_tickets_stay_out_of_state(rig):
    """수백 건이라 state 를 부풀린다. 감시 입력으로만 쓴다."""
    rig.releases()
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(27)

    rig.run()

    assert set(rig.state()["tickets"]) == {"CWEB-1547"}


def test_parked_release_becomes_one_aggregated_alert(rig, capsys):
    """이전 구현이 티켓별로 만들어 릴리즈 하나를 27줄로 도배했다."""
    rig.releases()
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(27)

    rig.run()
    out = capsys.readouterr().out

    w1 = [line for line in out.splitlines() if "W1" in line]
    assert len(w1) == 1
    assert "[shop 3.2.0]" in w1[0]
    assert "27건" in w1[0]
    assert "WPQ-9000 외 26건" in w1[0]
    assert "1일 경과" in w1[0]


def test_watch_state_records_the_release_subject(rig):
    rig.releases()
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(3)

    rig.run()

    assert rig.state()["watch"]["shop3.2.0"] == {"W1": "2026-09-04"}


def test_no_releases_file_means_no_release_alerts(rig, capsys):
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(27)

    assert rig.run() == 0

    out = capsys.readouterr().out
    assert "W1" not in out
    assert rig.state()["watch"] == {}
    assert rig.state()["consecutive_errors"] == 0


def test_release_absent_from_the_table_is_silent(rig, capsys):
    rig.releases()
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(5, version="shop9.9.9")

    rig.run()

    assert "W1" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fix_version · blocked_since
# ---------------------------------------------------------------------------

def test_fix_version_comes_from_jira(rig):
    rig.jira.active = [issue("CWEB-1547", fix_versions=("shop3.3.0",))]
    rig.run()
    assert rig.state()["tickets"]["CWEB-1547"]["fix_version"] == "shop3.3.0"


def test_fix_version_falls_back_to_the_md(rig):
    """Jira fixVersions 가 비어 있는 티켓이 흔하다. md 선언이 durable 이다."""
    rig.md("CWEB-1547", frontmatter=['fix_version: "shop3.3.0"'])
    rig.jira.active = [issue("CWEB-1547")]

    rig.run()

    assert rig.state()["tickets"]["CWEB-1547"]["fix_version"] == "shop3.3.0"


def test_fix_version_prefers_a_parseable_jira_value(rig):
    rig.jira.active = [issue("CWEB-1547", fix_versions=("26.10 (v.3.20.0)", "shop3.3.0"))]
    rig.run()
    assert rig.state()["tickets"]["CWEB-1547"]["fix_version"] == "shop3.3.0"


def test_fix_version_is_empty_when_nothing_declares_it(rig):
    rig.jira.active = [issue("CWEB-1547")]
    rig.run()
    assert rig.state()["tickets"]["CWEB-1547"]["fix_version"] == ""


def test_blocked_since_is_recorded_when_blocked_turns_on(rig):
    rig.md("CWEB-1547", frontmatter=["blocked: true"])
    rig.jira.active = [issue("CWEB-1547")]

    rig.run()

    assert rig.state()["tickets"]["CWEB-1547"]["blocked_since"] == "2026-09-04"


def test_blocked_since_keeps_the_original_day(rig):
    rig.md("CWEB-1547", frontmatter=["blocked: true"])
    rig.jira.active = [issue("CWEB-1547")]
    rig.run(date="2026-09-01")

    rig.run(date=FRIDAY)

    assert rig.state()["tickets"]["CWEB-1547"]["blocked_since"] == "2026-09-01"


def test_blocked_since_is_dropped_when_blocked_turns_off(rig):
    rig.md("CWEB-1547", frontmatter=["blocked: true"])
    rig.jira.active = [issue("CWEB-1547")]
    rig.run()
    assert "blocked_since" in rig.state()["tickets"]["CWEB-1547"]

    rig.md("CWEB-1547", frontmatter=["blocked: false"])
    rig.run()

    assert "blocked_since" not in rig.state()["tickets"]["CWEB-1547"]


def test_unblocked_ticket_never_gets_the_key(rig):
    rig.md("CWEB-1547", frontmatter=["blocked: false"])
    rig.jira.active = [issue("CWEB-1547")]
    rig.run()
    assert "blocked_since" not in rig.state()["tickets"]["CWEB-1547"]


# ---------------------------------------------------------------------------
# 반복 억제 · 출력
# ---------------------------------------------------------------------------

def test_yellow_alert_folds_on_the_second_run(rig, capsys):
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]

    rig.run()
    first = capsys.readouterr().out
    assert "W7 [CWEB-1547]" in first
    assert "신규 1" in first

    rig.run()
    second = capsys.readouterr().out
    assert "W7 [CWEB-1547]" not in second
    assert "W7 계속 1건" in second
    assert "이어짐 1" in second


def test_red_alert_never_folds(rig, capsys):
    rig.releases()
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(3)

    rig.run()
    capsys.readouterr()
    rig.run()

    assert "W1 [shop 3.2.0]" in capsys.readouterr().out


def test_resolved_alert_leaves_the_seen_map(rig):
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]
    rig.run()
    assert "CWEB-1547" in rig.state()["watch"]

    rig.jira.active = [issue("CWEB-1547", updated=FRESH)]
    rig.run()

    assert rig.state()["watch"] == {}


def test_watch_ignore_silences_the_ticket(rig, capsys):
    rig.md("CWEB-1547", frontmatter=["watch_ignore: BE 일정 대기"])
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]

    rig.run()

    assert "W7" not in capsys.readouterr().out
    assert rig.state()["watch"] == {}


def test_quiet_run_prints_no_watch_block(rig, capsys):
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547")]

    rig.run()

    assert "감시 경보:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 설정 · dry-run
# ---------------------------------------------------------------------------

def test_watch_table_raises_the_threshold(rig, capsys):
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]
    rig.config_lines += ["[watch]", "ticket_stale_days = 30"]

    rig.run()

    assert "W7" not in capsys.readouterr().out


def test_watch_table_lowers_the_threshold(rig, capsys):
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]
    rig.config_lines += ["[watch]", "ticket_stale_days = 5"]

    rig.run()

    assert "W7 [CWEB-1547]" in capsys.readouterr().out


def test_dry_run_computes_without_writing(rig, capsys):
    rig.releases()
    rig.md("CWEB-1547")
    rig.jira.active = [issue("CWEB-1547", updated=STALE)]
    rig.parked_release(4)

    assert rig.run(dry_run=True) == 0

    out = capsys.readouterr().out
    assert "W1 [shop 3.2.0]" in out
    assert "W7 [CWEB-1547]" in out
    assert not rig.state_path.exists()


def test_dry_run_does_not_touch_the_releases_file(rig):
    rig.releases()
    path = rig.daily / "releases.md"
    before = path.read_bytes()

    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(4)
    rig.run(dry_run=True)
    rig.run()

    assert path.read_bytes() == before


def test_broken_releases_table_does_not_fail_the_poll(rig):
    rig.releases("| 이상한 | 표 |\n|---|---|\n| a | b |\n")
    rig.jira.active = [issue("CWEB-1547")]
    rig.parked_release(4)

    assert rig.run() == 0
    assert rig.state()["consecutive_errors"] == 0


def test_watch_failure_does_not_count_as_an_api_error(rig, monkeypatch, capsys):
    """감시는 로컬 계산이다. 버그로 '폴링 연속 실패' 알림이 울려선 안 된다."""
    rig.jira.active = [issue("CWEB-1547")]
    monkeypatch.setattr(
        poll.watch_mod, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert rig.run() == 0

    assert rig.state()["consecutive_errors"] == 0
    assert "감시 평가 실패" in capsys.readouterr().err
