#!/usr/bin/env python3
"""브리핑 본문을 Slack DM 루트 메시지로 보내고 그 `ts` 를 남긴다.

    python3 send_brief.py --date YYYY-MM-DD [--dry-run] < brief.md

`daily-brief` 스킬이 부른다. 여기서 기록한 `_state.json["slack"]` 을 낮의
`poll.py` 가 읽어 같은 메시지의 스레드에 변경분을 덧붙인다. 즉 이 파일이
하루 한 스레드 규칙의 시작점이다.

**발송 실패는 exit 0 이다.** 브리핑 파일은 이미 만들어졌고, 알림이 안 갔다고
브리핑 전체를 실패로 만들지 않는다. 대신 `slack` 키를 쓰지 않아서 폴링이
엉뚱한 ts 에 답글을 다는 일도 없다.
"""

import argparse
import sys
from pathlib import Path

import notify as notify_mod
import state as state_mod
from config import load_config

STATE_NAME = "_state.json"
SLACK_KEY = "slack"


def main(argv=None):
    args = _parse_args(argv)

    text = sys.stdin.read().strip()
    if not text:
        # 보낼 게 없는 건 발송 실패가 아니라 호출 실수다. 조용히 넘기지 않는다.
        print("브리핑 본문이 stdin 으로 오지 않았다", file=sys.stderr)
        return 1

    try:
        cfg = load_config(Path(args.config) if args.config else None)
    except Exception as exc:
        print(f"설정 로드 실패: {_safe(exc)}", file=sys.stderr)
        return 1

    if args.dry_run:
        _preview(cfg, args.date, text)
        return 0

    ts = _send(cfg, text)
    if not ts:
        # 채널에 ts 개념이 없거나(osascript) 발송이 실패했다. 폴링이 스레드를
        # 잇지 못할 뿐, 브리핑은 성공이다.
        print("Slack ts 를 받지 못했다 — 스레드 답글 없이 진행한다")
        return 0

    _record(cfg, args.date, ts)
    print(f"Slack 발송 완료 · ts {ts}")
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="브리핑 본문을 Slack 으로 발송")
    parser.add_argument("--date", required=True, help="브리핑 기준일 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="발송도 저장도 하지 않는다")
    parser.add_argument("--config", help="config.toml 경로")
    return parser.parse_args(argv)


def _send(cfg, text):
    """루트 메시지로 발송. 어떤 실패도 밖으로 내보내지 않고 None 을 준다."""
    try:
        notifier = notify_mod.build(cfg)
        return notifier.send(text)  # thread_ts 없음 = 스레드의 시작
    except Exception as exc:
        print(f"Slack 발송 실패: {_safe(exc)}")
        return None


def _record(cfg, date, ts):
    """`slack` 키만 갈아끼운다. 폴링이 같은 파일을 쓰므로 나머지는 손대지 않는다."""
    path = cfg.daily_dir / STATE_NAME
    data = state_mod.load(path)
    data[SLACK_KEY] = {"date": str(date), "ts": str(ts)}
    state_mod.save(path, data)


def _preview(cfg, date, text):
    settings = getattr(cfg, "notify", None) or {}
    channel = settings.get("channel") or "(없음 — 알림 끔)"
    target = settings.get("slack_target") or "(없음)"
    print(f"[dry-run] {date} 브리핑 → channel={channel} target={target}")
    print(f"[dry-run] _state.json 의 {SLACK_KEY} 키는 갱신하지 않는다")
    for line in text.split("\n"):
        print(f"    {line}")


def _safe(exc):
    """예외를 한 줄로. 토큰은 notify.py 가 헤더에만 실어 여기까지 오지 않는다."""
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]


if __name__ == "__main__":
    sys.exit(main())
