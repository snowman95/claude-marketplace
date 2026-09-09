"""`{vault}/daily/releases.md` 의 릴리즈 일정표 파서.

**이 파일은 사람이 관리한다. 여기서 절대 쓰지 않는다.** 읽기 전용이고, 어떤
입력에도 예외를 던지지 않는다 — 표가 깨졌다고 감시 계층이 죽으면 안 된다.
모르는 값은 빈 칸이든 오타든 전부 `None` 이다. 일정을 모르는 것은 경보가
아니므로, 값이 없으면 watch 가 그 규칙을 건너뛴다.

열 순서는 헤더에서 읽는다. 사람이 열을 옮기거나 `비고` 를 지워도 동작한다.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

RELEASES_NAME = "releases.md"

# "2026-09-14", "2026/09/14", "2026.09.14" — 뒤에 `(월)` 같은 장식이 붙어도 된다.
DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")

# "shop3.3.0" / "oms1.14.0" / "shop-3.3.0" / "shopv3.3.0".
# 접두사를 비탐욕으로 잡아 뒤따르는 `v` 를 버전 쪽으로 넘긴다.
FIX_VERSION_RE = re.compile(r"^([A-Za-z]+?)[\s\-_]*v?(\d+(?:\.\d+)+)$")

FENCE_RE = re.compile(r"^(```|~~~)")
SEPARATOR_RE = re.compile(r"^[\s|:-]+$")

# 헤더 셀 → 역할. 위에서부터 먼저 맞는 것을 쓴다 ("prod 배포" 가 배포로 가야 한다).
_ROLES = (
    ("qa_start", ("qa",)),
    ("prod_deploy", ("배포", "deploy", "prod", "release")),
    ("project", ("프로젝트", "project")),
    ("version", ("버전", "version")),
    ("note", ("비고", "note", "메모", "remark")),
)

_REQUIRED = ("project", "version")

# `비고` 가 "이미 나갔다"고 말하는 표현. 나간 릴리즈에 티켓 하나가 남아 있는 것은
# 🔴 로 매일 띄울 일이 아니다 (watch 가 W1 을 🟡 로 내린다).
_RELEASED_WORDS = ("배포완료", "배포 완료", "완료", "released")

# "미완료" 는 반대말이다. `완료` 포함으로 읽으면 살아 있는 red 가 조용히 사라진다.
_NOT_RELEASED_WORDS = ("미완료",)


@dataclass(frozen=True)
class Release:
    project: str
    version: str
    qa_start: date | None
    prod_deploy: date | None
    note: str
    released: bool = field(init=False)

    def __post_init__(self):
        # 파생값이다. 인자로 못 넘기게 막아 note 와 어긋난 Release 를 만들 수 없게 한다.
        object.__setattr__(self, "released", _released(self.note))


def load_releases(path) -> dict[tuple[str, str], Release]:
    """표를 {(project, version): Release} 로. 파일·표가 없으면 빈 dict."""
    text = _read(path)
    if not text:
        return {}

    found: dict[tuple[str, str], Release] = {}
    for block in _tables(text):
        columns = _columns(block[0])
        if not columns:
            continue
        for row in block[1:]:
            release = _release(row, columns)
            if release is None:
                continue
            found.setdefault((release.project, release.version), release)
    return found


def parse_fix_version(raw) -> tuple[str, str] | None:
    """Jira fixVersion 문자열 → (프로젝트, 버전). 판단이 안 서면 None."""
    if not isinstance(raw, str):
        return None
    match = FIX_VERSION_RE.match(raw.strip())
    if not match:
        return None
    return match.group(1).lower(), match.group(2)


# ---------------------------------------------------------------------------
# 표 스캔
# ---------------------------------------------------------------------------

def _read(path) -> str:
    """읽기 실패는 빈 문자열. iCloud 미동기화·디렉토리·권한 전부 포함."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _tables(text) -> list[list[list[str]]]:
    """연속한 파이프 줄을 표 블록으로 묶는다. 코드펜스 안은 건너뛴다."""
    blocks = []
    current: list[list[str]] = []
    fence = None
    for line in text.split("\n"):
        stripped = line.strip()
        match = FENCE_RE.match(stripped)
        if match:
            if fence is None:
                fence = match.group(1)
            elif stripped.startswith(fence):
                fence = None
            current = _flush(blocks, current)
            continue
        if fence is not None:
            continue
        if not stripped.startswith("|"):
            current = _flush(blocks, current)
            continue
        if SEPARATOR_RE.match(stripped):
            continue  # |---|---| 는 데이터가 아니다
        current.append(_cells(stripped))
    _flush(blocks, current)
    return blocks


def _flush(blocks, current):
    if len(current) >= 2:  # 헤더 + 최소 1행. 헤더만 있는 표는 빈 표다.
        blocks.append(current)
    return []


def _cells(line) -> list[str]:
    inner = line.strip().strip("|")
    return [_clean(cell) for cell in inner.split("|")]


def _clean(cell) -> str:
    return cell.replace("`", "").replace("**", "").replace("*", "").strip()


def _columns(header) -> dict[str, int]:
    """헤더 셀에서 역할→인덱스. 프로젝트·버전이 없으면 릴리즈 표가 아니다."""
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        role = _role(cell)
        if role and role not in columns:
            columns[role] = index
    if any(role not in columns for role in _REQUIRED):
        return {}
    if "qa_start" not in columns and "prod_deploy" not in columns:
        return {}
    return columns


def _role(cell) -> str | None:
    lowered = cell.lower()
    for role, needles in _ROLES:
        if any(needle in lowered for needle in needles):
            return role
    return None


# ---------------------------------------------------------------------------
# 행 파싱
# ---------------------------------------------------------------------------

def _release(row, columns) -> Release | None:
    project = _cell(row, columns.get("project")).lower()
    version = _version(_cell(row, columns.get("version")))
    if not project or not version:
        return None
    return Release(
        project=project,
        version=version,
        qa_start=_date(_cell(row, columns.get("qa_start"))),
        prod_deploy=_date(_cell(row, columns.get("prod_deploy"))),
        note=_cell(row, columns.get("note")),
    )


def _cell(row, index) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def _version(value) -> str:
    """`v3.3.0` 를 `3.3.0` 으로. fixVersion 파싱 결과와 키를 맞춘다."""
    value = value.strip()
    if value[:1] in ("v", "V") and value[1:2].isdigit():
        return value[1:]
    return value


def _released(note) -> bool:
    """`비고` 가 배포 완료를 말하는지. 모르면 False — 조용해지는 쪽을 기본값으로 두지 않는다."""
    lowered = str(note or "").lower()
    if any(word in lowered for word in _NOT_RELEASED_WORDS):
        return False
    return any(word in lowered for word in _RELEASED_WORDS)


def _date(value) -> date | None:
    match = DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None  # 2026-13-45 같은 값은 모르는 것으로 둔다
