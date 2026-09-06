"""_state.json 의 원자적 읽기/쓰기와 티켓 diff.

히스토리는 append-only 라 diff 가 흔들리면 되돌릴 수 없다.
판단이 서지 않는 입력에는 이벤트를 만들지 않는 쪽을 택한다.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1

KST = timezone(timedelta(hours=9))

# Figma API 의 lastModified 는 편집이 없어도 초 단위로 흔들린다.
# 이 폭 미만의 차이는 변경으로 보지 않는다.
FIGMA_TOLERANCE = timedelta(seconds=60)

_KIND_NEW = "new"
_KIND_STATUS = "status"
_KIND_CONFLUENCE = "confluence"
_KIND_FIGMA = "figma"
_KIND_QA_CANDIDATE = "qa_candidate"


@dataclass
class Event:
    ticket: str
    kind: str
    text: str
    attention: bool


def empty_state() -> dict:
    return {
        "schema": SCHEMA,
        "polled_at": None,
        "consecutive_errors": 0,
        "last_error": None,
        "tickets": {},
        "qa_candidates": {},
    }


def bak_path(path: Path) -> Path:
    return Path(str(path) + ".bak")


def load(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return empty_state()
    data = _read_json(path)
    if data is None:
        data = _read_json(bak_path(path))
    if data is None:
        return empty_state()
    return _fill_defaults(data)


def save(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _backup(path)
    _atomic_write(path, payload)


def diff_ticket(old: dict | None, new: dict) -> list[Event]:
    new = new or {}
    key = str(new.get("key") or "")

    if old is None:
        return [
            Event(key, _KIND_NEW, f'**추적 시작** {new.get("status", "")}', False)
        ]

    events: list[Event] = []

    old_status = old.get("status")
    new_status = new.get("status")
    if old_status and new_status and old_status != new_status:
        events.append(
            Event(key, _KIND_STATUS, f"**status** {old_status} → {new_status}", False)
        )

    old_links = old.get("links") or {}
    new_links = new.get("links") or {}

    old_conf = old_links.get("confluence") or {}
    new_conf = new_links.get("confluence") or {}
    for page_id in sorted(new_conf):
        if page_id not in old_conf:
            continue  # 최초 등록은 변경이 아니다
        old_v = _as_int(old_conf[page_id])
        new_v = _as_int(new_conf[page_id])
        if old_v is None or new_v is None or new_v <= old_v:
            continue
        events.append(
            Event(
                key,
                _KIND_CONFLUENCE,
                f"**Confluence** `{page_id}` v{old_v} → v{new_v}",
                True,
            )
        )

    old_figma = old_links.get("figma") or {}
    new_figma = new_links.get("figma") or {}
    for file_key in sorted(new_figma):
        if file_key not in old_figma:
            continue  # 최초 등록은 변경이 아니다
        old_ts = old_figma[file_key]
        new_ts = new_figma[file_key]
        if not old_ts or not new_ts or old_ts == new_ts:
            continue
        if not _figma_changed(old_ts, new_ts):
            continue
        events.append(
            Event(
                key,
                _KIND_FIGMA,
                f"**Figma** `{file_key}` {_fmt_ts(old_ts)} → {_fmt_ts(new_ts)}",
                True,
            )
        )

    return events


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # Figma 는 UTC 로 준다
    return parsed


def _figma_changed(old_ts, new_ts) -> bool:
    old_dt = _parse_ts(old_ts)
    new_dt = _parse_ts(new_ts)
    if old_dt is None or new_dt is None:
        return True  # 문자열 비교 폴백. 여기 오면 이미 다른 값이다
    return abs(new_dt - old_dt) >= FIGMA_TOLERANCE


def _fmt_ts(value) -> str:
    parsed = _parse_ts(value)
    if parsed is None:
        return str(value)[:16]
    return parsed.astimezone(KST).strftime("%m-%d %H:%M")


def _read_json(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _fill_defaults(data: dict) -> dict:
    for key, value in empty_state().items():
        data.setdefault(key, value)
    return data


def _backup(path: Path) -> None:
    if not path.exists():
        return
    try:
        previous = path.read_bytes()
    except OSError:
        return
    try:
        _atomic_write(bak_path(path), previous)
    except OSError:
        pass  # 백업 실패가 본 저장을 막지 않는다


def _atomic_write(path: Path, payload: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
