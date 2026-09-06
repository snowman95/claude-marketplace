import json
import subprocess
import urllib.error
import urllib.request

import pytest

import config
import notify
from notify import (
    NullNotifier,
    Notifier,
    OsascriptNotifier,
    SlackNotifier,
    build,
)

TOKEN = "xoxb-1111-2222-do-not-leak"
TARGET = "U0000000000"


@pytest.fixture
def slack():
    return SlackNotifier(TOKEN, TARGET)


@pytest.fixture
def no_env(monkeypatch, tmp_path):
    """실제 머신의 daily-track.env 가 테스트로 새어들어오지 않게 막는다."""
    monkeypatch.delenv(notify.SLACK_TOKEN_KEY, raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.config")
    return tmp_path


def body(http, index=0):
    return json.loads(http.calls[index].data.decode("utf-8"))


# --- SlackNotifier.send ---------------------------------------------------


def test_send_posts_to_chat_postmessage(slack, http):
    http.add_json({"ok": True, "channel": "D0BUFTZSVL7", "ts": "1756950000.000100"})

    ts = slack.send("브리핑 나왔다")

    assert ts == "1756950000.000100"
    assert http.calls[0].full_url == "https://slack.com/api/chat.postMessage"
    assert http.calls[0].get_method() == "POST"
    headers = http.headers()
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert body(http) == {"channel": TARGET, "text": "브리핑 나왔다"}


def test_send_body_is_utf8_json(slack, http):
    http.add_json({"ok": True, "ts": "1.1"})
    slack.send("한글 본문")
    assert "한글 본문".encode("utf-8") in http.calls[0].data


def test_send_includes_thread_ts(slack, http):
    http.add_json({"ok": True, "ts": "1756950001.000200"})
    slack.send("답글", thread_ts="1756950000.000100")
    assert body(http)["thread_ts"] == "1756950000.000100"


def test_send_omits_thread_ts_when_absent(slack, http):
    http.add_json({"ok": True, "ts": "1.1"})
    slack.send("본문")
    assert "thread_ts" not in body(http)


def test_send_falls_back_to_message_ts(slack, http):
    http.add_json({"ok": True, "message": {"ts": "1756950002.000300"}})
    assert slack.send("본문") == "1756950002.000300"


def test_send_returns_none_when_ts_missing(slack, http):
    http.add_json({"ok": True})
    assert slack.send("본문") is None


def test_send_returns_none_on_ok_false(slack, http, capsys):
    http.add_json({"ok": False, "error": "channel_not_found"})

    assert slack.send("본문") is None

    assert "channel_not_found" in capsys.readouterr().err


def test_send_returns_none_on_http_500(slack, http, capsys):
    http.add_error(500, b"server exploded")
    assert slack.send("본문") is None
    assert capsys.readouterr().err.strip()


def test_send_returns_none_on_network_error(slack, monkeypatch, capsys):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    assert slack.send("본문") is None
    assert capsys.readouterr().err.strip()


def test_send_survives_non_json_response(slack, monkeypatch):
    class Garbage:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *a):
            return b"<html>nope</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: Garbage())
    assert slack.send("본문") is None


def test_send_clips_text_over_limit(slack, http):
    http.add_json({"ok": True, "ts": "1.1"})

    slack.send("가" * 5000)

    text = body(http)["text"]
    assert len(text) == notify.TEXT_LIMIT
    assert text.endswith(notify.CLIP_MARKER)


def test_send_keeps_text_at_limit_intact(slack, http):
    http.add_json({"ok": True, "ts": "1.1"})
    exact = "a" * notify.TEXT_LIMIT
    slack.send(exact)
    assert body(http)["text"] == exact


# --- SlackNotifier.update -------------------------------------------------


def test_update_calls_chat_update(slack, http):
    http.add_json({"ok": True, "ts": "1756950000.000100"})

    assert slack.update("1756950000.000100", "고친 본문") is True

    assert http.calls[0].full_url == "https://slack.com/api/chat.update"
    assert body(http) == {
        "channel": TARGET,
        "ts": "1756950000.000100",
        "text": "고친 본문",
    }


def test_update_returns_false_on_ok_false(slack, http, capsys):
    http.add_json({"ok": False, "error": "message_not_found"})
    assert slack.update("1.1", "본문") is False
    assert "message_not_found" in capsys.readouterr().err


def test_update_returns_false_on_http_error(slack, http):
    http.add_error(500, b"boom")
    assert slack.update("1.1", "본문") is False


def test_update_clips_text_over_limit(slack, http):
    http.add_json({"ok": True})
    slack.update("1.1", "나" * 4500)
    assert len(body(http)["text"]) == notify.TEXT_LIMIT


# --- 토큰 비노출 ----------------------------------------------------------


def test_token_absent_from_repr_and_str(slack):
    assert TOKEN not in repr(slack)
    assert TOKEN not in str(slack)
    assert TARGET in repr(slack)


def test_token_absent_from_stderr_on_failures(slack, http, capsys):
    http.add_error(401, b'{"ok":false,"error":"invalid_auth"}')
    http.add_json({"ok": False, "error": "not_authed"})

    slack.send("본문")
    slack.update("1.1", "본문")

    out, err = capsys.readouterr()
    assert TOKEN not in err
    assert TOKEN not in out


def test_token_redacted_even_if_exception_carries_it(slack, monkeypatch, capsys):
    def boom(req, timeout=None):
        raise RuntimeError(f"proxy rejected Bearer {TOKEN}")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    assert slack.send("본문") is None
    out, err = capsys.readouterr()
    assert TOKEN not in err
    assert TOKEN not in out


def test_token_never_lands_in_the_url(slack, http):
    http.add_json({"ok": True, "ts": "1.1"})
    slack.send("본문")
    assert TOKEN not in http.calls[0].full_url


# --- OsascriptNotifier ----------------------------------------------------


@pytest.fixture
def run_calls(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_osascript_send_runs_subprocess(run_calls):
    assert OsascriptNotifier().send("빌드 깨졌다") is None

    cmd, kwargs = run_calls[0]
    assert cmd[0] == "osascript"
    assert kwargs["check"] is False
    assert "빌드 깨졌다" in cmd


def test_osascript_passes_text_as_argv_not_inline_script(run_calls):
    nasty = 'he said "boom"\ndisplay dialog "pwned"'

    OsascriptNotifier().send(nasty)

    cmd = run_calls[0][0]
    assert "--" in cmd
    argv = cmd[cmd.index("--") + 1:]
    assert argv[0] == nasty  # 문자열은 인자로만 전달된다
    script = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-e"]
    assert all(nasty not in fragment for fragment in script)
    assert all("pwned" not in fragment for fragment in script)


def test_osascript_send_survives_missing_binary(monkeypatch, capsys):
    def boom(cmd, **kwargs):
        raise FileNotFoundError("osascript")

    monkeypatch.setattr(subprocess, "run", boom)

    assert OsascriptNotifier().send("본문") is None
    assert capsys.readouterr().err.strip()


def test_osascript_send_survives_timeout(monkeypatch):
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(subprocess, "run", boom)
    assert OsascriptNotifier().send("본문") is None


def test_osascript_send_ignores_thread_ts(run_calls):
    assert OsascriptNotifier().send("본문", thread_ts="1.1") is None
    assert len(run_calls) == 1


def test_osascript_update_is_a_noop(run_calls):
    assert OsascriptNotifier().update("1.1", "본문") is False
    assert run_calls == []


# --- NullNotifier ---------------------------------------------------------


def test_null_notifier_has_no_side_effects(http, run_calls):
    null = NullNotifier()

    assert null.send("본문") is None
    assert null.send("본문", thread_ts="1.1") is None
    assert null.update("1.1", "본문") is False

    assert http.calls == []
    assert run_calls == []


def test_null_notifier_is_quiet(capsys):
    NullNotifier().send("본문")
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


# --- Notifier 베이스 ------------------------------------------------------


def test_base_notifier_is_abstract():
    base = Notifier()
    with pytest.raises(NotImplementedError):
        base.send("본문")
    with pytest.raises(NotImplementedError):
        base.update("1.1", "본문")


# --- build ----------------------------------------------------------------


class Cfg:
    def __init__(self, notify=None):
        self.notify = notify


def test_build_slack_with_token(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)

    built = build(Cfg({"channel": "slack", "slack_target": TARGET}))

    assert isinstance(built, SlackNotifier)
    assert TARGET in repr(built)


def test_build_slack_reads_token_from_env_file(no_env, monkeypatch):
    env_file = no_env / "daily-track.env"
    env_file.write_text(
        f"ATLASSIAN_API_TOKEN=atl\n{notify.SLACK_TOKEN_KEY}={TOKEN}\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    assert isinstance(build(Cfg({"channel": "slack", "slack_target": TARGET})), SlackNotifier)


def test_build_slack_without_token_falls_back(no_env, capsys):
    built = build(Cfg({"channel": "slack", "slack_target": TARGET}))
    assert isinstance(built, NullNotifier)
    assert capsys.readouterr().err.strip()


def test_build_slack_without_target_falls_back(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    assert isinstance(build(Cfg({"channel": "slack"})), NullNotifier)


def test_build_channel_none(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    assert isinstance(build(Cfg({"channel": "none", "slack_target": TARGET})), NullNotifier)


def test_build_without_notify_section(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    assert isinstance(build(Cfg()), NullNotifier)


def test_build_with_config_lacking_notify_attribute(no_env):
    assert isinstance(build(config.load_config()), NullNotifier)


def test_build_with_none_config(no_env):
    assert isinstance(build(None), NullNotifier)


def test_build_osascript(no_env):
    assert isinstance(build(Cfg({"channel": "osascript"})), OsascriptNotifier)


def test_build_unknown_channel_falls_back(no_env):
    assert isinstance(build(Cfg({"channel": "telegram"})), NullNotifier)


def test_build_accepts_plain_dict_config(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    cfg = {"notify": {"channel": "slack", "slack_target": TARGET}}
    assert isinstance(build(cfg), SlackNotifier)


def test_build_accepts_flat_keys(no_env):
    class Flat:
        notify_channel = "osascript"

    assert isinstance(build(Flat()), OsascriptNotifier)


def test_build_is_case_and_space_tolerant(no_env, monkeypatch):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    built = build(Cfg({"channel": " Slack ", "slack_target": f" {TARGET} "}))
    assert isinstance(built, SlackNotifier)
    assert TARGET in repr(built)


def test_build_never_leaks_token(no_env, monkeypatch, capsys):
    monkeypatch.setenv(notify.SLACK_TOKEN_KEY, TOKEN)
    built = build(Cfg({"channel": "slack", "slack_target": TARGET}))
    out, err = capsys.readouterr()
    assert TOKEN not in repr(built)
    assert TOKEN not in out
    assert TOKEN not in err
