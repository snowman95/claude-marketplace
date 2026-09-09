"""브리핑 `### 결정` 섹션의 회신 파서.

Slack 봇은 `chat:write`·`im:write` 뿐이라 **발신 전용**이다 — 스레드 답글을 읽을
수 없다. 그래서 결정 회신은 브리핑 파일(`{vault}/daily/YYYY-MM-DD.md`)의
`↳ 답:` 줄이 **유일한 경로**다. 이 모듈은 그 줄만 읽는다.

두 가지를 지킨다.
- **읽기 전용.** 파일을 쓰지 않는다. 기록은 `decision-apply` 스킬이 한다.
- **예외를 던지지 않는다.** 파일 없음·섹션 없음·깨진 인코딩은 빈 리스트다.
  폴링이 매시 돌기 때문에, 손으로 쓴 한 줄의 표기 때문에 폴링이 죽으면 안 된다.

표기가 흔들리는 것을 전제한다. 정본은 `↳ 답:`(U+21B3)이지만 폰에서 화살표를
찾지 못해 `-> 답:`·`→ 답:` 을 쓰는 일이 실제로 생긴다. 셋 다 받는다.
판단이 서지 않으면 **미응답으로 두는 쪽**을 택한다 — 없는 결정을 기록하는 것보다
놓치는 게 싸다.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# `### 결정` 이 정본. `## 결정` 도 받되 `## 결정 사항 (Decision Log)` 같은
# 다른 섹션까지 물지 않도록 제목이 정확히 `결정` 인 헤더만 본다.
SECTION_RE = re.compile(r"^#{2,4}\s+결정\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s")
ITEM_RE = re.compile(r"^ {0,3}(\d{1,3})\.\s+(.*)$")

# `↳`(U+21B3) 가 정본. `→`(U+2192)·`->` 는 폰에서 손으로 쓸 때의 현실.
ANSWER_RE = re.compile(r"^\s*(?:↳|→|->)\s*답\s*[:：]\s*(.*)$")

# `[[CWEB-1547]]`(Obsidian) 와 `<url|CWEB-1547>`(Slack mrkdwn) 두 형태.
TICKET_RE = re.compile(
    r"\[\[([A-Z][A-Z0-9]*-\d+)\]\]|<[^<>|]*\|([A-Z][A-Z0-9]*-\d+)>"
)

# `decision-apply` 가 답 줄 끝에 붙이는 처리 완료 마커. 답 내용의 일부가 아니다.
APPLIED_MARK = "✅"

HASH_LENGTH = 12


@dataclass(frozen=True)
class Decision:
    id: str      # "2026-09-04#2" — 날짜 + 항목 번호
    date: str
    index: int
    ticket: str  # 항목에서 추출한 티켓 키. 없으면 ""
    title: str   # 첫 줄에서 뽑은 제목 (마크다운 강조 제거)
    answer: str  # `↳ 답:` 뒤의 내용. 여러 줄이면 한 줄로 합친다. 비면 ""


def parse(md_path) -> list[Decision]:
    """브리핑 md 의 `### 결정` 항목을 전부 돌려준다. 실패하면 빈 리스트."""
    path = Path(md_path)
    lines = _read_lines(path)
    if not lines:
        return []
    block = _section(lines)
    if not block:
        return []
    day = path.stem
    return [_decision(day, number, item) for number, item in _items(block)]


def answered(decisions) -> list[Decision]:
    """답이 채워진 것만."""
    return [d for d in decisions or [] if d.answer.strip()]


def pending(decisions) -> list[Decision]:
    """아직 빈칸인 것만. 재촉하지 않고 개수만 세는 데 쓴다."""
    return [d for d in decisions or [] if not d.answer.strip()]


def hash_answer(answer) -> str:
    """답 내용의 sha256 앞 12자. 답이 수정되면 값이 바뀐다.

    **`↳ 답:` 뒤의 원문 그대로** 를 해시한다 — 이미 `_state.json["decisions"]` 에
    이 값으로 쌓인 기록이 있어서, 정규화한 값으로 바꾸면 과거 결정이 전부 새 답
    으로 되살아난다.
    """
    return _digest(str(answer or "").strip())


def normalize_answer(answer) -> str:
    """처리 완료 마커(`✅ …`)를 떼고 공백을 정규화한 답 내용.

    `decision-apply` 는 처리한 답 줄 끝에 `✅ D-03 기록` 을 붙인다. 그 마커는
    답의 일부가 아닌데 `hash_answer` 는 원문을 해시하므로, 마커가 붙는 순간 답이
    수정된 것처럼 보인다 — 그대로 두면 폴링이 같은 결정을 한 번 더 접수하고
    스킬을 한 번 더 띄운다. 그 한 바퀴를 죽이는 게 이 함수다.
    """
    text = str(answer or "")
    head = text.split(APPLIED_MARK, 1)[0]
    return " ".join(head.split())


def answer_key(answer) -> str:
    """마커·공백에 흔들리지 않는 비교 키. 내용이 비면 "" (판정에 쓰지 않는다).

    답이 마커뿐인 병적인 경우에 모든 답이 같은 키를 갖는 것을 막는다.
    """
    normalized = normalize_answer(answer)
    return _digest(normalized) if normalized else ""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LENGTH]


# ---------------------------------------------------------------------------
# 내부
# ---------------------------------------------------------------------------

def _read_lines(path: Path):
    try:
        return path.read_text(encoding="utf-8").split("\n")
    except (OSError, ValueError, UnicodeDecodeError):
        return []


def _section(lines):
    """첫 `### 결정` 섹션의 줄들. 다음 헤더 전까지. 없으면 빈 리스트."""
    start = next(
        (i for i, line in enumerate(lines) if SECTION_RE.match(line.rstrip())), None
    )
    if start is None:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if HEADING_RE.match(lines[i])),
        len(lines),
    )
    return lines[start + 1:end]


def _items(block):
    """(번호, 줄들). 번호 항목 앞의 안내 blockquote 등은 버린다."""
    items = []
    for line in block:
        match = ITEM_RE.match(line)
        if match:
            items.append((int(match.group(1)), [match.group(2)]))
        elif items:
            items[-1][1].append(line)
    return items


def _decision(day, number, lines) -> Decision:
    return Decision(
        id=f"{day}#{number}",
        date=day,
        index=number,
        ticket=_ticket(lines),
        title=_strip_emphasis(lines[0] if lines else ""),
        answer=_answer(lines),
    )


def _ticket(lines):
    match = TICKET_RE.search("\n".join(lines))
    if not match:
        return ""
    return match.group(1) or match.group(2) or ""


def _answer(lines):
    """`↳ 답:` 뒤의 내용. 이어지는 들여쓴 줄을 한 줄로 합친다."""
    start = next((i for i, line in enumerate(lines) if ANSWER_RE.match(line)), None)
    if start is None:
        return ""
    parts = [ANSWER_RE.match(lines[start]).group(1).strip()]
    for line in lines[start + 1:]:
        if not line.strip():
            continue  # 빈 줄은 항목의 끝이 아니다 — 답이 끊기지 않는다
        if not line[:1].isspace() or ANSWER_RE.match(line):
            break  # 들여쓰지 않은 줄·다음 답 줄은 이 답이 아니다
        parts.append(line.strip())
    return " ".join(part for part in parts if part).strip()


def _strip_emphasis(text):
    """제목에서 마크다운 강조만 벗긴다. 링크·코드는 그대로 둔다."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text))
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    return text.replace("**", "").strip()
