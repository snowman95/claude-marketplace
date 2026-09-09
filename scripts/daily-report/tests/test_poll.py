"""poll.py 통합 테스트.

실제 API·실제 vault 를 건드리지 않는다. 클라이언트는 전부 가짜로 갈아끼우고
vault 는 tmp_path 아래에 만든다.
"""

import json

import pytest

import poll
import state as state_mod
from atlassian import ApiError

FRIDAY = "2026-09-04"
SATURDAY = "2026-09-05"
SUNDAY = "2026-09-06"

ACTIVE = [
    ("CWEB-1547", "진행 중"),
    ("CWEB-1548", "리뷰중"),
    ("CWEB-1550", "진행 중"),
    ("CWEB-1549", "진행 중"),
    ("WV2Q-53784", "접수"),
]

MD_BODY = """
# {key}

## 문의·Blocked

- 없음
"""


def issue(key, status, category="진행 중", summary=None, updated="2026-09-02T18:22:00.000+0900"):
    return {
        "key": key,
        "fields": {
            "summary": summary or f"{key} 요약",
            "status": {"name": status, "statusCategory": {"name": category}},
            "updated": updated,
        },
    }


def adf(text):
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


# ---------------------------------------------------------------------------
# 가짜 클라이언트
# ---------------------------------------------------------------------------

class FakeJira:
    """생성자 자리에 그대로 꽂는다. 호출되면 자기 자신을 돌려준다."""

    def __init__(self):
        self.constructed = 0
        self.jqls = []
        self.active = [issue(k, s) for k, s in ACTIVE]
        self.parked = [issue(f"CWEB-{9000 + i}", "Ready to Deploy") for i in range(37)]
        self.qa = []
        self.fail = None

    def __call__(self, site, email, token):
        self.constructed += 1
        return self

    def search(self, jql, fields, max_results=100):
        self.jqls.append(jql)
        if self.fail is not None:
            raise self.fail
        if "project IN" in jql:
            return list(self.qa)
        if "statusCategory" in jql:
            return list(self.active)
        return list(self.parked)

    def status(self, key, value):
        for item in self.active:
            if item["key"] == key:
                item["fields"]["status"]["name"] = value


class FakeConfluence:
    def __init__(self):
        self.constructed = 0
        self.calls = []
        self.versions = {}
        self.fail = None

    def __call__(self, site, email, token):
        self.constructed += 1
        return self

    def page_versions(self, ids):
        self.calls.append(list(ids))
        if self.fail is not None:
            raise self.fail
        return {i: self.versions[i] for i in ids if i in self.versions}


class FakeFigma:
    def __init__(self):
        self.constructed = 0
        self.calls = []
        self.times = {}
        self.fail = None

    def __call__(self, token):
        self.constructed += 1
        return self

    def last_modified(self, file_key):
        self.calls.append(file_key)
        if self.fail is not None:
            raise self.fail
        return self.times.get(file_key)


# ---------------------------------------------------------------------------
# 환경
# ---------------------------------------------------------------------------

class Rig:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.vault = tmp_path / "projects"
        self.daily = self.vault / "daily"
        self.daily.mkdir(parents=True)
        self.config = tmp_path / "config.toml"
        self.config.write_text(
            "\n".join(
                [
                    f'vault = "{self.vault}"',
                    'site = "example.atlassian.net"',
                    'email = "me@example.com"',
                    'parked_statuses = ["Ready to Deploy"]',
                    'qa_projects = ["WPQ", "WV2Q"]',
                    "qa_lookback_days = 7",
                    "repos = []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.jira = FakeJira()
        self.confluence = FakeConfluence()
        self.figma = FakeFigma()
        self.notifications = []

        monkeypatch.setattr(poll, "JiraClient", self.jira)
        monkeypatch.setattr(poll, "ConfluenceClient", self.confluence)
        monkeypatch.setattr(poll, "FigmaClient", self.figma)
        monkeypatch.setattr(poll, "load_token", lambda email: "atl-token")
        monkeypatch.setattr(poll, "load_figma_token", lambda: "figma-token")
        monkeypatch.setattr(
            poll.subprocess, "run", lambda *a, **k: self.notifications.append(a[0])
        )
        # 자기감시는 tmp vault 에 오늘자 daily 가 없으니 항상 울린다. 여기서는
        # 그 알림이 관심사가 아니다 — 배선·판정은 test_heartbeat.py 가 본다.
        monkeypatch.setattr(poll, "_heartbeat", lambda cfg, data, now: ([], []))

    # --- vault 조립 -------------------------------------------------------
    def md(self, repo, key, frontmatter=None, links=None):
        path = self.vault / repo / "tasks" / "shop3.3.0" / f"{key}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = [f"jira_key: {key}", "blocked: false"]
        head += list(frontmatter or [])
        if links:
            head.append("links:")
            head += links
        path.write_text(
            "---\n" + "\n".join(head) + "\n---\n" + MD_BODY.format(key=key),
            encoding="utf-8",
        )
        return path

    def standard_vault(self):
        self.p1547 = self.md("myproject", "CWEB-1547")
        self.p1548a = self.md("myproject", "CWEB-1548")
        self.p1548b = self.md("myproject_admin", "CWEB-1548")

    # --- 실행 -------------------------------------------------------------
    def run(self, date=FRIDAY, dry_run=False):
        argv = ["--config", str(self.config), "--date", date]
        if dry_run:
            argv.append("--dry-run")
        return poll.main(argv)

    # --- 산출물 -----------------------------------------------------------
    @property
    def state_path(self):
        return self.daily / "_state.json"

    @property
    def pending_path(self):
        return self.daily / "_pending.jsonl"

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def pending(self):
        if not self.pending_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.pending_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


CONFLUENCE_LINKS = [
    "  confluence:",
    '    - id: "5919834330"',
    "      url: https://example/x",
    "      title: 기획서",
    "      version: 43",
    "      local: docs/x.md",
]

FIGMA_LINKS = [
    "  figma:",
    "    - file_key: AbC123",
    '      node_id: "1-2"',
    "      name: 디자인",
    "      last_modified: 2026-08-20T04:11:00Z",
]


# ---------------------------------------------------------------------------
# 주말
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_weekend_still_polls(rig, day, capsys):
    """주말에도 끝까지 돈다 — 여기서 빠지면 주간 회고 미발행을 영원히 못 잡는다.

    억제되는 것은 티켓 이벤트로 인한 Slack 스레드 답글뿐이다
    (test_weekend_suppresses_thread_replies).
    """
    rig.standard_vault()
    before = rig.p1547.read_bytes()

    assert rig.run(date=day) == 0

    assert rig.jira.constructed == 1
    assert rig.state_path.exists()
    assert rig.pending()  # 감시·기록은 주말에도 남는다
    assert rig.p1547.read_bytes() != before
    assert "주말 — 이벤트 알림 억제" in capsys.readouterr().out


@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_weekend_suppresses_thread_replies(rig, notifier, day):
    """주말에 티켓 알림이 울리는 게 원래 피하려던 것이다."""
    rig.standard_vault()
    seed_state(rig, slack={"date": day, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run(date=day) == 0

    assert notifier.sent == []
    assert [e["kind"] for e in rig.pending()] == ["status"]  # 기록은 남는다


# ---------------------------------------------------------------------------
# 첫 실행 / 증분
# ---------------------------------------------------------------------------

def test_first_run_emits_new_for_every_ticket(rig, capsys):
    rig.standard_vault()

    assert rig.run() == 0

    events = rig.pending()
    assert len(events) == 5
    assert {e["ticket"] for e in events} == {k for k, _ in ACTIVE}
    assert {e["kind"] for e in events} == {"new"}

    assert "**추적 시작** 진행 중" in rig.p1547.read_text(encoding="utf-8")
    assert poll.vault_mod.HISTORY_HEADER in rig.p1547.read_text(encoding="utf-8")

    st = rig.state()
    assert set(st["tickets"]) == {k for k, _ in ACTIVE}
    assert st["tickets"]["CWEB-1547"]["status"] == "진행 중"
    assert st["consecutive_errors"] == 0
    assert st["last_error"] is None

    out = capsys.readouterr().out
    assert "활성 5 · parked 37 · 이벤트 5" in out


def test_second_run_reports_only_changed_ticket(rig):
    rig.standard_vault()
    rig.run()
    rig.jira.status("CWEB-1550", "리뷰중")

    rig.run()

    events = rig.pending()[5:]
    assert len(events) == 1
    assert events[0]["ticket"] == "CWEB-1550"
    assert events[0]["kind"] == "status"
    assert "진행 중 → 리뷰중" in events[0]["text"]


def test_no_change_writes_nothing_new(rig):
    rig.standard_vault()
    rig.run()
    before = rig.p1547.stat().st_mtime_ns
    body = rig.p1547.read_bytes()
    count = len(rig.pending())

    rig.run()

    assert len(rig.pending()) == count
    assert rig.p1547.stat().st_mtime_ns == before
    assert rig.p1547.read_bytes() == body


def test_every_event_carries_its_ticket_key(rig):
    rig.standard_vault()
    rig.run()
    assert all(e["ticket"] for e in rig.pending())


# ---------------------------------------------------------------------------
# md 베이스라인 — state 가 없을 때 md 선언값으로 드리프트를 잡는다
# ---------------------------------------------------------------------------

STALE_CONFLUENCE_LINKS = [
    "  confluence:",
    '    - id: "5919834330"',
    "      url: https://example/x",
    "      title: 기획서",
    "      version: 26",
    "      local: docs/x.md",
    '    - id: "5941952582"',
    "      url: https://example/y",
    "      title: 정책",
    "      version: 4",
    "      local: docs/y.md",
]


def test_md_declared_status_drift_surfaces_on_the_first_run(rig):
    """state 가 없어도 md 가 선언한 status 와 라이브가 다르면 잡아야 한다."""
    path = rig.md("myproject", "CWEB-1547", frontmatter=['jira_status: "개발 준비"'])

    rig.run()

    events = [e for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert [e["kind"] for e in events] == ["status"]
    assert "개발 준비 → 진행 중" in events[0]["text"]
    text = path.read_text(encoding="utf-8")
    assert "추적 시작" not in text
    assert "개발 준비 → 진행 중" in text


def test_md_declared_status_matching_live_emits_nothing(rig):
    rig.md("myproject", "CWEB-1547", frontmatter=['jira_status: "진행 중"'])

    rig.run()

    assert [e for e in rig.pending() if e["ticket"] == "CWEB-1547"] == []


def test_md_declared_confluence_version_drift_surfaces_on_the_first_run(rig):
    path = rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "진행 중"'],
        links=STALE_CONFLUENCE_LINKS,
    )
    rig.confluence.versions = {"5919834330": 44, "5941952582": 13}

    rig.run()

    events = [e for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert [e["kind"] for e in events] == ["confluence", "confluence"]
    assert all(e["attention"] is True for e in events)
    texts = " ".join(e["text"] for e in events)
    assert "v26 → v44" in texts
    assert "v4 → v13" in texts
    assert "⚠️" in path.read_text(encoding="utf-8")


def test_md_declaring_both_status_and_links_reports_the_whole_drift(rig):
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "개발 준비"'],
        links=STALE_CONFLUENCE_LINKS,
    )
    rig.confluence.versions = {"5919834330": 44, "5941952582": 13}

    rig.run()

    kinds = [e["kind"] for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert sorted(kinds) == ["confluence", "confluence", "status"]


def test_md_declared_figma_timestamp_drift_surfaces_on_the_first_run(rig):
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "진행 중"'],
        links=FIGMA_LINKS,
    )
    rig.figma.times = {"AbC123": "2026-09-01T09:00:00Z"}

    rig.run()

    events = [e for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert [e["kind"] for e in events] == ["figma"]
    assert events[0]["attention"] is True
    assert "08-20 13:11 → 09-01 18:00" in events[0]["text"]


def test_md_without_any_declaration_still_starts_tracking(rig):
    rig.md("myproject", "CWEB-1547")

    rig.run()

    events = [e for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert [e["kind"] for e in events] == ["new"]


def test_ticket_without_md_still_starts_tracking(rig):
    rig.standard_vault()

    rig.run()

    events = [e for e in rig.pending() if e["ticket"] == "CWEB-1550"]
    assert [e["kind"] for e in events] == ["new"]


def test_md_baseline_drift_is_not_repeated_on_the_second_run(rig):
    """md 는 그대로여도 state 가 생겼으면 두 번째부터는 조용하다."""
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "개발 준비"'],
        links=STALE_CONFLUENCE_LINKS,
    )
    rig.confluence.versions = {"5919834330": 44, "5941952582": 13}
    rig.run()
    seen = len(rig.pending())

    rig.run()

    assert len(rig.pending()) == seen
    links = rig.state()["tickets"]["CWEB-1547"]["links"]["confluence"]
    assert links == {"5919834330": 44, "5941952582": 13}


def test_md_declared_version_ahead_of_live_emits_nothing(rig):
    """수동 롤백 등으로 md 선언이 라이브보다 높으면 변경이 아니다."""
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "진행 중"'],
        links=CONFLUENCE_LINKS,
    )
    rig.confluence.versions = {"5919834330": 40}

    rig.run()

    assert [e for e in rig.pending() if e["ticket"] == "CWEB-1547"] == []


def test_md_link_without_a_version_is_a_first_registration(rig):
    """version 미선언은 '0' 이 아니라 베이스라인 없음이다."""
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "진행 중"'],
        links=[
            "  confluence:",
            '    - id: "5919834330"',
            "      url: https://example/x",
            "      title: 기획서",
        ],
    )
    rig.confluence.versions = {"5919834330": 44}

    rig.run()

    assert [e for e in rig.pending() if e["ticket"] == "CWEB-1547"] == []


def test_corrupt_state_recovers_the_baseline_from_md(rig):
    rig.md(
        "myproject",
        "CWEB-1547",
        frontmatter=['jira_status: "개발 준비"'],
        links=STALE_CONFLUENCE_LINKS,
    )
    rig.confluence.versions = {"5919834330": 44, "5941952582": 13}
    rig.state_path.write_text("{ this is not json", encoding="utf-8")

    rig.run()

    kinds = [e["kind"] for e in rig.pending() if e["ticket"] == "CWEB-1547"]
    assert "new" not in kinds
    assert sorted(kinds) == ["confluence", "confluence", "status"]


# ---------------------------------------------------------------------------
# md 매핑
# ---------------------------------------------------------------------------

def test_ticket_with_two_mds_gets_both_appended(rig):
    rig.standard_vault()

    rig.run()

    for path in (rig.p1548a, rig.p1548b):
        text = path.read_text(encoding="utf-8")
        assert text.count("추적 시작") == 1


def test_ticket_without_md_only_lands_in_pending(rig, capsys):
    rig.standard_vault()

    assert rig.run() == 0

    tickets = {e["ticket"] for e in rig.pending()}
    assert "WV2Q-53784" in tickets
    out = capsys.readouterr().out
    assert "md 없음:" in out
    for key in ("CWEB-1549", "CWEB-1550", "WV2Q-53784"):
        assert key in out.split("md 없음:")[1]


def test_supplementary_md_is_not_appended(rig):
    rig.standard_vault()
    share = rig.vault / "myproject" / "tasks" / "shop3.3.0" / "CWEB-1547-share.md"
    share.write_text("---\njira_key: CWEB-1547\n---\n\n# share\n", encoding="utf-8")
    before = share.read_bytes()

    rig.run()

    assert share.read_bytes() == before


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------

def test_dry_run_writes_not_a_single_byte(rig, capsys):
    rig.standard_vault()
    rig.run()
    rig.jira.status("CWEB-1550", "리뷰중")

    md = rig.p1547.read_bytes()
    md48 = rig.p1548a.read_bytes()
    st = rig.state_path.read_bytes()
    pending = rig.pending_path.read_bytes()
    capsys.readouterr()

    assert rig.run(dry_run=True) == 0

    assert rig.p1547.read_bytes() == md
    assert rig.p1548a.read_bytes() == md48
    assert rig.state_path.read_bytes() == st
    assert rig.pending_path.read_bytes() == pending
    assert "dry-run" in capsys.readouterr().out


def test_dry_run_on_a_clean_vault_creates_no_files(rig):
    rig.standard_vault()

    assert rig.run(dry_run=True) == 0

    assert not rig.state_path.exists()
    assert not rig.pending_path.exists()
    assert not state_mod.bak_path(rig.state_path).exists()


# ---------------------------------------------------------------------------
# 링크 없음 → 조회 없음
# ---------------------------------------------------------------------------

def test_no_links_means_no_confluence_or_figma_call(rig):
    rig.standard_vault()

    rig.run()

    assert rig.confluence.constructed == 0
    assert rig.confluence.calls == []
    assert rig.figma.constructed == 0
    assert rig.figma.calls == []


def test_links_are_fetched_in_one_batch(rig):
    rig.standard_vault()
    rig.md("myproject", "CWEB-1547", links=CONFLUENCE_LINKS + FIGMA_LINKS)
    rig.md("myproject", "CWEB-1548", links=CONFLUENCE_LINKS)
    rig.confluence.versions = {"5919834330": 43}
    rig.figma.times = {"AbC123": "2026-08-20T04:11:00Z"}

    rig.run()

    assert len(rig.confluence.calls) == 1
    assert rig.confluence.calls[0] == ["5919834330"]
    assert rig.figma.calls == ["AbC123"]
    links = rig.state()["tickets"]["CWEB-1547"]["links"]
    assert links == {
        "confluence": {"5919834330": 43},
        "figma": {"AbC123": "2026-08-20T04:11:00Z"},
    }


def test_confluence_version_bump_becomes_an_attention_event(rig):
    path = rig.md("myproject", "CWEB-1547", links=CONFLUENCE_LINKS)
    rig.confluence.versions = {"5919834330": 43}
    rig.run()
    seen = len(rig.pending())

    rig.confluence.versions = {"5919834330": 44}
    rig.run()

    events = [e for e in rig.pending()[seen:] if e["kind"] == "confluence"]
    assert len(events) == 1
    assert events[0]["attention"] is True
    assert "v43 → v44" in events[0]["text"]
    assert "⚠️" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 에러
# ---------------------------------------------------------------------------

def test_jira_failure_exits_zero_and_preserves_state(rig, capsys):
    rig.standard_vault()
    rig.run()
    before = rig.state()

    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    assert rig.run() == 0

    after = rig.state()
    assert after["tickets"] == before["tickets"]
    assert after["consecutive_errors"] == before["consecutive_errors"] + 1
    assert after["last_error"]
    assert "실패" in capsys.readouterr().out


def test_success_resets_the_error_counter(rig):
    rig.standard_vault()
    rig.jira.fail = ApiError(503, "/rest/api/3/search/jql", "boom")
    rig.run()
    assert rig.state()["consecutive_errors"] == 1

    rig.jira.fail = None
    rig.run()

    assert rig.state()["consecutive_errors"] == 0
    assert rig.state()["last_error"] is None


def test_third_consecutive_failure_notifies(rig):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")

    rig.run()
    rig.run()
    assert rig.notifications == []

    rig.run()

    assert len(rig.notifications) == 1
    assert rig.notifications[0][0] == "osascript"
    assert any("display notification" in part for part in rig.notifications[0])


def test_figma_failure_does_not_block_confluence(rig, capsys):
    rig.md("myproject", "CWEB-1547", links=CONFLUENCE_LINKS + FIGMA_LINKS)
    rig.confluence.versions = {"5919834330": 43}
    rig.figma.times = {"AbC123": "2026-08-20T04:11:00Z"}
    rig.run()
    seen = len(rig.pending())

    rig.confluence.versions = {"5919834330": 44}
    rig.figma.fail = ApiError(500, "/v1/files/AbC123", "boom")
    assert rig.run() == 0

    kinds = [e["kind"] for e in rig.pending()[seen:]]
    assert "confluence" in kinds
    assert "figma" not in kinds
    # figma 값은 직전 값을 유지한다 — 사라졌다 다시 나타나며 오탐을 만들지 않는다
    links = rig.state()["tickets"]["CWEB-1547"]["links"]
    assert links["figma"] == {"AbC123": "2026-08-20T04:11:00Z"}
    assert links["confluence"] == {"5919834330": 44}


def test_expired_figma_pat_is_not_an_error(rig):
    """403 은 last_modified() 가 None 을 돌려주는 정상 경로다."""
    rig.md("myproject", "CWEB-1547", links=FIGMA_LINKS)
    rig.figma.times = {}

    assert rig.run() == 0

    assert rig.state()["consecutive_errors"] == 0
    assert rig.state()["last_error"] is None


def test_no_token_never_reaches_stdout(rig, capsys):
    rig.standard_vault()
    rig.run()
    out = capsys.readouterr().out
    assert "atl-token" not in out
    assert "figma-token" not in out


# ---------------------------------------------------------------------------
# QA 후보
# ---------------------------------------------------------------------------

def qa_issue(key, mentions, summary="장바구니 쿠폰 금액 오류"):
    return {
        "key": key,
        "fields": {"summary": summary, "description": adf(f"{mentions} 에서 재현됨")},
    }


def test_qa_candidate_is_proposed_once(rig):
    rig.standard_vault()
    rig.jira.qa = [qa_issue("WPQ-17801", "CWEB-1547")]

    rig.run()

    candidate = rig.state()["qa_candidates"]["WPQ-17801"]
    assert candidate["parent"] == "CWEB-1547"
    assert candidate["state"] == "proposed"
    assert candidate["seen"] == FRIDAY

    events = [e for e in rig.pending() if e["kind"] == "qa_candidate"]
    assert len(events) == 1
    assert events[0]["ticket"] == "CWEB-1547"
    assert events[0]["attention"] is True
    assert "WPQ-17801" in events[0]["text"]
    assert "QA 후보" in rig.p1547.read_text(encoding="utf-8")


@pytest.mark.parametrize("existing", ["proposed", "confirmed", "rejected"])
def test_known_qa_candidate_is_never_reproposed(rig, existing):
    rig.standard_vault()
    rig.jira.qa = [qa_issue("WPQ-17801", "CWEB-1547")]
    state_mod.save(
        rig.state_path,
        {
            **state_mod.empty_state(),
            "qa_candidates": {
                "WPQ-17801": {
                    "parent": "CWEB-1547",
                    "basis": "description 언급",
                    "state": existing,
                    "seen": "2026-09-01",
                }
            },
        },
    )

    rig.run()

    assert [e for e in rig.pending() if e["kind"] == "qa_candidate"] == []
    assert rig.state()["qa_candidates"]["WPQ-17801"]["state"] == existing


def test_active_ticket_in_a_qa_project_is_not_its_own_candidate(rig):
    rig.standard_vault()
    rig.jira.qa = [qa_issue("WV2Q-53784", "CWEB-1547")]

    rig.run()

    assert rig.state()["qa_candidates"] == {}


def test_qa_issue_mentioning_nothing_active_is_ignored(rig):
    rig.standard_vault()
    rig.jira.qa = [qa_issue("WPQ-17900", "CWEB-1200")]

    rig.run()

    assert rig.state()["qa_candidates"] == {}


# ---------------------------------------------------------------------------
# daily 파일
# ---------------------------------------------------------------------------

def test_change_log_is_appended_when_the_daily_file_exists(rig):
    rig.standard_vault()
    daily = rig.daily / f"{FRIDAY}.md"
    daily.write_text(
        "# 2026-09-04 (금)\n\n## 변경 로그 (오늘)\n\n## 히스토리\n\n- 끝\n",
        encoding="utf-8",
    )

    rig.run()

    text = daily.read_text(encoding="utf-8")
    assert "추적 시작" in text
    assert text.index("추적 시작") < text.index("## 히스토리")
    assert text.rstrip().endswith("- 끝")


def test_missing_daily_file_is_skipped(rig):
    rig.standard_vault()

    assert rig.run() == 0

    assert not (rig.daily / f"{FRIDAY}.md").exists()


def test_jql_shape(rig):
    rig.standard_vault()
    rig.run()

    active, parked, qa = rig.jira.jqls
    assert "statusCategory != Done" in active
    assert 'status NOT IN ("Ready to Deploy")' in active
    assert "ORDER BY updated DESC" in active
    assert 'status IN ("Ready to Deploy")' in parked
    assert "project IN" in qa
    assert "created >= -7d" in qa


# ---------------------------------------------------------------------------
# 알림 (Slack 스레드 답글 / 실패 알림)
# ---------------------------------------------------------------------------

BRIEFING_TS = "1788484474.799609"
THURSDAY = "2026-09-03"


class FakeNotifier:
    """notify.Notifier 계약만 흉내낸다. 네트워크는 건드리지 않는다."""

    def __init__(self):
        self.sent = []
        self.result = BRIEFING_TS

    def send(self, text, thread_ts=None):
        self.sent.append({"text": text, "thread_ts": thread_ts})
        return self.result

    def update(self, ts, text):
        return False

    @property
    def texts(self):
        return [call["text"] for call in self.sent]


@pytest.fixture
def notifier(monkeypatch):
    fake = FakeNotifier()
    monkeypatch.setattr(poll, "_build_notifier", lambda cfg: fake)
    return fake


def baseline_tickets(overrides=None):
    tickets = {
        key: {"status": status, "links": {"confluence": {}, "figma": {}}}
        for key, status in ACTIVE
    }
    for key, status in (overrides or {}).items():
        tickets[key]["status"] = status
    return tickets


def seed_state(rig, slack=None, tickets=None):
    data = state_mod.empty_state()
    if slack is not None:
        data["slack"] = slack
    data["tickets"] = tickets if tickets is not None else baseline_tickets()
    state_mod.save(rig.state_path, data)


def test_events_become_one_thread_reply(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")
    rig.jira.status("CWEB-1548", "완료")

    assert rig.run() == 0

    assert len(notifier.sent) == 1
    call = notifier.sent[0]
    assert call["thread_ts"] == BRIEFING_TS
    assert "CWEB-1547" in call["text"]
    assert "CWEB-1548" in call["text"]
    assert len(call["text"].splitlines()) == 2


def test_thread_reply_uses_slack_mrkdwn(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    rig.run()

    text = notifier.sent[0]["text"]
    assert "**" not in text
    assert "*status*" in text
    assert text.startswith("`")
    assert "진행 중 → 리뷰중" in text


def test_attention_event_is_marked_in_the_thread_reply(rig, notifier):
    rig.md("myproject", "CWEB-1547", links=CONFLUENCE_LINKS)
    seed_state(
        rig,
        slack={"date": FRIDAY, "ts": BRIEFING_TS},
        tickets=baseline_tickets(),
    )
    state_path = rig.state_path
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["tickets"]["CWEB-1547"]["links"]["confluence"] = {"5919834330": 44}
    state_mod.save(state_path, data)
    rig.confluence.versions = {"5919834330": 45}

    rig.run()

    text = notifier.sent[0]["text"]
    assert "⚠️" in text
    assert "*Confluence*" in text
    assert "v44 → v45" in text


def test_stale_briefing_date_sends_nothing(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": THURSDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run() == 0

    assert notifier.sent == []
    assert "리뷰중" in rig.p1547.read_text(encoding="utf-8")


def test_missing_slack_key_sends_nothing(rig, notifier):
    rig.standard_vault()
    seed_state(rig)
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run() == 0

    assert notifier.sent == []


def test_slack_entry_without_ts_sends_nothing(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": ""})
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run() == 0

    assert notifier.sent == []


def test_no_events_sends_nothing(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})

    assert rig.run() == 0

    assert notifier.sent == []


def test_dry_run_never_touches_the_notifier(rig, notifier, capsys):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run(dry_run=True) == 0

    assert notifier.sent == []
    out = capsys.readouterr().out
    assert f"[dry-run] 알림(thread {BRIEFING_TS})" in out
    assert "CWEB-1547 *status* 진행 중 → 리뷰중" in out


def test_failed_send_still_saves_state(rig, notifier):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")
    notifier.result = None  # 발송 실패

    assert rig.run() == 0

    assert len(notifier.sent) == 1
    assert rig.state()["tickets"]["CWEB-1547"]["status"] == "리뷰중"
    assert "리뷰중" in rig.p1547.read_text(encoding="utf-8")


def test_raising_notifier_does_not_kill_the_poll(rig, monkeypatch):
    class Boom:
        def send(self, text, thread_ts=None):
            raise RuntimeError("slack down")

        def update(self, ts, text):
            return False

    monkeypatch.setattr(poll, "_build_notifier", lambda cfg: Boom())
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    assert rig.run() == 0

    assert rig.state()["tickets"]["CWEB-1547"]["status"] == "리뷰중"


def test_third_failure_sends_a_root_message(rig, notifier):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")

    rig.run()
    rig.run()
    assert notifier.sent == []

    rig.run()

    assert len(notifier.sent) == 1
    call = notifier.sent[0]
    assert call["thread_ts"] is None
    assert call["text"].startswith("🔴")
    assert "3회 연속 실패" in call["text"]
    assert len(call["text"].splitlines()) == 2
    assert rig.state()["notified_error_at"]


@pytest.mark.parametrize("extra", [1, 2])
def test_further_failures_do_not_spam(rig, notifier, extra):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    for _ in range(3 + extra):
        rig.run()

    assert len(notifier.sent) == 1
    assert rig.state()["consecutive_errors"] == 3 + extra


def test_recovery_resets_the_notification_latch(rig, notifier):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    for _ in range(3):
        rig.run()
    assert len(notifier.sent) == 1

    rig.jira.fail = None
    rig.run()
    assert rig.state()["notified_error_at"] is None

    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    for _ in range(3):
        rig.run()

    assert len(notifier.sent) == 2


def test_dry_run_never_sends_the_failure_notification(rig, notifier, capsys):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    rig.run()
    rig.run()
    assert rig.state()["consecutive_errors"] == 2

    assert rig.run(dry_run=True) == 0

    assert notifier.sent == []
    assert "연속 실패" in capsys.readouterr().out
    assert rig.state()["consecutive_errors"] == 2  # dry-run 은 상태도 쓰지 않는다


def test_failure_notification_carries_one_error_line(rig, notifier):
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    for _ in range(3):
        rig.run()

    body = notifier.sent[0]["text"].splitlines()[1]
    assert body
    assert "\n" not in body


def test_notifications_never_leak_the_token(rig, notifier, capsys):
    rig.standard_vault()
    seed_state(rig, slack={"date": FRIDAY, "ts": BRIEFING_TS})
    rig.jira.status("CWEB-1547", "리뷰중")

    rig.run()

    assert "atl-token" not in notifier.sent[0]["text"]
    assert "atl-token" not in capsys.readouterr().out


def test_unconfigured_notify_falls_back_to_the_local_notifier(rig):
    """`[notify]` 가 없으면 기존 macOS 알림으로 내려간다."""
    rig.standard_vault()
    rig.jira.fail = ApiError(500, "/rest/api/3/search/jql", "boom")
    for _ in range(3):
        rig.run()

    assert len(rig.notifications) == 1
    assert rig.notifications[0][0] == "osascript"
