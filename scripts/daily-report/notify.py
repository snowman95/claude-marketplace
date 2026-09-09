"""알림 계층 — Slack DM / macOS 알림 / 끔.

알림은 부가 기능이다. **알림 실패가 폴링·브리핑을 죽이면 안 된다.** 그래서
`send`/`update` 는 어떤 예외도 밖으로 내보내지 않고 `None`/`False` 를 돌려주며,
사유는 stderr 한 줄로만 남긴다.

토큰은 Authorization 헤더에만 실린다. URL·본문·repr·예외 문자열 어디에도
들어가지 않고, 혹시 예외 메시지가 토큰을 물고 오더라도 stderr 로 나가기 전에
지운다.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import config

SLACK_API = "https://slack.com/api"
SLACK_TOKEN_KEY = "SLACK_BOT_TOKEN"
TIMEOUT = 15

# Slack 메시지 상한. 넘기면 잘라 보낸다 — 통째로 거절당하는 것보다 낫다.
TEXT_LIMIT = 4000
CLIP_MARKER = "…"

NOTIFY_TITLE = "daily-report"
REDACTED = "***"

CHANNEL_SLACK = "slack"
CHANNEL_OSASCRIPT = "osascript"

# 스크립트에 문자열을 끼워넣지 않는다. 따옴표·개행이 섞인 본문도 argv 로 넘기면
# AppleScript 파서를 건드리지 못한다.
OSASCRIPT_ARGV = [
    "osascript",
    "-e", "on run argv",
    "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
    "-e", "end run",
    "--",
]


class Notifier:
    """알림 채널의 최소 계약."""

    def send(self, text: str, thread_ts: str | None = None) -> str | None:
        """메시지 식별자(ts). 실패했거나 채널에 식별자 개념이 없으면 None."""
        raise NotImplementedError

    def update(self, ts: str, text: str) -> bool:
        raise NotImplementedError


class SlackNotifier(Notifier):
    """chat.postMessage / chat.update. target 은 채널 ID 또는 사용자 ID(=DM)."""

    def __init__(self, token: str, target: str):
        self._token = token
        self._target = target

    def __repr__(self) -> str:
        return f"{type(self).__name__}(target={self._target!r})"

    def send(self, text: str, thread_ts: str | None = None) -> str | None:
        body = {"channel": self._target, "text": _clip(text)}
        if thread_ts:
            body["thread_ts"] = str(thread_ts)
        data = self._post("chat.postMessage", body)
        if data is None:
            return None
        ts = data.get("ts") or (data.get("message") or {}).get("ts")
        return str(ts) if ts else None

    def update(self, ts: str, text: str) -> bool:
        body = {"channel": self._target, "ts": str(ts), "text": _clip(text)}
        return self._post("chat.update", body) is not None

    def _post(self, method: str, body: dict) -> dict | None:
        """ok:true 면 응답 dict, 아니면 None.

        Slack 은 실패해도 HTTP 200 을 준다. 상태 코드가 아니라 `ok` 를 본다.
        """
        request = urllib.request.Request(
            f"{SLACK_API}/{method}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = json.load(response)
        except Exception as exc:  # 알림 실패가 호출자를 죽이지 않는다
            self._warn(f"{method}: {_safe(exc)}")
            return None
        if not isinstance(data, dict) or not data.get("ok"):
            error = data.get("error") if isinstance(data, dict) else ""
            self._warn(f"{method}: {error or 'ok:false'}")
            return None
        return data

    def _warn(self, message: str) -> None:
        if self._token:
            message = message.replace(self._token, REDACTED)
        _warn(message)


class OsascriptNotifier(Notifier):
    """macOS 알림 센터. ts 개념이 없어 send 는 항상 None, update 는 False."""

    def __init__(self, title: str = NOTIFY_TITLE):
        self._title = title

    def __repr__(self) -> str:
        return f"{type(self).__name__}(title={self._title!r})"

    def send(self, text: str, thread_ts: str | None = None) -> str | None:
        try:
            subprocess.run(
                OSASCRIPT_ARGV + [_text(text), self._title],
                check=False,
                capture_output=True,
                timeout=TIMEOUT,
            )
        except Exception as exc:
            _warn(f"osascript: {_safe(exc)}")
        return None

    def update(self, ts: str, text: str) -> bool:
        return False


class MultiNotifier(Notifier):
    """여러 채널로 같은 메시지를 겹쳐 보낸다.

    자기감시 알림이 Slack 하나에만 실려 있으면, 봇 토큰이 만료되는 순간 경고가
    조용히 사라진다 — 이 시스템이 애초에 잡으려던 실패 클래스와 똑같다. 그래서
    **하나가 실패해도 나머지를 계속** 보낸다.
    """

    def __init__(self, notifiers):
        self._notifiers = [n for n in (notifiers or []) if n is not None]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._notifiers!r})"

    @property
    def notifiers(self) -> list:
        return list(self._notifiers)

    def send(self, text: str, thread_ts: str | None = None) -> str | None:
        """전부에게 보내고 **첫 성공의 ts** 를 돌려준다. 아무도 못 주면 None."""
        first = None
        for notifier in self._notifiers:
            try:
                ts = notifier.send(text, thread_ts=thread_ts)
            except Exception as exc:  # 한 채널이 터져도 다음 채널로 계속 간다
                _warn(f"multi send: {_safe(exc)}")
                continue
            if first is None and ts:
                first = str(ts)
        return first

    def update(self, ts: str, text: str) -> bool:
        """하나라도 고쳤으면 True."""
        updated = False
        for notifier in self._notifiers:
            try:
                if notifier.update(ts, text):
                    updated = True
            except Exception as exc:
                _warn(f"multi update: {_safe(exc)}")
        return updated


class NullNotifier(Notifier):
    """알림 끔. 아무것도 하지 않고 아무것도 출력하지 않는다."""

    def send(self, text: str, thread_ts: str | None = None) -> str | None:
        return None

    def update(self, ts: str, text: str) -> bool:
        return False


def build(cfg) -> Notifier:
    """config 의 `[notify]` 를 보고 채널을 고른다.

    설정이 없거나 자격증명이 빠졌으면 조용히 NullNotifier 로 내려간다. 알림
    설정 때문에 폴링이 멈추는 일은 없어야 한다.
    """
    try:
        settings = _notify_settings(cfg)
        channel = _text(settings.get("channel")).strip().lower()
        if channel == CHANNEL_SLACK:
            return _build_slack(_text(settings.get("slack_target")).strip())
        if channel == CHANNEL_OSASCRIPT:
            return OsascriptNotifier()
    except Exception as exc:
        _warn(f"알림 설정 로드 실패 — 알림 끔: {_safe(exc)}")
    return NullNotifier()


def load_slack_token() -> str | None:
    """$SLACK_BOT_TOKEN → daily-track.env → config. 없으면 None (에러 아님)."""
    token = os.environ.get(SLACK_TOKEN_KEY)
    if token:
        return token
    for path in (config.ENV_FILE, config.CONFIG_FILE):
        # KEY=value 파서는 config.py 하나만 두고 재사용한다.
        token = config._read_key(path, key=SLACK_TOKEN_KEY)
        if token:
            return token
    return None


def _build_slack(target: str) -> Notifier:
    token = load_slack_token()
    if not token or not target:
        missing = "토큰" if not token else "slack_target"
        _warn(f"slack 알림에 {missing} 이(가) 없다 — 알림 끔")
        return NullNotifier()
    return SlackNotifier(token, target)


def _notify_settings(cfg) -> dict:
    """dict·객체 어느 쪽으로 와도 `[notify]` 를 꺼낸다. 없으면 빈 값."""
    table = _get(cfg, "notify")
    if table is None:
        return {
            "channel": _get(cfg, "notify_channel"),
            "slack_target": _get(cfg, "notify_slack_target"),
        }
    return {
        "channel": _get(table, "channel"),
        "slack_target": _get(table, "slack_target"),
    }


def _get(obj, key):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _text(value) -> str:
    return "" if value is None else str(value)


def _clip(text) -> str:
    text = _text(text)
    if len(text) <= TEXT_LIMIT:
        return text
    return text[: TEXT_LIMIT - len(CLIP_MARKER)] + CLIP_MARKER


def _warn(message: str) -> None:
    print(f"[notify] {message}", file=sys.stderr)


def _safe(exc: Exception) -> str:
    """예외를 한 줄로. 토큰은 헤더에만 있어 여기까지 오지 않는다."""
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]
