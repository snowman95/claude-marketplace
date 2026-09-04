import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def test_scan_prefers_frontmatter_jira_key(tmp_path):
    write(
        tmp_path / "myproject/tasks/shop3.3.0/cart-note.md",
        "---\njira_key: CWEB-1547\njira_status: \"개발 준비\"\n---\n\n# 본문\n",
    )
    got = vault.scan(tmp_path)
    assert set(got) == {"CWEB-1547"}
    assert got["CWEB-1547"] == [tmp_path / "myproject/tasks/shop3.3.0/cart-note.md"]


def test_scan_falls_back_to_filename_when_no_jira_key(tmp_path):
    write(
        tmp_path / "myproject/tasks/qa/WPQ-17415-share.md",
        "---\nfix_version: \"shop3.2.0\"\n---\n\n# 공유용\n",
    )
    write(tmp_path / "myproject/tasks/qa/WPQ-17415.md", "# 제목만 있는 문서\n")
    got = vault.scan(tmp_path)
    assert set(got) == {"WPQ-17415"}
    assert len(got["WPQ-17415"]) == 2


def test_scan_returns_absolute_paths(tmp_path):
    write(tmp_path / "p/tasks/v/CWEB-1.md", "---\njira_key: CWEB-1\n---\n")
    for paths in vault.scan(tmp_path).values():
        for p in paths:
            assert p.is_absolute()


def test_scan_same_key_in_two_projects(tmp_path):
    a = write(
        tmp_path / "myproject/tasks/shop3.3.0/CWEB-1548.md",
        "---\njira_key: CWEB-1548\n---\n",
    )
    b = write(
        tmp_path / "myproject_admin/tasks/shop3.3.0/CWEB-1548.md",
        "---\njira_key: CWEB-1548\n---\n",
    )
    got = vault.scan(tmp_path)
    assert sorted(got["CWEB-1548"]) == sorted([a, b])


def test_scan_ignores_md_outside_tasks(tmp_path):
    write(tmp_path / "myproject/modules/CWEB-9.md", "---\njira_key: CWEB-9\n---\n")
    write(tmp_path / "myproject/tasks/CWEB-8.md", "---\njira_key: CWEB-8\n---\n")
    assert set(vault.scan(tmp_path)) == {"CWEB-8"}


def test_scan_skips_unreadable_files_without_raising(tmp_path):
    write(tmp_path / "p/tasks/v/CWEB-1.md", "---\njira_key: CWEB-1\n---\n")
    # 클라우드에만 있어 읽기가 실패하는 파일을 흉내낸다 (디렉토리 → IsADirectoryError).
    (tmp_path / "p/tasks/v/CWEB-9999.md").mkdir(parents=True)
    unreadable = write(tmp_path / "p/tasks/v/CWEB-8888.md", "---\njira_key: CWEB-8888\n---\n")
    unreadable.chmod(0o000)
    try:
        got = vault.scan(tmp_path)
    finally:
        unreadable.chmod(0o644)
    assert "CWEB-1" in got
    assert "CWEB-9999" not in got
    assert "CWEB-8888" not in got


def test_scan_empty_vault(tmp_path):
    assert vault.scan(tmp_path) == {}


# --------------------------------------------------------------------------
# primary_mds
# --------------------------------------------------------------------------

def test_primary_mds_exact_stem_only(tmp_path):
    paths = [
        tmp_path / "a/tasks/WPQ-17415.md",
        tmp_path / "a/tasks/WPQ-17415-share.md",
        tmp_path / "a/tasks/WPQ-17415-errorcode-audit.md",
    ]
    assert vault.primary_mds("WPQ-17415", paths) == [paths[0]]


def test_primary_mds_keeps_all_exact_matches(tmp_path):
    paths = [
        tmp_path / "myproject/tasks/shop3.3.0/CWEB-1548.md",
        tmp_path / "myproject_admin/tasks/shop3.3.0/CWEB-1548.md",
        tmp_path / "myproject/tasks/shop3.3.0/CWEB-1548-report.md",
    ]
    assert vault.primary_mds("CWEB-1548", paths) == paths[:2]


def test_primary_mds_none_matching(tmp_path):
    assert vault.primary_mds("WPQ-1", [tmp_path / "a/tasks/WPQ-1-share.md"]) == []


# --------------------------------------------------------------------------
# read_frontmatter
# --------------------------------------------------------------------------

FM = """---
jira_key: CWEB-1547
fix_version: "shop3.3.0"
jira_status: "개발 준비"
blocked: true
url: https://your-site.atlassian.net/browse/CWEB-1547
related_tickets: ["WWSP-1816", "WWSP-1813"]
---

# 제목

## 변경 히스토리
"""


def test_read_frontmatter_basic_keys(tmp_path):
    fm = vault.read_frontmatter(write(tmp_path / "CWEB-1547.md", FM))
    assert fm["jira_key"] == "CWEB-1547"
    assert fm["fix_version"] == "shop3.3.0"
    assert fm["jira_status"] == "개발 준비"
    assert fm["url"] == "https://your-site.atlassian.net/browse/CWEB-1547"


def test_read_frontmatter_blocked_is_bool(tmp_path):
    fm = vault.read_frontmatter(write(tmp_path / "a.md", FM))
    assert fm["blocked"] is True

    fm2 = vault.read_frontmatter(
        write(tmp_path / "b.md", "---\njira_key: X-1\nblocked: false\n---\n")
    )
    assert fm2["blocked"] is False


def test_read_frontmatter_no_frontmatter(tmp_path):
    assert vault.read_frontmatter(write(tmp_path / "c.md", "# 제목만\n")) == {}


def test_read_frontmatter_unreadable_returns_empty(tmp_path):
    missing = tmp_path / "nope.md"
    assert vault.read_frontmatter(missing) == {}


# --------------------------------------------------------------------------
# read_links
# --------------------------------------------------------------------------

LINKS_MD = """---
jira_key: CWEB-1547
blocked: true
links:
  confluence:
    - id: "5919834330"
      url: https://your-site.atlassian.net/wiki/spaces/W/pages/5919834330
      title: 장바구니 쿠폰 기획서
      version: 12                          # 변경 감지 키
      local: docs/W/장바구니 쿠폰 기획서.md   # docs-pull 산출물
    - id: "5941952582"
      url: https://your-site.atlassian.net/wiki/spaces/fanVoice/pages/5941952582
      title: E9 API 명세
      version: 7
  figma:
    - file_key: LU01ZBqK0wEA930576PjLm
      node_id: "8604-39330"
      name: 샵_장바구니
      last_modified: 2026-08-20T04:11:00Z
    - file_key: AbC123
      node_id: "1-2"
      name: 두번째 파일
      last_modified: 2026-08-29T01:00:00Z
qa_tickets: [WPQ-17801]
---

# 제목
"""


def test_read_links_absent_returns_two_empty_lists(tmp_path):
    got = vault.read_links(write(tmp_path / "a.md", FM))
    assert got == {"confluence": [], "figma": []}


def test_read_links_no_frontmatter_at_all(tmp_path):
    got = vault.read_links(write(tmp_path / "b.md", "# 제목만\n"))
    assert got == {"confluence": [], "figma": []}


def test_read_links_parses_multiple_entries(tmp_path):
    got = vault.read_links(write(tmp_path / "CWEB-1547.md", LINKS_MD))
    assert len(got["confluence"]) == 2
    assert len(got["figma"]) == 2

    first = got["confluence"][0]
    assert first["id"] == "5919834330"
    assert first["url"].endswith("/pages/5919834330")
    assert first["title"] == "장바구니 쿠폰 기획서"
    assert first["version"] == 12
    assert first["local"] == "docs/W/장바구니 쿠폰 기획서.md"
    assert got["confluence"][1]["id"] == "5941952582"
    assert got["confluence"][1]["version"] == 7

    fig = got["figma"][0]
    assert fig["file_key"] == "LU01ZBqK0wEA930576PjLm"
    assert fig["node_id"] == "8604-39330"
    assert fig["name"] == "샵_장바구니"
    assert fig["last_modified"] == "2026-08-20T04:11:00Z"
    assert got["figma"][1]["file_key"] == "AbC123"


def test_read_links_version_is_int_and_ids_are_str(tmp_path):
    got = vault.read_links(write(tmp_path / "a.md", LINKS_MD))
    for item in got["confluence"]:
        assert isinstance(item["version"], int)
        assert isinstance(item["id"], str)


def test_read_links_only_one_kind(tmp_path):
    md = write(
        tmp_path / "a.md",
        "---\njira_key: X-1\nlinks:\n  figma:\n    - file_key: K\n      node_id: \"1-2\"\n"
        "      name: n\n      last_modified: 2026-01-01T00:00:00Z\n---\n\n# t\n",
    )
    got = vault.read_links(md)
    assert got["confluence"] == []
    assert len(got["figma"]) == 1


def test_read_frontmatter_exposes_links(tmp_path):
    fm = vault.read_frontmatter(write(tmp_path / "a.md", LINKS_MD))
    assert len(fm["links"]["confluence"]) == 2
    assert fm["blocked"] is True


# --------------------------------------------------------------------------
# append_history
# --------------------------------------------------------------------------

WITH_HISTORY = """---
jira_key: CWEB-1547
blocked: true
---

# [shop] 커머스 쿠폰

## 결정 사항 (Decision Log)

### D-01. `groupKey`
**결정일** 2026-08-18

## 변경 히스토리

> `poll.py`가 자동 append. 항목을 삭제하지 않는다.
> `⚠️`는 판단이 필요하다는 뜻이며, 처리하면 줄 끝에 결과를 덧붙인다.

- `09-02 14:07` **status** 개발 준비 → 진행 중

## 문의·Blocked

전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` 에서 관리한다.
"""

WITHOUT_HISTORY = """---
jira_key: CWEB-1548
blocked: true
---

# [shop admin] 커머스 쿠폰

## 남은 작업 (회신 후)
- [ ] Q13 확정 시 반영

## 문의·Blocked

전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` C군에서 관리한다.
"""

NO_BLOCKED_SECTION = """---
jira_key: WWSP-1820
---

# 공통 컨텍스트

## Plan

내용.
"""

NEW_LINE = "- `09-04 14:07` **status** 개발 준비 → 진행 중"
NEW_LINE2 = "- `09-04 14:07` ⚠️ **Confluence** `5919834330` v12 → v13"


def test_append_history_appends_to_existing_section(tmp_path):
    md = write(tmp_path / "CWEB-1547.md", WITH_HISTORY)
    assert vault.append_history(md, [NEW_LINE, NEW_LINE2]) is True

    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    hist = lines.index(vault.HISTORY_HEADER)
    blocked = lines.index(vault.BLOCKED_HEADER)

    # 기존 항목이 남고, 새 줄이 섹션 안 · Blocked 앞에 들어간다
    assert "- `09-02 14:07` **status** 개발 준비 → 진행 중" in lines
    assert hist < lines.index(NEW_LINE) < blocked
    assert hist < lines.index(NEW_LINE2) < blocked
    assert lines.index(NEW_LINE) < lines.index(NEW_LINE2)


def test_append_history_preserves_following_section(tmp_path):
    md = write(tmp_path / "CWEB-1547.md", WITH_HISTORY)
    vault.append_history(md, [NEW_LINE])
    text = md.read_text(encoding="utf-8")

    assert vault.BLOCKED_HEADER in text
    assert "전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` 에서 관리한다." in text
    assert "## 결정 사항 (Decision Log)" in text
    assert "### D-01. `groupKey`" in text
    assert "**결정일** 2026-08-18" in text


def test_append_history_does_not_duplicate_guide_blockquote(tmp_path):
    md = write(tmp_path / "CWEB-1547.md", WITH_HISTORY)
    vault.append_history(md, [NEW_LINE])
    text = md.read_text(encoding="utf-8")
    assert text.count("`poll.py`가 자동 append") == 1


def test_append_history_creates_section_before_blocked(tmp_path):
    md = write(tmp_path / "CWEB-1548.md", WITHOUT_HISTORY)
    assert vault.append_history(md, [NEW_LINE]) is True

    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    hist = lines.index(vault.HISTORY_HEADER)
    blocked = lines.index(vault.BLOCKED_HEADER)
    assert hist < blocked

    guide = [
        "> `poll.py`가 자동 append. 항목을 삭제하지 않는다.",
        "> `⚠️`는 판단이 필요하다는 뜻이며, 처리하면 줄 끝에 결과를 덧붙인다.",
    ]
    assert guide[0] in lines and guide[1] in lines
    assert lines.index(guide[0]) + 1 == lines.index(guide[1])
    assert hist < lines.index(guide[0]) < lines.index(NEW_LINE) < blocked

    # 앞뒤 섹션이 그대로 살아있다
    assert "## 남은 작업 (회신 후)" in text
    assert "- [ ] Q13 확정 시 반영" in text
    assert "전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` C군에서 관리한다." in text


def test_append_history_appends_at_eof_when_no_blocked_section(tmp_path):
    md = write(tmp_path / "WWSP-1820.md", NO_BLOCKED_SECTION)
    assert vault.append_history(md, [NEW_LINE]) is True

    text = md.read_text(encoding="utf-8")
    lines = text.rstrip("\n").split("\n")
    assert vault.BLOCKED_HEADER not in text
    assert lines.index(vault.HISTORY_HEADER) > lines.index("## Plan")
    assert lines[-1] == NEW_LINE
    assert "내용." in text
    assert "`poll.py`가 자동 append" in text


def test_append_history_dry_run_does_not_touch_file(tmp_path):
    for name, body in (
        ("a.md", WITH_HISTORY),
        ("b.md", WITHOUT_HISTORY),
        ("c.md", NO_BLOCKED_SECTION),
    ):
        md = write(tmp_path / name, body)
        before = md.read_bytes()
        assert vault.append_history(md, [NEW_LINE, NEW_LINE2], dry_run=True) is True
        assert md.read_bytes() == before


def test_append_history_no_duplicate_trailing_newline(tmp_path):
    for name, body in (
        ("a.md", WITH_HISTORY),
        ("b.md", WITHOUT_HISTORY),
        ("c.md", NO_BLOCKED_SECTION),
        ("d.md", NO_BLOCKED_SECTION.rstrip("\n")),
        ("e.md", NO_BLOCKED_SECTION + "\n\n\n"),
    ):
        md = write(tmp_path / name, body)
        vault.append_history(md, [NEW_LINE])
        text = md.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert not text.endswith("\n\n")


def test_append_history_empty_lines_is_noop(tmp_path):
    md = write(tmp_path / "a.md", WITH_HISTORY)
    before = md.read_bytes()
    assert vault.append_history(md, []) is False
    assert md.read_bytes() == before


def test_append_history_twice_keeps_order_and_content(tmp_path):
    md = write(tmp_path / "CWEB-1548.md", WITHOUT_HISTORY)
    vault.append_history(md, [NEW_LINE])
    vault.append_history(md, [NEW_LINE2])
    lines = md.read_text(encoding="utf-8").split("\n")
    assert lines.index(NEW_LINE) < lines.index(NEW_LINE2) < lines.index(vault.BLOCKED_HEADER)


def test_append_history_ignores_headings_inside_code_fence(tmp_path):
    body = (
        "---\njira_key: X-1\n---\n\n# 제목\n\n"
        + vault.HISTORY_HEADER
        + "\n\n- `09-01 10:07` **status** a → b\n\n"
        + "```markdown\n## 문의·Blocked\n```\n\n"
        + vault.BLOCKED_HEADER
        + "\n\n진짜 blocked 본문.\n"
    )
    md = write(tmp_path / "X-1.md", body)
    vault.append_history(md, [NEW_LINE])
    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert "```markdown" in lines
    assert "진짜 blocked 본문." in lines
    # 코드펜스 안의 헤더를 진짜 섹션으로 오인하지 않는다
    assert text.count(vault.BLOCKED_HEADER) == 2
    real_blocked = len(lines) - 1 - lines[::-1].index(vault.BLOCKED_HEADER)
    assert lines.index(vault.HISTORY_HEADER) < lines.index(NEW_LINE) < real_blocked
    # 섹션이 이미 있으므로 안내 blockquote를 새로 만들지 않는다
    assert "`poll.py`가 자동 append" not in text


def test_append_history_missing_file_returns_false(tmp_path):
    assert vault.append_history(tmp_path / "nope.md", [NEW_LINE]) is False


def test_append_history_preserves_file_mode(tmp_path):
    md = write(tmp_path / "a.md", WITH_HISTORY)
    md.chmod(0o644)
    vault.append_history(md, [NEW_LINE])
    assert md.stat().st_mode & 0o777 == 0o644


def test_append_history_refuses_non_utf8_file(tmp_path):
    md = tmp_path / "broken.md"
    body = (WITH_HISTORY.encode("utf-8")).replace(b"\xea\xb0\x9c", b"\xff\xfe")
    md.write_bytes(body)
    assert vault.append_history(md, [NEW_LINE]) is False
    assert md.read_bytes() == body


def test_scan_still_reads_non_utf8_file(tmp_path):
    md = tmp_path / "p/tasks/CWEB-7.md"
    md.parent.mkdir(parents=True)
    md.write_bytes(b"---\njira_key: CWEB-7\nsummary: \xff\xfe\n---\n")
    assert "CWEB-7" in vault.scan(tmp_path)
