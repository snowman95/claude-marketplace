"""send_brief.py — 브리핑 본문을 Slack 루트 메시지로 보내고 ts 를 남긴다."""
import io
import json
import sys

import pytest

import notify as notify_mod
import send_brief

DATE = "2026-09-04"
BRIEF = "*오늘의 브리핑*\n• CWEB-1547 진행 중"


class FakeNotifier:
    """send 를 기록만 하는 Notifier. 실제 Slack 을 절대 부르지 않는다."""

    def __init__(self, ts="1788484474.799609"):
        self._ts = ts
        self.sent = []

    def send(self, text, thread_ts=None):
        self.sent.append((text, thread_ts))
        return self._ts

    def update(self, ts, text):
        return False


class BoomNotifier(FakeNotifier):
    def send(self, text, thread_ts=None):
        self.sent.append((text, thread_ts))
        raise RuntimeError("slack down")


CONFIG_TOML = """
vault = "{vault}"
site = "example.atlassian.net"
email = "me@example.com"
parked_statuses = []
qa_projects = []
qa_lookback_days = 7
repos = []

[notify]
channel = "slack"
slack_target = "U0TEST"
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """config + _state.json 을 tmp 에 깔고 stdin/notifier 를 갈아끼울 준비."""
    vault = tmp_path / "projects"
    (vault / "daily").mkdir(parents=True)
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TOML.format(vault=vault), encoding="utf-8")
    return {
        "config": config_path,
        "state": vault / "daily" / "_state.json",
    }


def seed_state(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_state(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(workspace, monkeypatch, notifier, stdin=BRIEF, extra=()):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    if notifier is not None:
        monkeypatch.setattr(notify_mod, "build", lambda cfg: notifier)
    argv = ["--date", DATE, "--config", str(workspace["config"]), *extra]
    return send_brief.main(argv)


# --- 정상 발송 -----------------------------------------------------------


def test_sends_stdin_body_and_records_ts(workspace, monkeypatch, capsys):
    notifier = FakeNotifier()

    assert run(workspace, monkeypatch, notifier) == 0

    assert notifier.sent == [(BRIEF, None)]  # 루트 메시지 — thread_ts 없음
    state = read_state(workspace["state"])
    assert state["slack"] == {"date": DATE, "ts": "1788484474.799609"}


def test_preserves_other_state_keys(workspace, monkeypatch):
    seed_state(
        workspace["state"],
        {
            "schema": 1,
            "polled_at": "2026-09-04T09:00:00+09:00",
            "tickets": {"CWEB-1547": {"status": "진행 중"}},
            "qa_candidates": {"WPQ-1": {"state": "proposed"}},
        },
    )

    assert run(workspace, monkeypatch, FakeNotifier()) == 0

    state = read_state(workspace["state"])
    assert state["tickets"] == {"CWEB-1547": {"status": "진행 중"}}
    assert state["qa_candidates"] == {"WPQ-1": {"state": "proposed"}}
    assert state["polled_at"] == "2026-09-04T09:00:00+09:00"
    assert state["slack"]["ts"] == "1788484474.799609"


def test_replaces_yesterdays_slack_entry(workspace, monkeypatch):
    seed_state(
        workspace["state"],
        {"schema": 1, "slack": {"date": "2026-09-03", "ts": "111.222"}, "tickets": {}},
    )

    assert run(workspace, monkeypatch, FakeNotifier(ts="999.888")) == 0

    assert read_state(workspace["state"])["slack"] == {"date": DATE, "ts": "999.888"}


# --- 발송 실패 -----------------------------------------------------------


def test_missing_ts_leaves_slack_key_alone(workspace, monkeypatch, capsys):
    """osascript 처럼 ts 개념이 없거나 발송이 실패한 경우."""
    notifier = FakeNotifier(ts=None)

    assert run(workspace, monkeypatch, notifier) == 0

    assert not workspace["state"].exists() or "slack" not in read_state(
        workspace["state"]
    )
    assert capsys.readouterr().out.strip()  # 실패 사유 한 줄


def test_send_failure_does_not_clobber_existing_state(workspace, monkeypatch):
    seed_state(workspace["state"], {"schema": 1, "tickets": {"CWEB-1": {}}})

    assert run(workspace, monkeypatch, FakeNotifier(ts=None)) == 0

    state = read_state(workspace["state"])
    assert state["tickets"] == {"CWEB-1": {}}
    assert "slack" not in state


def test_raising_notifier_still_exits_zero(workspace, monkeypatch):
    """Notifier 가 예외를 던져도 브리핑은 이미 만들어졌다. 죽이지 않는다."""
    assert run(workspace, monkeypatch, BoomNotifier()) == 0
    assert not workspace["state"].exists()


# --- dry-run -------------------------------------------------------------


def test_dry_run_sends_nothing_and_writes_nothing(workspace, monkeypatch, capsys):
    notifier = FakeNotifier()

    assert run(workspace, monkeypatch, notifier, extra=["--dry-run"]) == 0

    assert notifier.sent == []
    assert not workspace["state"].exists()
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "CWEB-1547" in out  # 무엇을 보낼지 보여준다


def test_dry_run_does_not_touch_existing_state(workspace, monkeypatch):
    seed_state(workspace["state"], {"schema": 1, "tickets": {"CWEB-1": {}}})
    before = workspace["state"].read_text(encoding="utf-8")

    assert run(workspace, monkeypatch, FakeNotifier(), extra=["--dry-run"]) == 0

    assert workspace["state"].read_text(encoding="utf-8") == before


# --- 빈 stdin ------------------------------------------------------------


@pytest.mark.parametrize("stdin", ["", "   \n\n  "])
def test_empty_stdin_is_an_error(workspace, monkeypatch, stdin):
    notifier = FakeNotifier()

    assert run(workspace, monkeypatch, notifier, stdin=stdin) == 1

    assert notifier.sent == []
    assert not workspace["state"].exists()


def test_empty_stdin_errors_even_with_dry_run(workspace, monkeypatch):
    assert run(workspace, monkeypatch, FakeNotifier(), stdin="", extra=["--dry-run"]) == 1


# --- 발송 본문 -----------------------------------------------------------


def test_body_is_sent_verbatim_apart_from_trailing_newline(workspace, monkeypatch):
    notifier = FakeNotifier()
    body = "줄1\n줄2  \n"

    run(workspace, monkeypatch, notifier, stdin=body)

    assert notifier.sent[0][0] == "줄1\n줄2"


def test_uses_notify_build_with_the_loaded_config(workspace, monkeypatch):
    seen = {}

    def fake_build(cfg):
        seen["cfg"] = cfg
        return FakeNotifier()

    monkeypatch.setattr(notify_mod, "build", fake_build)
    monkeypatch.setattr(sys, "stdin", io.StringIO(BRIEF))

    send_brief.main(["--date", DATE, "--config", str(workspace["config"])])

    assert seen["cfg"].notify["slack_target"] == "U0TEST"
