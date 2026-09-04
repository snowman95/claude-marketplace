"""vault 스캐너 · 티켓 md 프론트매터 리더 · `## 변경 히스토리` 안전 append.

손으로 쓴 노트를 건드리므로 파괴적 동작을 하지 않는 것이 최우선이다.
- 읽기는 전부 실패 허용(iCloud 미동기화 파일 skip).
- 쓰기는 append 전용. 기존 줄을 지우거나 재배치하지 않는다.
- 외부 yaml 의존 없이 필요한 키만 파싱한다.
"""

import os
import re
import tempfile
from pathlib import Path

HISTORY_HEADER = "## 변경 히스토리"
BLOCKED_HEADER = "## 문의·Blocked"

HISTORY_GUIDE = [
    "> `poll.py`가 자동 append. 항목을 삭제하지 않는다.",
    "> `⚠️`는 판단이 필요하다는 뜻이며, 처리하면 줄 끝에 결과를 덧붙인다.",
]

KEY_RE = re.compile(r"^([A-Z][A-Z0-9]+-\d+)")
FENCE_RE = re.compile(r"^(```|~~~)")
HEADING_RE = re.compile(r"^#{1,2} ")

CONFLUENCE_FIELDS = ("id", "url", "title", "version", "local")
FIGMA_FIELDS = ("file_key", "node_id", "name", "last_modified")


# ---------------------------------------------------------------------------
# 스캔
# ---------------------------------------------------------------------------

def scan(vault):
    """vault 하위 티켓 md를 훑어 {jira_key: [절대경로, ...]} 를 만든다."""
    vault = Path(vault)
    result = {}
    for path in sorted(vault.glob("*/tasks/**/*.md")):
        text = _read_text(path)
        if text is None:
            continue
        key = _key_for(path, text)
        if not key:
            continue
        result.setdefault(key, []).append(path if path.is_absolute() else path.resolve())
    return result


def primary_mds(key, paths):
    """stem 이 key 와 정확히 일치하는 것만. 보조 문서(-share 등)는 제외."""
    return [p for p in paths if Path(p).stem == key]


def _key_for(path, text):
    key = _scalar(_frontmatter_raw(text).get("jira_key", ""))
    if isinstance(key, str) and key.strip():
        return key.strip()
    match = KEY_RE.match(path.stem)
    return match.group(1) if match else None


def _read_text(path):
    """읽기 실패는 None. 클라우드에만 있는 파일·권한 문제 전부 포함.

    스캔·조회용이라 깨진 바이트는 치환해서라도 읽는다.
    """
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _read_text_strict(path):
    """되쓰기(append) 전용. 치환이 일어나면 원본이 손상되므로 실패로 본다."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 프론트매터
# ---------------------------------------------------------------------------

def read_frontmatter(md):
    text = _read_text(md)
    if text is None:
        return {}
    raw = _frontmatter_raw(text)
    parsed = {}
    for key, value in raw.items():
        if key == "links":
            continue
        parsed[key] = _scalar(value) if isinstance(value, str) else value
    links = raw.get("links")
    if isinstance(links, list):
        parsed["links"] = _parse_links_block(links)
    return parsed


def read_links(md):
    links = read_frontmatter(md).get("links")
    if not isinstance(links, dict):
        return {"confluence": [], "figma": []}
    return links


def _frontmatter_lines(text):
    """맨 앞 `---` … `---` 사이 줄. 없으면 빈 리스트."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return lines[1:i]
    return []


def _frontmatter_raw(text):
    """최상위 키만 뽑는다. 값은 스칼라 문자열, 중첩 블록은 하위 줄 리스트."""
    raw = {}
    lines = _frontmatter_lines(text)
    current = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            if isinstance(current, list):
                current.append(line)
            continue
        if line[:1].isspace() or line.lstrip().startswith("- "):
            if isinstance(current, list):
                current.append(line)
            continue
        key, sep, value = line.partition(":")
        if not sep:
            current = None
            continue
        key = key.strip()
        if value.strip():
            raw[key] = value
            current = None
        else:
            current = []
            raw[key] = current
    return raw


def _parse_links_block(block):
    """links: 하위 블록 → {"confluence": [...], "figma": [...]}"""
    result = {"confluence": [], "figma": []}
    kind = None
    item = None
    for line in block:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("confluence:", "figma:"):
            kind = stripped[:-1]
            item = None
            continue
        if kind is None:
            continue
        if stripped.startswith("- "):
            item = {}
            result[kind].append(item)
            stripped = stripped[2:].strip()
            if not stripped:
                continue
        elif stripped == "-":
            item = {}
            result[kind].append(item)
            continue
        if item is None:
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        item[key.strip()] = _scalar(value)
    return {
        "confluence": [_normalize(i, CONFLUENCE_FIELDS) for i in result["confluence"]],
        "figma": [_normalize(i, FIGMA_FIELDS) for i in result["figma"]],
    }


def _normalize(item, fields):
    out = {}
    for field in fields:
        value = item.get(field)
        if field == "version":
            out[field] = value if isinstance(value, int) and not isinstance(value, bool) else _to_int(value)
        elif value is None:
            out[field] = ""
        elif isinstance(value, str):
            out[field] = value
        else:
            out[field] = str(value)
    return out


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _scalar(value):
    """따옴표·인라인 주석·불리언·정수·인라인 리스트만 다루는 최소 파서."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end != -1:
            return text[1:end]
        return text[1:]
    text = re.split(r"\s+#", text, maxsplit=1)[0].strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


# ---------------------------------------------------------------------------
# 히스토리 append
# ---------------------------------------------------------------------------

def append_history(md, lines, dry_run=False):
    """`## 변경 히스토리` 섹션에 lines 를 append. 기존 내용은 절대 건드리지 않는다."""
    entries = [line for line in (lines or []) if line is not None]
    if not entries:
        return False

    md = Path(md)
    text = _read_text_strict(md)
    if text is None:
        return False
    if dry_run:
        return True

    doc = text.split("\n")
    headings = _heading_indices(doc)
    history_idx = _find_heading(doc, headings, HISTORY_HEADER)

    if history_idx is not None:
        end = _section_end(headings, history_idx, len(doc))
        insert_at = end
        while insert_at > history_idx + 1 and not doc[insert_at - 1].strip():
            insert_at -= 1
        new_doc = doc[:insert_at] + list(entries) + doc[insert_at:]
    else:
        block = [HISTORY_HEADER, ""] + HISTORY_GUIDE + [""] + list(entries)
        blocked_idx = _find_heading(doc, headings, BLOCKED_HEADER)
        if blocked_idx is not None:
            new_doc = doc[:blocked_idx] + block + [""] + doc[blocked_idx:]
        else:
            body = list(doc)
            while body and not body[-1].strip():
                body.pop()
            new_doc = body + [""] + block

    _write_atomic(md, _one_trailing_newline("\n".join(new_doc)))
    return True


def _heading_indices(doc):
    """코드펜스·프론트매터를 제외한 `#`/`##` 헤더 줄 인덱스."""
    start = 0
    if doc and doc[0].strip() == "---":
        for i in range(1, len(doc)):
            if doc[i].strip() in ("---", "..."):
                start = i + 1
                break
    indices = []
    fence = None
    for i in range(start, len(doc)):
        line = doc[i]
        match = FENCE_RE.match(line.strip())
        if match:
            if fence is None:
                fence = match.group(1)
            elif line.strip().startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if HEADING_RE.match(line):
            indices.append(i)
    return indices


def _find_heading(doc, headings, header):
    for i in headings:
        if doc[i].strip() == header:
            return i
    return None


def _section_end(headings, start, total):
    for i in headings:
        if i > start:
            return i
    return total


def _one_trailing_newline(text):
    return text.rstrip("\n") + "\n"


def _write_atomic(path, text):
    directory = path.parent
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
