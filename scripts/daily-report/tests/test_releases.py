"""releases.md 파서 테스트.

이 파일은 **사람이 관리한다.** 파서는 읽기만 하고, 어떤 입력에도 예외를
던지지 않으며, 모르는 값은 None 으로 남긴다. 표를 못 읽어서 감시가 죽는 것보다
경보가 없는 게 낫다.
"""

import textwrap
from datetime import date

import pytest

import releases as rel

REAL = """\
---
title: 릴리즈 일정
note: 사람이 직접 관리한다. 자동화는 읽기만 하고 덮어쓰지 않는다.
---

# 릴리즈 일정

> Jira 프로젝트 버전에서 가져온 초안. **빈 칸은 Jira에도 없다** — 직접 채워라.
> 브리핑 하단이 이 표를 읽는다. 비어 있으면 `모름` 으로 표시된다.

| 프로젝트 | 버전     | QA 시작      | prod 배포    | 비고   |
| ---- | ------ | ---------- | ---------- | ---- |
| shop | 3.1.3  |            |            | 배포완료 |
| shop | 3.2.0  | 2026-08-10 | 2026-09-03 | 배포완료 |
| shop | 3.3.0  | 2026-09-14 | 2026-10-07 | 개발중  |
| oms  | 1.14.0 |            | 2026-08-06 |      |

## 프로젝트 표기

| 표기 | 무엇 | Jira 버전 접두사 |
|---|---|---|
| `shop` | 위버스샵 프론트 | `shop` |
| `oms` | 주문관리 | `oms` |
"""


def write(tmp_path, body, name="releases.md"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_fix_version
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("shop3.3.0", ("shop", "3.3.0")),
        ("oms1.14.0", ("oms", "1.14.0")),
        ("shop2.18.0", ("shop", "2.18.0")),
        ("SHOP3.3.0", ("shop", "3.3.0")),
        ("  shop3.3.0  ", ("shop", "3.3.0")),
        ("shop-3.3.0", ("shop", "3.3.0")),
        ("shop 3.3.0", ("shop", "3.3.0")),
        ("shop_3.3.0", ("shop", "3.3.0")),
        ("shopv3.3.0", ("shop", "3.3.0")),
        ("shop3.3", ("shop", "3.3")),
    ],
)
def test_parse_fix_version_accepts(raw, expected):
    assert rel.parse_fix_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "3.3.0",          # 프로젝트 접두사 없음
        "shop",           # 버전 없음
        "shop3",          # 점 없는 단일 숫자는 버전으로 보지 않는다
        "backlog",
        "26.10 (v.3.20.0)",
        "shop3.3.0-rc1",  # 꼬리표가 붙으면 판단하지 않는다
        [],
        42,
    ],
)
def test_parse_fix_version_rejects(raw):
    assert rel.parse_fix_version(raw) is None


# ---------------------------------------------------------------------------
# load_releases — 없음 / 빈 표 / 못 읽음
# ---------------------------------------------------------------------------

def test_missing_file_is_empty(tmp_path):
    assert rel.load_releases(tmp_path / "nope.md") == {}


def test_directory_instead_of_file_is_empty(tmp_path):
    assert rel.load_releases(tmp_path) == {}


def test_file_without_any_table_is_empty(tmp_path):
    path = write(tmp_path, "# 릴리즈 일정\n\n아직 표가 없다.\n")
    assert rel.load_releases(path) == {}


def test_header_only_table_is_empty(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        | --- | --- | --- | --- | --- |
        """,
    )
    assert rel.load_releases(path) == {}


def test_empty_file_is_empty(tmp_path):
    assert rel.load_releases(write(tmp_path, "")) == {}


def test_unrelated_table_is_ignored(tmp_path):
    path = write(
        tmp_path,
        """
        | 표기 | 무엇 | Jira 버전 접두사 |
        |---|---|---|
        | `shop` | 위버스샵 프론트 | `shop` |
        """,
    )
    assert rel.load_releases(path) == {}


# ---------------------------------------------------------------------------
# load_releases — 실제 파일 형태
# ---------------------------------------------------------------------------

def test_parses_the_real_shape(tmp_path):
    found = rel.load_releases(write(tmp_path, REAL))

    assert set(found) == {
        ("shop", "3.1.3"),
        ("shop", "3.2.0"),
        ("shop", "3.3.0"),
        ("oms", "1.14.0"),
    }
    r = found[("shop", "3.2.0")]
    assert (r.project, r.version) == ("shop", "3.2.0")
    assert r.qa_start == date(2026, 8, 10)
    assert r.prod_deploy == date(2026, 9, 3)
    assert r.note == "배포완료"


def test_blank_cells_become_none(tmp_path):
    found = rel.load_releases(write(tmp_path, REAL))

    empty = found[("shop", "3.1.3")]
    assert empty.qa_start is None
    assert empty.prod_deploy is None
    assert empty.note == "배포완료"

    half = found[("oms", "1.14.0")]
    assert half.qa_start is None
    assert half.prod_deploy == date(2026, 8, 6)
    assert half.note == ""


def test_second_table_does_not_leak_rows(tmp_path):
    found = rel.load_releases(write(tmp_path, REAL))
    assert ("shop", "위버스샵 프론트") not in found
    assert all(key[0] in ("shop", "oms") for key in found)


def test_lookup_by_fix_version_round_trips(tmp_path):
    found = rel.load_releases(write(tmp_path, REAL))
    assert found[rel.parse_fix_version("shop3.3.0")].note == "개발중"


# ---------------------------------------------------------------------------
# load_releases — 파싱 불가 입력
# ---------------------------------------------------------------------------

def test_unparseable_dates_become_none(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 9.0.0 | 미정 | TBD | 확인중 |
        | shop | 9.1.0 | 2026-13-45 | 2026-02-30 | 말이 안 되는 날짜 |
        """,
    )
    found = rel.load_releases(path)

    assert found[("shop", "9.0.0")].qa_start is None
    assert found[("shop", "9.0.0")].prod_deploy is None
    assert found[("shop", "9.1.0")].qa_start is None
    assert found[("shop", "9.1.0")].prod_deploy is None


def test_decorated_dates_still_parse(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 9.0.0 | 2026-09-14(월) | **2026-10-07** | |
        | shop | 9.1.0 | 2026/09/14 | `2026.10.07` | |
        """,
    )
    found = rel.load_releases(path)

    assert found[("shop", "9.0.0")].qa_start == date(2026, 9, 14)
    assert found[("shop", "9.0.0")].prod_deploy == date(2026, 10, 7)
    assert found[("shop", "9.1.0")].qa_start == date(2026, 9, 14)
    assert found[("shop", "9.1.0")].prod_deploy == date(2026, 10, 7)


def test_rows_without_project_or_version_are_skipped(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        |  | 9.0.0 | 2026-09-14 | 2026-10-07 | 프로젝트 없음 |
        | shop |  | 2026-09-14 | 2026-10-07 | 버전 없음 |
        | shop | 9.2.0 | 2026-09-14 | 2026-10-07 | 정상 |
        """,
    )
    assert set(rel.load_releases(path)) == {("shop", "9.2.0")}


def test_short_rows_are_skipped_not_fatal(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop |
        | shop | 9.3.0 | 2026-09-14 | 2026-10-07 | 정상 |
        """,
    )
    assert set(rel.load_releases(path)) == {("shop", "9.3.0")}


def test_version_v_prefix_is_normalized(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | v9.4.0 | | 2026-10-07 | |
        """,
    )
    found = rel.load_releases(path)
    assert ("shop", "9.4.0") in found
    assert found[rel.parse_fix_version("shop9.4.0")].prod_deploy == date(2026, 10, 7)


def test_column_order_follows_the_header(tmp_path):
    path = write(
        tmp_path,
        """
        | 버전 | 프로젝트 | prod 배포 | QA 시작 | 비고 |
        |---|---|---|---|---|
        | 9.5.0 | shop | 2026-10-07 | 2026-09-14 | 뒤바뀐 순서 |
        """,
    )
    r = rel.load_releases(path)[("shop", "9.5.0")]
    assert r.qa_start == date(2026, 9, 14)
    assert r.prod_deploy == date(2026, 10, 7)


def test_table_without_note_column_gives_empty_note(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 |
        |---|---|---|---|
        | shop | 9.6.0 | 2026-09-14 | 2026-10-07 |
        """,
    )
    assert rel.load_releases(path)[("shop", "9.6.0")].note == ""


def test_duplicate_rows_keep_the_first(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 9.7.0 | 2026-09-14 | 2026-10-07 | 먼저 |
        | shop | 9.7.0 | 2026-09-15 | 2026-10-08 | 나중 |
        """,
    )
    found = rel.load_releases(path)
    assert len(found) == 1
    assert found[("shop", "9.7.0")].note == "먼저"


def test_table_inside_a_code_fence_is_ignored(tmp_path):
    path = write(
        tmp_path,
        """
        ```
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 0.0.1 | 2026-09-14 | 2026-10-07 | 예시 |
        ```

        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 9.8.0 | 2026-09-14 | 2026-10-07 | 진짜 |
        """,
    )
    assert set(rel.load_releases(path)) == {("shop", "9.8.0")}


def test_release_is_frozen(tmp_path):
    r = rel.load_releases(write(tmp_path, REAL))[("shop", "3.3.0")]
    with pytest.raises(Exception):
        r.version = "9.9.9"


def test_unreadable_file_is_empty(tmp_path, monkeypatch):
    path = write(tmp_path, REAL)

    def boom(*a, **k):
        raise OSError("iCloud 미동기화")

    monkeypatch.setattr(rel.Path, "read_text", boom)
    assert rel.load_releases(path) == {}


def test_never_writes_the_file(tmp_path):
    path = write(tmp_path, REAL)
    before = path.read_bytes()
    rel.load_releases(path)
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# released — `비고` 에서 파생
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "note,expected",
    [
        ("배포완료", True),
        ("배포 완료", True),
        ("완료", True),
        ("released", True),
        ("Released", True),
        ("RELEASED 2026-06-25", True),
        ("배포완료 (핫픽스 포함)", True),
        ("", False),
        ("개발중", False),
        ("QA중", False),
        ("배포 예정", False),
        ("미완료", False),      # 반대말을 완료로 읽으면 red 가 조용히 사라진다
        ("QA 미완료", False),
    ],
)
def test_released_is_derived_from_the_note(tmp_path, note, expected):
    path = write(
        tmp_path,
        f"""
        | 프로젝트 | 버전 | QA 시작 | prod 배포 | 비고 |
        |---|---|---|---|---|
        | shop | 8.0.0 | 2026-09-14 | 2026-10-07 | {note} |
        """,
    )
    assert rel.load_releases(path)[("shop", "8.0.0")].released is expected


def test_released_in_the_real_shape(tmp_path):
    found = rel.load_releases(write(tmp_path, REAL))
    assert found[("shop", "3.1.3")].released is True
    assert found[("shop", "3.2.0")].released is True
    assert found[("shop", "3.3.0")].released is False
    assert found[("oms", "1.14.0")].released is False


def test_released_is_false_without_a_note_column(tmp_path):
    path = write(
        tmp_path,
        """
        | 프로젝트 | 버전 | QA 시작 | prod 배포 |
        |---|---|---|---|
        | shop | 8.1.0 | 2026-09-14 | 2026-10-07 |
        """,
    )
    assert rel.load_releases(path)[("shop", "8.1.0")].released is False


def test_released_is_not_an_init_argument():
    """파생값이다. 손으로 넘길 수 있으면 note 와 어긋난 Release 가 생긴다."""
    r = rel.Release("shop", "8.2.0", None, None, "배포완료")
    assert r.released is True
    with pytest.raises(TypeError):
        rel.Release("shop", "8.2.0", None, None, "", False)


def test_released_stays_in_sync_with_equality():
    same = rel.Release("shop", "8.3.0", None, None, "배포완료")
    other = rel.Release("shop", "8.3.0", None, None, "개발중")
    assert same != other
