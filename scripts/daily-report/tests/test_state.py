import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import state  # noqa: E402


EMPTY = {
    "schema": 1,
    "polled_at": None,
    "consecutive_errors": 0,
    "last_error": None,
    "tickets": {},
    "qa_candidates": {},
}

FULL = {
    "schema": 1,
    "polled_at": "2026-09-04T14:07:00+09:00",
    "consecutive_errors": 0,
    "last_error": None,
    "tickets": {
        "CWEB-1547": {
            "status": "진행 중",
            "status_category": "진행 중",
            "updated": "2026-09-02T18:22:00+09:00",
            "summary": "[shop] 커머스 쿠폰 Phase 1",
            "blocked": False,
            "md": ["myproject/tasks/shop3.3.0/CWEB-1547.md"],
            "links": {
                "confluence": {"5919834330": 13},
                "figma": {"AbC123": "2026-08-20T04:11:00Z"},
            },
        }
    },
    "qa_candidates": {
        "WPQ-17801": {
            "parent": "CWEB-1547",
            "basis": "description 언급",
            "state": "proposed",
            "seen": "2026-09-01",
        }
    },
}


def bak_of(path: Path) -> Path:
    return Path(str(path) + ".bak")


# --------------------------------------------------------------------------
# load
# --------------------------------------------------------------------------


def test_load_missing_file_returns_empty_state(tmp_path):
    assert state.load(tmp_path / "_state.json") == EMPTY


def test_load_missing_file_does_not_create_anything(tmp_path):
    state.load(tmp_path / "_state.json")
    assert list(tmp_path.iterdir()) == []


def test_load_valid_file(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text(json.dumps(FULL, ensure_ascii=False), encoding="utf-8")
    assert state.load(p) == FULL


def test_load_broken_json_falls_back_to_bak(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text('{"schema": 1, "tickets": {', encoding="utf-8")
    bak_of(p).write_text(json.dumps(FULL, ensure_ascii=False), encoding="utf-8")
    assert state.load(p) == FULL


def test_load_broken_json_and_broken_bak_returns_empty_state(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text("not json at all", encoding="utf-8")
    bak_of(p).write_text("]]] also not json", encoding="utf-8")
    assert state.load(p) == EMPTY


def test_load_never_raises_on_binary_garbage(tmp_path):
    p = tmp_path / "_state.json"
    p.write_bytes(b"\xff\xfe\x00\x00garbage")
    assert state.load(p) == EMPTY


def test_load_json_that_is_not_an_object_falls_back(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    bak_of(p).write_text(json.dumps(FULL, ensure_ascii=False), encoding="utf-8")
    assert state.load(p) == FULL


def test_load_fills_missing_top_level_keys(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text(json.dumps({"tickets": {"A-1": {"status": "x"}}}), encoding="utf-8")
    loaded = state.load(p)
    assert loaded["tickets"] == {"A-1": {"status": "x"}}
    assert loaded["schema"] == 1
    assert loaded["qa_candidates"] == {}
    assert loaded["polled_at"] is None
    assert loaded["consecutive_errors"] == 0
    assert loaded["last_error"] is None


def test_load_missing_file_ignores_existing_bak(tmp_path):
    # 본 파일이 사라진 것은 파싱 실패가 아니다. 계약대로 빈 상태.
    p = tmp_path / "_state.json"
    bak_of(p).write_text(json.dumps(FULL, ensure_ascii=False), encoding="utf-8")
    assert state.load(p) == EMPTY


# --------------------------------------------------------------------------
# save
# --------------------------------------------------------------------------


def test_save_roundtrip(tmp_path):
    p = tmp_path / "_state.json"
    state.save(p, FULL)
    assert state.load(p) == FULL


def test_save_keeps_hangul_readable(tmp_path):
    p = tmp_path / "_state.json"
    state.save(p, FULL)
    assert "진행 중" in p.read_text(encoding="utf-8")


def test_save_uses_temp_file_in_same_directory(tmp_path):
    p = tmp_path / "_state.json"
    seen = []
    real_replace = os.replace

    def spy(src, dst, *a, **kw):
        src_path = Path(src)
        seen.append((src_path, Path(dst), src_path.parent, src_path.exists()))
        return real_replace(src, dst, *a, **kw)

    original = os.replace
    os.replace = spy
    try:
        state.save(p, FULL)
    finally:
        os.replace = original

    assert seen, "save()는 os.replace 로 원자적 교체를 해야 한다"
    src, dst, src_parent, existed = seen[-1]
    assert dst == p
    assert src_parent == p.parent, "temp 파일은 대상과 같은 디렉토리에 있어야 한다"
    assert src != p
    assert existed, "replace 시점에 temp 파일이 존재해야 한다"


def test_save_leaves_no_temp_files_behind(tmp_path):
    p = tmp_path / "_state.json"
    state.save(p, FULL)
    state.save(p, EMPTY)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["_state.json", "_state.json.bak"]


def test_save_first_write_creates_no_bak(tmp_path):
    p = tmp_path / "_state.json"
    state.save(p, FULL)
    assert not bak_of(p).exists()


def test_save_creates_bak_with_previous_content(tmp_path):
    p = tmp_path / "_state.json"
    state.save(p, FULL)
    state.save(p, EMPTY)
    assert json.loads(bak_of(p).read_text(encoding="utf-8")) == FULL
    assert json.loads(p.read_text(encoding="utf-8")) == EMPTY


def test_save_refreshes_bak_on_each_run(tmp_path):
    p = tmp_path / "_state.json"
    v1 = dict(EMPTY, polled_at="v1")
    v2 = dict(EMPTY, polled_at="v2")
    v3 = dict(EMPTY, polled_at="v3")
    state.save(p, v1)
    state.save(p, v2)
    assert json.loads(bak_of(p).read_text(encoding="utf-8"))["polled_at"] == "v1"
    state.save(p, v3)
    assert json.loads(bak_of(p).read_text(encoding="utf-8"))["polled_at"] == "v2"
    assert json.loads(p.read_text(encoding="utf-8"))["polled_at"] == "v3"


def test_save_bak_preserves_unparseable_previous_file(tmp_path):
    p = tmp_path / "_state.json"
    p.write_text("{broken", encoding="utf-8")
    state.save(p, EMPTY)
    assert bak_of(p).read_text(encoding="utf-8") == "{broken"


def test_save_creates_parent_directory(tmp_path):
    p = tmp_path / "daily" / "_state.json"
    state.save(p, EMPTY)
    assert state.load(p) == EMPTY


def test_save_accepts_str_path(tmp_path):
    p = tmp_path / "_state.json"
    state.save(str(p), EMPTY)
    assert p.exists()


# --------------------------------------------------------------------------
# diff_ticket
# --------------------------------------------------------------------------


def ticket(**over):
    base = {
        "status": "진행 중",
        "status_category": "진행 중",
        "updated": "2026-09-02T18:22:00+09:00",
        "summary": "s",
        "blocked": False,
        "md": [],
        "links": {"confluence": {}, "figma": {}},
    }
    base.update(over)
    return base


def test_diff_new_ticket(tmp_path):
    events = state.diff_ticket(None, ticket(status="개발 준비"))
    assert len(events) == 1
    e = events[0]
    assert e.kind == "new"
    assert e.text == "**추적 시작** 개발 준비"
    assert e.attention is False


def test_diff_new_ticket_ignores_links(tmp_path):
    new = ticket(links={"confluence": {"111": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    events = state.diff_ticket(None, new)
    assert [e.kind for e in events] == ["new"]


def test_diff_status_change_only(tmp_path):
    old = ticket(status="개발 준비")
    new = ticket(status="진행 중")
    events = state.diff_ticket(old, new)
    assert len(events) == 1
    e = events[0]
    assert e.kind == "status"
    assert e.text == "**status** 개발 준비 → 진행 중"
    assert e.attention is False


def test_diff_confluence_version_bump(tmp_path):
    old = ticket(links={"confluence": {"5919834330": 12}, "figma": {}})
    new = ticket(links={"confluence": {"5919834330": 13}, "figma": {}})
    events = state.diff_ticket(old, new)
    assert len(events) == 1
    e = events[0]
    assert e.kind == "confluence"
    assert e.text == "**Confluence** `5919834330` v12 → v13"
    assert e.attention is True


def test_diff_confluence_version_decrease_is_ignored(tmp_path):
    old = ticket(links={"confluence": {"1": 13}, "figma": {}})
    new = ticket(links={"confluence": {"1": 12}, "figma": {}})
    assert state.diff_ticket(old, new) == []


def figma_pair(old_ts, new_ts):
    return (
        ticket(links={"confluence": {}, "figma": {"AbC123": old_ts}}),
        ticket(links={"confluence": {}, "figma": {"AbC123": new_ts}}),
    )


def test_diff_figma_last_modified_change(tmp_path):
    old, new = figma_pair("2026-08-20T04:11:00Z", "2026-08-29T09:30:00Z")
    events = state.diff_ticket(old, new)
    assert len(events) == 1
    e = events[0]
    assert e.kind == "figma"
    assert e.text == "**Figma** `AbC123` 08-20 13:11 → 08-29 18:30"
    assert e.attention is True


# --- Figma 타임스탬프 지터 (실측: 같은 파일이 초 단위로 흔들린다) ---------


def test_diff_figma_one_second_jitter_is_not_a_change(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:41Z", "2026-09-03T08:12:42Z")
    assert state.diff_ticket(old, new) == []


def test_diff_figma_fifty_nine_second_jitter_is_not_a_change(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:00Z", "2026-09-03T08:12:59Z")
    assert state.diff_ticket(old, new) == []


def test_diff_figma_exactly_sixty_seconds_is_a_change(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:00Z", "2026-09-03T08:13:00Z")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` 09-03 17:12 → 09-03 17:13"


def test_diff_figma_hours_apart_is_a_change(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:41Z", "2026-09-04T01:30:00Z")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` 09-03 17:12 → 09-04 10:30"


def test_diff_figma_backwards_beyond_tolerance_is_a_change(tmp_path):
    # 롤백도 알아야 한다.
    old, new = figma_pair("2026-09-04T01:30:00Z", "2026-09-03T08:12:41Z")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` 09-04 10:30 → 09-03 17:12"


def test_diff_figma_backwards_within_tolerance_is_not_a_change(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:42Z", "2026-09-03T08:12:41Z")
    assert state.diff_ticket(old, new) == []


def test_diff_figma_unparseable_differing_values_fall_back_to_string_compare(tmp_path):
    old, new = figma_pair("어제쯤", "오늘쯤")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` 어제쯤 → 오늘쯤"


def test_diff_figma_unparseable_equal_values_are_not_a_change(tmp_path):
    old, new = figma_pair("어제쯤", "어제쯤")
    assert state.diff_ticket(old, new) == []


def test_diff_figma_only_new_parseable_falls_back_to_string_compare(tmp_path):
    old, new = figma_pair("not-a-date", "2026-09-03T08:12:41Z")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` not-a-date → 09-03 17:12"


def test_diff_figma_only_old_parseable_falls_back_to_string_compare(tmp_path):
    old, new = figma_pair("2026-09-03T08:12:41Z", "not-a-date")
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["figma"]
    assert events[0].text == "**Figma** `AbC123` 09-03 17:12 → not-a-date"


def test_diff_figma_offset_input_parses_and_compares_by_instant(tmp_path):
    # 같은 순간을 다른 표기로 준 것뿐이다.
    old, new = figma_pair("2026-09-03T17:12:41+09:00", "2026-09-03T08:12:41Z")
    assert state.diff_ticket(old, new) == []


def test_diff_figma_offset_input_is_rendered_in_kst(tmp_path):
    old, new = figma_pair("2026-09-03T17:12:00+09:00", "2026-09-04T10:30:00+09:00")
    events = state.diff_ticket(old, new)
    assert events[0].text == "**Figma** `AbC123` 09-03 17:12 → 09-04 10:30"


def test_diff_figma_stores_nothing_and_does_not_truncate_inputs(tmp_path):
    # 비교만 관대하게 한다. 입력 원본은 건드리지 않는다.
    old, new = figma_pair("2026-09-03T08:12:41Z", "2026-09-03T08:12:42Z")
    state.diff_ticket(old, new)
    assert old["links"]["figma"]["AbC123"] == "2026-09-03T08:12:41Z"
    assert new["links"]["figma"]["AbC123"] == "2026-09-03T08:12:42Z"


def test_diff_figma_unparseable_display_is_capped_at_16_chars(tmp_path):
    long = "x" * 40
    old, new = figma_pair(long, long + "y")
    events = state.diff_ticket(old, new)
    assert events[0].text == f"**Figma** `AbC123` {'x' * 16} → {'x' * 16}"


def test_diff_no_change(tmp_path):
    old = ticket(links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    new = ticket(links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    assert state.diff_ticket(old, new) == []


def test_diff_updated_timestamp_alone_is_not_an_event(tmp_path):
    old = ticket(updated="2026-09-02T18:22:00+09:00")
    new = ticket(updated="2026-09-03T10:00:00+09:00")
    assert state.diff_ticket(old, new) == []


def test_diff_newly_registered_links_produce_no_events(tmp_path):
    old = ticket(links={"confluence": {}, "figma": {}})
    new = ticket(
        links={
            "confluence": {"5919834330": 13},
            "figma": {"AbC123": "2026-08-29T09:30:00Z"},
        }
    )
    assert state.diff_ticket(old, new) == []


def test_diff_links_key_absent_in_old_produces_no_events(tmp_path):
    old = ticket()
    del old["links"]
    new = ticket(links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    assert state.diff_ticket(old, new) == []


def test_diff_removed_links_produce_no_events(tmp_path):
    old = ticket(links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    new = ticket(links={"confluence": {}, "figma": {}})
    assert state.diff_ticket(old, new) == []


def test_diff_links_key_absent_in_new_produces_no_events(tmp_path):
    old = ticket(links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    new = ticket()
    del new["links"]
    assert state.diff_ticket(old, new) == []


def test_diff_status_and_confluence_order(tmp_path):
    old = ticket(status="개발 준비", links={"confluence": {"1": 3}, "figma": {}})
    new = ticket(status="진행 중", links={"confluence": {"1": 4}, "figma": {}})
    events = state.diff_ticket(old, new)
    assert [e.kind for e in events] == ["status", "confluence"]
    assert events[0].text == "**status** 개발 준비 → 진행 중"
    assert events[1].text == "**Confluence** `1` v3 → v4"


def test_diff_event_order_is_status_confluence_figma(tmp_path):
    old = ticket(
        status="개발 준비",
        links={"confluence": {"1": 3}, "figma": {"K": "2026-08-20T04:11:00Z"}},
    )
    new = ticket(
        status="진행 중",
        links={"confluence": {"1": 4}, "figma": {"K": "2026-08-29T09:30:00Z"}},
    )
    assert [e.kind for e in state.diff_ticket(old, new)] == [
        "status",
        "confluence",
        "figma",
    ]


def test_diff_multiple_links_are_sorted_by_id(tmp_path):
    old = ticket(links={"confluence": {"200": 1, "100": 1}, "figma": {}})
    new = ticket(links={"confluence": {"200": 2, "100": 2}, "figma": {}})
    events = state.diff_ticket(old, new)
    assert [e.text for e in events] == [
        "**Confluence** `100` v1 → v2",
        "**Confluence** `200` v1 → v2",
    ]


def test_diff_ticket_key_is_propagated_when_present(tmp_path):
    new = ticket(key="CWEB-1547", status="진행 중")
    old = ticket(key="CWEB-1547", status="개발 준비")
    assert state.diff_ticket(old, new)[0].ticket == "CWEB-1547"
    assert state.diff_ticket(None, new)[0].ticket == "CWEB-1547"


def test_diff_ticket_key_defaults_to_empty_string(tmp_path):
    assert state.diff_ticket(None, ticket())[0].ticket == ""


def test_diff_missing_old_status_is_not_reported(tmp_path):
    old = ticket()
    del old["status"]
    assert state.diff_ticket(old, ticket(status="진행 중")) == []


def test_diff_missing_new_status_is_not_reported(tmp_path):
    new = ticket()
    del new["status"]
    assert state.diff_ticket(ticket(status="진행 중"), new) == []


def test_diff_non_numeric_confluence_version_is_ignored(tmp_path):
    old = ticket(links={"confluence": {"1": "v3"}, "figma": {}})
    new = ticket(links={"confluence": {"1": "v4"}, "figma": {}})
    assert state.diff_ticket(old, new) == []


def test_diff_string_confluence_versions_still_compare_numerically(tmp_path):
    old = ticket(links={"confluence": {"1": "9"}, "figma": {}})
    new = ticket(links={"confluence": {"1": "10"}, "figma": {}})
    events = state.diff_ticket(old, new)
    assert [e.text for e in events] == ["**Confluence** `1` v9 → v10"]


def test_diff_figma_removed_value_is_ignored(tmp_path):
    old = ticket(links={"confluence": {}, "figma": {"K": "2026-08-20T04:11:00Z"}})
    new = ticket(links={"confluence": {}, "figma": {"K": None}})
    assert state.diff_ticket(old, new) == []


def test_diff_does_not_mutate_inputs(tmp_path):
    old = ticket(status="개발 준비", links={"confluence": {"1": 3}, "figma": {}})
    new = ticket(status="진행 중", links={"confluence": {"1": 4}, "figma": {}})
    old_copy = json.loads(json.dumps(old))
    new_copy = json.loads(json.dumps(new))
    state.diff_ticket(old, new)
    assert old == old_copy
    assert new == new_copy


def test_schema_constant():
    assert state.SCHEMA == 1


def test_event_field_order():
    e = state.Event("CWEB-1", "status", "t", True)
    assert (e.ticket, e.kind, e.text, e.attention) == ("CWEB-1", "status", "t", True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
