"""감시 규칙 W1~W8 · 반복 억제 테스트.

경계값을 전부 짚는다 — 임계값 −1 / 정확히 임계값 / +1. 규칙이 하루 일찍
울리거나 하루 늦게 울리는 것을 실제로 겪었기 때문이다.

`today` 는 항상 주입한다. 이 모듈이 `date.today()` 를 부르면 테스트가 달에
한 번씩 깨지고, 그때 원인을 찾는 데 하루가 든다.
"""

import inspect
from datetime import date, timedelta

import pytest

import watch
from releases import Release
from watch import DEFAULTS, Alert

TODAY = date(2026, 9, 9)      # 수요일
MONDAY = date(2026, 9, 7)
SUNDAY = date(2026, 9, 6)


# ---------------------------------------------------------------------------
# 조립 도우미
# ---------------------------------------------------------------------------

def ago(days, today=TODAY):
    """Jira `updated` 형식 문자열. days 일 전."""
    return (today - timedelta(days=days)).strftime("%Y-%m-%dT10:00:00.000+0900")


def ticket(status="진행 중", updated_days=0, fix_version=None, parked=None,
           blocked_since=None, done=False, today=TODAY, **extra):
    entry = {
        "status": status,
        "status_category": "완료" if done else "진행 중",
        "updated": ago(updated_days, today),
        "summary": "요약",
    }
    if fix_version is not None:
        entry["fix_version"] = fix_version
    if parked is not None:
        entry["parked"] = parked
    if blocked_since is not None:
        entry["blocked_since"] = blocked_since
    entry.update(extra)
    return entry


def release(project="shop", version="3.2.0", qa=None, prod=None, note=""):
    return Release(project, version, qa, prod, note)


def rel_map(*entries):
    return {(r.project, r.version): r for r in entries}


def since(days, today=TODAY):
    return (today - timedelta(days=days)).isoformat()


def hist(days_ago, body="**Confluence** `591` v26 → v44", resolved=False,
         today=TODAY, mark="⚠️ "):
    day = today - timedelta(days=days_ago)
    tail = " ✅ 변경 대응 정리" if resolved else ""
    return f"- `{day:%m-%d} 14:07` {mark}{body}{tail}"


GUIDE = [
    "> `poll.py`가 자동 append. 항목을 삭제하지 않는다.",
    "> `⚠️`는 판단이 필요하다는 뜻이며, 처리하면 줄 끝에 결과를 덧붙인다.",
]


def md(tmp_path, key, history=None, inquiry=None, frontmatter=(), name=None, tail=()):
    lines = ["---", f"jira_key: {key}", *frontmatter, "---", "", f"# {key}", ""]
    if inquiry is not None:
        lines += ["## 문의·Blocked", "", *inquiry, ""]
    if history is not None:
        lines += ["## 변경 히스토리", "", *GUIDE, "", *history, ""]
    lines += list(tail)
    path = tmp_path / f"{name or key}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [path]


def rules(alerts):
    return [a.rule for a in alerts]


def only(alerts, rule):
    return [a for a in alerts if a.rule == rule]


def one(alerts, rule):
    found = only(alerts, rule)
    assert len(found) == 1, f"{rule} 이 {len(found)}건: {[a.text for a in found]}"
    return found[0]


def run(tickets=None, releases=None, today=TODAY, cfg=None, mds=None):
    return watch.evaluate(tickets or {}, releases or {}, today, cfg or {}, mds or {})


# ---------------------------------------------------------------------------
# 기본 계약
# ---------------------------------------------------------------------------

def test_empty_input_is_no_alerts():
    assert run() == []


def test_never_reads_the_clock():
    """`date.today()` 를 부르면 오늘이 언제냐에 따라 결과가 흔들린다."""
    source = inspect.getsource(watch)
    assert "date.today(" not in source
    assert "datetime.now(" not in source


def test_alert_is_frozen():
    alert = Alert("W1", "shop3.2.0", "red", "text", 1)
    with pytest.raises(Exception):
        alert.level = "yellow"


def test_alert_tickets_defaults_to_empty_tuple():
    assert Alert("W1", "s", "red", "t", 1).tickets == ()


def test_defaults_are_the_documented_eight():
    assert DEFAULTS == {
        "deploy_soon_days": 3,
        "deploy_stale_days": 30,
        "attention_stale_days": 3,
        "attention_urgent_days": 7,
        "inquiry_silent_days": 3,
        "blocked_long_days": 7,
        "ticket_stale_days": 14,
        "parked_stale_days": 30,
    }


# ---------------------------------------------------------------------------
# threshold
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cfg", [None, {}, {"watch": {}}, object()])
def test_threshold_falls_back_to_defaults(cfg):
    assert watch.threshold(cfg, "deploy_soon_days") == 3


def test_threshold_reads_nested_watch_table():
    assert watch.threshold({"watch": {"deploy_soon_days": 9}}, "deploy_soon_days") == 9


def test_threshold_reads_a_bare_watch_dict():
    assert watch.threshold({"deploy_soon_days": 9}, "deploy_soon_days") == 9


def test_threshold_reads_a_config_object():
    class Cfg:
        watch = {"ticket_stale_days": 21}

    assert watch.threshold(Cfg(), "ticket_stale_days") == 21


def test_threshold_coerces_numeric_strings():
    assert watch.threshold({"watch": {"blocked_long_days": "5"}}, "blocked_long_days") == 5


def test_threshold_accepts_zero():
    assert watch.threshold({"watch": {"deploy_soon_days": 0}}, "deploy_soon_days") == 0


@pytest.mark.parametrize("value", ["abc", -1, None, "", [], {}, True])
def test_threshold_rejects_garbage(value):
    assert watch.threshold({"watch": {"deploy_soon_days": value}}, "deploy_soon_days") == 3


def test_threshold_unknown_key_is_a_bug():
    with pytest.raises(KeyError):
        watch.threshold({}, "nope_days")


# ---------------------------------------------------------------------------
# watch_ignore
# ---------------------------------------------------------------------------

def test_ignore_reason_without_paths():
    assert watch.ignore_reason([]) is None
    assert watch.ignore_reason(None) is None


def test_ignore_reason_missing_file(tmp_path):
    assert watch.ignore_reason([tmp_path / "nope.md"]) is None


def test_ignore_reason_no_frontmatter(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("# 제목\n\nwatch_ignore: 본문은 프론트매터가 아니다\n", encoding="utf-8")
    assert watch.ignore_reason([path]) is None


def test_ignore_reason_reads_the_value(tmp_path):
    paths = md(tmp_path, "CWEB-1", frontmatter=["watch_ignore: 기획 확정 대기"])
    assert watch.ignore_reason(paths) == "기획 확정 대기"


def test_ignore_reason_strips_quotes_and_comments(tmp_path):
    paths = md(tmp_path, "CWEB-1", frontmatter=['watch_ignore: "BE 일정 대기"  # 9월'])
    assert watch.ignore_reason(paths) == "BE 일정 대기"


def test_ignore_reason_true_counts_as_ignored(tmp_path):
    paths = md(tmp_path, "CWEB-1", frontmatter=["watch_ignore: true"])
    assert watch.ignore_reason(paths) is not None


@pytest.mark.parametrize("value", ["false", "no", "0", "none", "", "null", "  "])
def test_ignore_reason_falsy_values_are_not_ignored(tmp_path, value):
    paths = md(tmp_path, "CWEB-1", frontmatter=[f"watch_ignore: {value}"])
    assert watch.ignore_reason(paths) is None


def test_ignore_reason_absent_key(tmp_path):
    paths = md(tmp_path, "CWEB-1", frontmatter=["blocked: false"])
    assert watch.ignore_reason(paths) is None


def test_ignore_reason_one_of_several_mds_is_enough(tmp_path):
    off = md(tmp_path, "CWEB-1", name="a")
    on = md(tmp_path, "CWEB-1", frontmatter=["watch_ignore: 대기"], name="b")
    assert watch.ignore_reason(off + on) == "대기"
    assert watch.ignore_reason(on + off) == "대기"


def test_ignore_reason_ignores_indented_lookalike(tmp_path):
    paths = md(tmp_path, "CWEB-1", frontmatter=["links:", "  watch_ignore: 중첩"])
    assert watch.ignore_reason(paths) is None


def test_ignored_ticket_produces_no_alerts_at_all(tmp_path):
    """방치와 의도적 대기를 구분하는 장치. 전 규칙에서 빠져야 한다."""
    paths = md(
        tmp_path,
        "CWEB-1",
        frontmatter=["watch_ignore: BE 일정 대기"],
        history=[hist(30)],
        inquiry=["- API 스펙 언제 나오나요?"],
    )
    tickets = {
        "CWEB-1": ticket(
            updated_days=99, fix_version="shop3.2.0", blocked_since=since(99)
        )
    }
    releases = rel_map(release(prod=TODAY - timedelta(days=5), qa=TODAY - timedelta(days=20)))

    assert run(tickets, releases, mds={"CWEB-1": paths}) == []


def test_ignored_ticket_is_left_out_of_release_counts(tmp_path):
    quiet = md(tmp_path, "CWEB-1", frontmatter=["watch_ignore: 대기"], name="q")
    tickets = {
        "CWEB-1": ticket(fix_version="shop3.2.0"),
        "CWEB-2": ticket(fix_version="shop3.2.0"),
    }
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    alert = one(run(tickets, releases, mds={"CWEB-1": quiet}), "W1")
    assert alert.tickets == ("CWEB-2",)
    assert "1건" in alert.text


def test_release_alert_vanishes_when_every_ticket_is_ignored(tmp_path):
    quiet = md(tmp_path, "CWEB-1", frontmatter=["watch_ignore: 대기"], name="q")
    tickets = {"CWEB-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    assert run(tickets, releases, mds={"CWEB-1": quiet}) == []


# ---------------------------------------------------------------------------
# W1 배포일 경과 — (프로젝트, 버전) 단위 집계
# ---------------------------------------------------------------------------

def test_w1_fires_when_the_deploy_date_has_passed():
    tickets = {"WPQ-17409": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=2)))

    alert = one(run(tickets, releases), "W1")
    assert alert.level == "red"
    assert alert.subject == "shop3.2.0"
    assert alert.days == 2
    assert alert.tickets == ("WPQ-17409",)
    assert "shop 3.2.0" in alert.text
    assert "09-07" in alert.text
    assert "2일 경과" in alert.text


def test_w1_aggregates_one_release_into_one_alert():
    """이전 구현이 티켓별로 만들어 릴리즈 하나를 27줄로 도배했다."""
    keys = ["WPQ-17409", "WPQ-17410", "WPQ-17411", "WPQ-17412", "WPQ-17413"]
    tickets = {k: ticket(fix_version="shop3.2.0") for k in keys}
    releases = rel_map(release(prod=TODAY - timedelta(days=2)))

    alerts = run(tickets, releases)

    assert len(alerts) == 1
    assert alerts[0].tickets == tuple(keys)
    assert len(alerts[0].tickets) == 5
    assert "5건" in alerts[0].text
    assert "WPQ-17409 외 4건" in alerts[0].text


def test_w1_two_releases_are_two_alerts():
    tickets = {
        "WPQ-1": ticket(fix_version="shop3.2.0"),
        "WPQ-2": ticket(fix_version="shop3.2.0"),
        "OMS-1": ticket(fix_version="oms1.14.0"),
    }
    releases = rel_map(
        release("shop", "3.2.0", prod=TODAY - timedelta(days=2)),
        release("oms", "1.14.0", prod=TODAY - timedelta(days=9)),
    )

    alerts = only(run(tickets, releases), "W1")

    assert len(alerts) == 2
    assert {a.subject for a in alerts} == {"shop3.2.0", "oms1.14.0"}


def test_w1_single_ticket_has_no_dangling_suffix():
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    text = one(run(tickets, releases), "W1").text
    assert "(WPQ-1)" in text
    assert "외" not in text


def test_w1_representative_is_deterministic():
    """자연순 최소값. 사전순이면 WPQ-17409 가 WPQ-9 앞에 온다."""
    tickets = {
        "WPQ-17409": ticket(fix_version="shop3.2.0"),
        "WPQ-9": ticket(fix_version="shop3.2.0"),
        "WPQ-100": ticket(fix_version="shop3.2.0"),
    }
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    alert = one(run(tickets, releases), "W1")
    assert alert.tickets == ("WPQ-9", "WPQ-100", "WPQ-17409")
    assert "WPQ-9 외 2건" in alert.text


def test_w1_counts_parked_tickets_too():
    """배포일이 지났는데 `Ready to Deploy` 로 남아 있는 것이 바로 그 신호다."""
    tickets = {"WPQ-1": ticket(status="Ready to Deploy", parked=True, fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    assert one(run(tickets, releases), "W1").tickets == ("WPQ-1",)


def test_w1_skips_completed_tickets():
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0", done=True)}
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))

    assert only(run(tickets, releases), "W1") == []


def test_w1_ignores_releases_absent_from_the_table():
    """일정을 모르는 것은 경보가 아니다."""
    tickets = {"WPQ-1": ticket(fix_version="shop9.9.9")}
    assert run(tickets, rel_map(release(prod=TODAY - timedelta(days=1)))) == []


def test_w1_ignores_unparseable_fix_version():
    tickets = {"WPQ-1": ticket(fix_version="26.10 (v.3.20.0)")}
    assert run(tickets, rel_map(release(prod=TODAY - timedelta(days=1)))) == []


def test_w1_ignores_tickets_without_a_fix_version():
    assert run({"WPQ-1": ticket()}, rel_map(release(prod=TODAY - timedelta(days=1)))) == []


def test_w1_needs_a_deploy_date():
    tickets = {"WPQ-1": ticket(fix_version="shop3.1.3")}
    releases = rel_map(release("shop", "3.1.3", prod=None, note="배포완료"))
    assert run(tickets, releases) == []


def test_w1_fires_even_when_the_note_says_shipped():
    """표의 `배포완료` 는 티켓이 닫혔다는 뜻이 아니다. 다만 급함은 내려간다."""
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=6), note="배포완료"))
    alert = one(run(tickets, releases), "W1")
    assert alert.days == 6
    assert alert.level == "yellow"


# ---------------------------------------------------------------------------
# W1 등급 강하 — 접히지 않는 🔴 가 영원히 뜨는 것을 막는다
# ---------------------------------------------------------------------------

def test_w1_is_red_while_the_release_is_still_live():
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=6)))

    alert = one(run(tickets, releases), "W1")
    assert alert.level == "red"
    assert alert.text.startswith("🔴")


@pytest.mark.parametrize("note", ["배포완료", "배포 완료", "완료", "released"])
def test_w1_downgrades_when_the_note_says_released(note):
    """나간 릴리즈에 티켓 하나가 남은 것을 매일 🔴 로 띄우면 아무도 안 읽는다."""
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=6), note=note))

    alert = one(run(tickets, releases), "W1")
    assert alert.level == "yellow"
    assert alert.text.startswith("🟡")


@pytest.mark.parametrize("note", ["", "개발중", "QA중", "미완료"])
def test_w1_keeps_red_for_a_note_that_does_not_say_released(note):
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=6), note=note))
    assert one(run(tickets, releases), "W1").level == "red"


@pytest.mark.parametrize("days,level", [(1, "red"), (29, "red"), (30, "red"), (31, "yellow"), (76, "yellow")])
def test_w1_downgrades_past_the_stale_threshold(days, level):
    """6일 지난 것은 아직 급하고, 76일 지난 것은 급한 척을 그만해야 한다."""
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=days)))

    alert = one(run(tickets, releases), "W1")
    assert alert.level == level
    assert alert.days == days


def test_w1_stale_threshold_is_configurable():
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=10)))
    cfg = {"watch": {"deploy_stale_days": 5}}

    assert one(run(tickets, releases, cfg=cfg), "W1").level == "yellow"
    assert one(run(tickets, releases), "W1").level == "red"


def test_w2_is_never_downgraded():
    """임박은 경과가 아니다. 아직 손 쓸 수 있으므로 🔴 로 둔다."""
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY + timedelta(days=1), note="배포완료"))
    assert one(run(tickets, releases), "W2").level == "red"


def test_downgraded_w1_folds_on_the_second_sighting():
    """강하의 목적이 이것이다 — 접힘 대상이 된다."""
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=76)))

    alerts = run(tickets, releases)
    seen = watch.update_seen({}, alerts, TODAY - timedelta(days=1))
    fresh, folded = watch.partition(alerts, seen, TODAY)

    assert fresh == []
    assert [a.rule for a in folded] == ["W1"]
    assert watch.fold_lines(folded) == ["🟡 W1 계속 1건 (shop3.2.0)"]


# ---------------------------------------------------------------------------
# W2 배포일 임박 — 경계
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta,fires", [(0, True), (1, True), (3, True), (4, False)])
def test_w2_boundary_on_the_default_threshold(delta, fires):
    tickets = {"WPQ-1": ticket(fix_version="shop3.3.0")}
    releases = rel_map(release("shop", "3.3.0", prod=TODAY + timedelta(days=delta)))

    alerts = only(run(tickets, releases), "W2")
    assert bool(alerts) is fires
    if fires:
        assert alerts[0].days == delta
        assert alerts[0].level == "red"


@pytest.mark.parametrize("delta,fires", [(0, True), (5, True), (6, False)])
def test_w2_boundary_on_a_configured_threshold(delta, fires):
    tickets = {"WPQ-1": ticket(fix_version="shop3.3.0")}
    releases = rel_map(release("shop", "3.3.0", prod=TODAY + timedelta(days=delta)))
    cfg = {"watch": {"deploy_soon_days": 5}}

    assert bool(only(run(tickets, releases, cfg=cfg), "W2")) is fires


def test_w2_and_w1_are_mutually_exclusive():
    tickets = {"WPQ-1": ticket(fix_version="shop3.2.0")}

    passed = run(tickets, rel_map(release(prod=TODAY - timedelta(days=1))))
    assert rules(passed) == ["W1"]

    soon = run(tickets, rel_map(release(prod=TODAY + timedelta(days=1))))
    assert rules(soon) == ["W2"]

    today = run(tickets, rel_map(release(prod=TODAY)))
    assert rules(today) == ["W2"]


def test_w2_aggregates_like_w1():
    tickets = {f"WPQ-{i}": ticket(fix_version="shop3.3.0") for i in range(1, 6)}
    releases = rel_map(release("shop", "3.3.0", prod=TODAY + timedelta(days=2)))

    alert = one(run(tickets, releases), "W2")
    assert len(alert.tickets) == 5
    assert "5건" in alert.text
    assert alert.subject == "shop3.3.0"


def test_w2_zero_threshold_only_fires_on_the_day():
    tickets = {"WPQ-1": ticket(fix_version="shop3.3.0")}
    cfg = {"watch": {"deploy_soon_days": 0}}

    on_day = rel_map(release("shop", "3.3.0", prod=TODAY))
    assert rules(run(tickets, on_day, cfg=cfg)) == ["W2"]

    tomorrow = rel_map(release("shop", "3.3.0", prod=TODAY + timedelta(days=1)))
    assert run(tickets, tomorrow, cfg=cfg) == []


# ---------------------------------------------------------------------------
# W3 QA 시작 경과
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta,fires", [(-1, False), (0, True), (1, True), (5, True)])
def test_w3_boundary(delta, fires):
    tickets = {"CWEB-1": ticket(fix_version="shop3.3.0")}
    releases = rel_map(release("shop", "3.3.0", qa=TODAY - timedelta(days=delta)))

    alerts = only(run(tickets, releases), "W3")
    assert bool(alerts) is fires
    if fires:
        assert alerts[0].days == delta
        assert alerts[0].level == "red"
        assert alerts[0].subject == "shop3.3.0"


def test_w3_excludes_parked_tickets():
    """parked 는 W8 이 본다. 두 번 울리지 않는다."""
    tickets = {
        "CWEB-1": ticket(fix_version="shop3.3.0"),
        "CWEB-2": ticket(status="Ready to Deploy", parked=True, fix_version="shop3.3.0"),
    }
    releases = rel_map(release("shop", "3.3.0", qa=TODAY - timedelta(days=2)))

    alert = one(run(tickets, releases), "W3")
    assert alert.tickets == ("CWEB-1",)
    assert "1건" in alert.text


def test_w3_silent_when_only_parked_tickets_remain():
    tickets = {"CWEB-2": ticket(status="Ready to Deploy", parked=True, fix_version="shop3.3.0")}
    releases = rel_map(release("shop", "3.3.0", qa=TODAY - timedelta(days=2)))

    assert only(run(tickets, releases), "W3") == []


def test_w3_excludes_completed_tickets():
    tickets = {"CWEB-1": ticket(fix_version="shop3.3.0", done=True)}
    releases = rel_map(release("shop", "3.3.0", qa=TODAY - timedelta(days=2)))
    assert run(tickets, releases) == []


def test_w3_needs_a_qa_date():
    tickets = {"CWEB-1": ticket(fix_version="shop3.1.1")}
    releases = rel_map(release("shop", "3.1.1", qa=None, prod=None))
    assert run(tickets, releases) == []


def test_w3_is_suppressed_when_w1_fires_on_the_same_release():
    """배포일이 지났으면 QA 시작일도 지났다. 같은 티켓·같은 건수로 두 줄이 난다."""
    tickets = {"CWEB-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(
        release(prod=TODAY - timedelta(days=2), qa=TODAY - timedelta(days=30))
    )
    assert rules(run(tickets, releases)) == ["W1"]


def test_w3_stays_suppressed_when_w1_is_downgraded():
    """W1 이 🟡 로 내려가도 여전히 상위 신호다. 부분집합을 되살릴 이유가 없다."""
    tickets = {"CWEB-1": ticket(fix_version="shop3.2.0")}
    releases = rel_map(
        release(prod=TODAY - timedelta(days=76), qa=TODAY - timedelta(days=90))
    )
    assert rules(run(tickets, releases)) == ["W1"]


def test_w3_fires_when_only_the_qa_date_has_passed():
    tickets = {"CWEB-1": ticket(fix_version="shop3.3.0")}
    releases = rel_map(
        release("shop", "3.3.0", qa=TODAY - timedelta(days=5), prod=TODAY + timedelta(days=30))
    )
    alert = one(run(tickets, releases), "W3")
    assert alert.level == "red"
    assert alert.days == 5


def test_w3_coexists_with_w2():
    """배포는 아직 안 지났고 QA 는 시작됐다. 서로 다른 사실을 말한다."""
    tickets = {"CWEB-1": ticket(fix_version="shop3.3.0")}
    releases = rel_map(
        release("shop", "3.3.0", qa=TODAY - timedelta(days=5), prod=TODAY + timedelta(days=2))
    )
    assert rules(run(tickets, releases)) == ["W2", "W3"]


def test_w3_survives_when_w1_is_silenced_by_completed_tickets():
    """W1 이 안 뜬 이유가 무엇이든, 안 떴으면 W3 는 자기 일을 한다."""
    tickets = {
        "CWEB-1": ticket(fix_version="shop3.2.0"),
        "CWEB-2": ticket(fix_version="shop3.2.0", done=True),
    }
    releases = rel_map(release(prod=None, qa=TODAY - timedelta(days=3)))
    assert rules(run(tickets, releases)) == ["W3"]


def test_w3_suppression_is_per_release():
    tickets = {
        "CWEB-1": ticket(fix_version="shop3.2.0"),
        "CWEB-2": ticket(fix_version="shop3.3.0"),
    }
    releases = rel_map(
        release("shop", "3.2.0", prod=TODAY - timedelta(days=2), qa=TODAY - timedelta(days=30)),
        release("shop", "3.3.0", qa=TODAY - timedelta(days=1)),
    )
    alerts = run(tickets, releases)
    assert [(a.rule, a.subject) for a in alerts] == [
        ("W1", "shop3.2.0"),
        ("W3", "shop3.3.0"),
    ]


def test_w3_aggregates_one_alert_per_release():
    tickets = {f"CWEB-{i}": ticket(fix_version="shop3.3.0") for i in range(1, 8)}
    releases = rel_map(release("shop", "3.3.0", qa=TODAY - timedelta(days=1)))

    alert = one(run(tickets, releases), "W3")
    assert len(alert.tickets) == 7
    assert "7건" in alert.text


# ---------------------------------------------------------------------------
# W4 미처리 ⚠️ 방치
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "days,fires,level",
    [(2, False, None), (3, True, "yellow"), (4, True, "yellow"),
     (6, True, "yellow"), (7, True, "red"), (9, True, "red")],
)
def test_w4_boundary_and_escalation(tmp_path, days, fires, level):
    paths = md(tmp_path, "CWEB-1", history=[hist(days)])
    alerts = only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")

    assert bool(alerts) is fires
    if fires:
        assert alerts[0].level == level
        assert alerts[0].days == days
        assert alerts[0].subject == "CWEB-1"


def test_w4_resolution_marker_is_the_check_not_the_arrow(tmp_path):
    """`v26 → v44` 처럼 본문이 `→` 를 품는다. `→` 로 판정하면 W4 가 영원히 0건이다."""
    paths = md(tmp_path, "CWEB-1", history=[hist(9, resolved=True)])
    alerts = only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")
    assert alerts == []


def test_w4_arrow_only_line_is_still_unresolved(tmp_path):
    line = "- `09-04 19:07` ⚠️ **Confluence** `591` v44 → v45"
    paths = md(tmp_path, "CWEB-1", history=[line])
    assert only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")


def test_w4_counts_only_the_unresolved_lines(tmp_path):
    paths = md(
        tmp_path,
        "CWEB-1",
        history=[
            hist(9, resolved=True),
            hist(8, resolved=True),
            hist(5),
            hist(4),
            hist(1),
        ],
    )
    alert = one(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")
    assert alert.days == 5              # 해소된 9일짜리는 세지 않는다
    assert alert.level == "yellow"
    assert "3건" in alert.text
    assert "5일" in alert.text


def test_w4_skips_lines_without_a_timestamp(tmp_path):
    """사람이 손으로 쓴 메모와 안내 blockquote 가 ⚠️ 를 품는다."""
    paths = md(
        tmp_path,
        "CWEB-1",
        history=[
            "- ⚠️ BE 확인 필요 (손으로 쓴 메모)",
            "⚠️ 이 줄도 타임스탬프가 없다",
            "> ⚠️ 안내 blockquote",
        ],
    )
    assert only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4") == []


def test_w4_only_looks_inside_the_history_section(tmp_path):
    paths = md(
        tmp_path,
        "CWEB-1",
        history=[hist(1)],
        tail=["## PR 리뷰", "", hist(40), ""],
    )
    alert = only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")
    assert alert == []  # 히스토리 안의 1일짜리 하나뿐이므로 임계 미달


def test_w4_without_a_history_section(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 없음"])
    assert only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4") == []


def test_w4_without_any_md():
    assert only(run({"CWEB-1": ticket()}), "W4") == []


def test_w4_year_wraps_to_the_nearest_past(tmp_path):
    """줄에는 연도가 없다. 12-28 은 1월 2일 기준으로 작년이다."""
    today = date(2027, 1, 2)
    paths = md(tmp_path, "CWEB-1", history=["- `12-28 14:07` ⚠️ **Confluence** `591` v1 → v2"])
    alert = one(run({"CWEB-1": ticket(today=today)}, today=today, mds={"CWEB-1": paths}), "W4")
    assert alert.days == 5


def test_w4_merges_several_mds(tmp_path):
    a = md(tmp_path, "CWEB-1", history=[hist(1)], name="a")
    b = md(tmp_path, "CWEB-1", history=[hist(8)], name="b")
    alert = one(run({"CWEB-1": ticket()}, mds={"CWEB-1": a + b}), "W4")
    assert alert.days == 8
    assert "2건" in alert.text


def test_w4_unreadable_md_is_skipped(tmp_path):
    paths = [tmp_path / "gone.md"]
    assert only(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4") == []


def test_w4_urgent_threshold_is_configurable(tmp_path):
    paths = md(tmp_path, "CWEB-1", history=[hist(4)])
    cfg = {"watch": {"attention_stale_days": 2, "attention_urgent_days": 4}}
    assert one(run({"CWEB-1": ticket()}, cfg=cfg, mds={"CWEB-1": paths}), "W4").level == "red"


def test_w4_future_timestamp_is_not_counted_as_today(tmp_path):
    """미래 날짜는 작년으로 읽힌다. 그 자체가 손으로 고친 흔적이므로 울려도 된다."""
    paths = md(tmp_path, "CWEB-1", history=[hist(-3)])
    alert = one(run({"CWEB-1": ticket()}, mds={"CWEB-1": paths}), "W4")
    assert alert.days > 300


# ---------------------------------------------------------------------------
# W5 문의 무응답
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,fires", [(2, False), (3, True), (4, True)])
def test_w5_boundary(tmp_path, days, fires):
    paths = md(tmp_path, "CWEB-1", inquiry=["- API 스펙 언제 나오나요? (BE 확인 중)"])
    tickets = {"CWEB-1": ticket(updated_days=days)}

    alerts = only(run(tickets, mds={"CWEB-1": paths}), "W5")
    assert bool(alerts) is fires
    if fires:
        assert alerts[0].level == "yellow"
        assert alerts[0].days == days
        assert alerts[0].subject == "CWEB-1"


@pytest.mark.parametrize(
    "body",
    [
        [],
        [""],
        ["없음"],
        ["- 없음"],
        ["해당없음"],
        ["n/a"],
        ["N/A"],
        ["none"],
        ["TBD"],
        ["- 문의:"],
        ["- 문의:", "- 담당:", "- 상태:"],
        ["**문의**:"],
        ["- 없음", ""],
        ["> 안내: 여기에 문의를 적는다"],
    ],
)
def test_w5_treats_template_only_sections_as_empty(tmp_path, body):
    paths = md(tmp_path, "CWEB-1", inquiry=body)
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5") == []


def test_w5_real_content_next_to_a_template_still_counts(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 문의:", "- 배송비 쿠폰 중복 적용 정책 확인 필요"])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5")


def test_w5_without_the_section(tmp_path):
    paths = md(tmp_path, "CWEB-1", history=[hist(1)])
    assert only(run({"CWEB-1": ticket(updated_days=99)}, mds={"CWEB-1": paths}), "W5") == []


def test_w5_recent_jira_update_silences_it(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 스펙 확인 필요"])
    assert only(run({"CWEB-1": ticket(updated_days=0)}, mds={"CWEB-1": paths}), "W5") == []


def test_w5_unparseable_updated_is_silent(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 스펙 확인 필요"])
    tickets = {"CWEB-1": {"status": "진행 중", "updated": "언젠가"}}
    assert only(run(tickets, mds={"CWEB-1": paths}), "W5") == []


def test_w5_threshold_is_configurable(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 스펙 확인 필요"])
    cfg = {"watch": {"inquiry_silent_days": 10}}
    tickets = {"CWEB-1": ticket(updated_days=9)}
    assert only(run(tickets, cfg=cfg, mds={"CWEB-1": paths}), "W5") == []


def test_w5_stops_at_the_next_heading(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 없음"], history=[hist(1)])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5") == []


# ---------------------------------------------------------------------------
# W5 는 parked 를 제외한다 — 내 손을 떠난 것에 내가 할 일은 없다
# ---------------------------------------------------------------------------

def test_w5_excludes_parked_tickets(tmp_path):
    """실측에서 W5 신규 10건이 전부 parked WPQ 였다. 적체는 W8 이 본다."""
    paths = md(tmp_path, "WPQ-1", inquiry=["- 배송비 정책 확인 필요"])
    tickets = {"WPQ-1": ticket(status="Ready to Deploy", parked=True, updated_days=7)}
    assert only(run(tickets, mds={"WPQ-1": paths}), "W5") == []


def test_w5_fires_for_an_active_ticket_with_the_same_content(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- 배송비 정책 확인 필요"])
    tickets = {"CWEB-1": ticket(updated_days=7)}
    assert one(run(tickets, mds={"CWEB-1": paths}), "W5").days == 7


def test_w5_excludes_parked_detected_from_the_config_statuses(tmp_path):
    paths = md(tmp_path, "WPQ-1", inquiry=["- 배송비 정책 확인 필요"])
    tickets = {"WPQ-1": ticket(status="Ready to Deploy", updated_days=7)}
    cfg = {"parked_statuses": ["Ready to Deploy"], "watch": {}}

    assert only(run(tickets, cfg=cfg, mds={"WPQ-1": paths}), "W5") == []
    assert only(run(tickets, mds={"WPQ-1": paths}), "W5")  # parked 판정이 없으면 그냥 활성이다


def test_w5_and_w8_do_not_both_fire_on_a_parked_ticket(tmp_path):
    paths = md(tmp_path, "WPQ-1", inquiry=["- 배송비 정책 확인 필요"])
    tickets = {"WPQ-1": ticket(status="Ready to Deploy", parked=True, updated_days=40)}
    assert rules(run(tickets, mds={"WPQ-1": paths})) == ["W8"]


# ---------------------------------------------------------------------------
# W5 포인터 문장 — 다른 문서를 가리키는 한 줄은 문의가 아니다
# ---------------------------------------------------------------------------

POINTER = (
    "전체 문의 목록은 [[WWSP-1820]] `## 문의·Blocked` 에서 관리한다 "
    "(장바구니 A·B·E군 + 공통 D군)."
)


@pytest.mark.parametrize(
    "line",
    [
        POINTER,
        "문의는 [[WWSP-1820]] 에서 관리",
        "- 문의 목록은 [[WWSP-1820]] 참조",
        "상세는 [[CWEB-1549]] 의 문의 섹션에서 본다",
    ],
)
def test_w5_pointer_line_is_an_empty_section(tmp_path, line):
    paths = md(tmp_path, "CWEB-1", inquiry=[line])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5") == []


def test_w5_pointer_line_next_to_a_template_marker_is_still_empty(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["> 안내", "", POINTER, "", "- 없음"])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5") == []


@pytest.mark.parametrize(
    "line",
    [
        "- **문의 내용**: [[WWSP-1820]] Q29 기준이 바뀌었는지",
        "- **문의 대상**: [[WWSP-1820]] 기획 · 답 없음",
        "- [[WWSP-1820]] Q29 기준이 바뀌었는지 확인 필요",
        "- 배송비 쿠폰 중복 적용 정책 확인 필요",
    ],
)
def test_w5_a_real_inquiry_survives_the_pointer_rule(tmp_path, line):
    """위키링크가 있다고 다 포인터가 아니다. 여기서 공격적으로 굴면 W5 가 죽는다."""
    paths = md(tmp_path, "CWEB-1", inquiry=[line])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5")


def test_w5_a_pointer_alongside_a_real_inquiry_still_fires(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=[POINTER, "- **문의 내용**: 배송비 정책"])
    assert one(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5")


def test_w5_delegation_words_alone_are_not_enough(tmp_path):
    """위키링크가 없으면 포인터로 보지 않는다 — 그냥 문의 문장일 수 있다."""
    paths = md(tmp_path, "CWEB-1", inquiry=["- 배송비 정책은 기획팀이 관리한다는데 확인 필요"])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5")


# ---------------------------------------------------------------------------
# W5 해소 — `✅` 로 끌 수 있어야 영구 yellow 가 안 된다
# ---------------------------------------------------------------------------

def test_w5_is_silent_when_every_inquiry_line_is_resolved(tmp_path):
    paths = md(
        tmp_path,
        "CWEB-1",
        inquiry=[
            "- **문의 내용**: 배송비 쿠폰 중복 적용 ✅ 09-05 기획 확정",
            "- **문의 내용**: Q29 기준 ✅ 답 받음",
        ],
    )
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5") == []


def test_w5_fires_while_one_inquiry_line_is_open(tmp_path):
    paths = md(
        tmp_path,
        "CWEB-1",
        inquiry=[
            "- **문의 내용**: 배송비 쿠폰 중복 적용 ✅ 09-05 기획 확정",
            "- **문의 내용**: Q29 기준이 바뀌었는지",
        ],
    )
    assert one(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5").days == 9


def test_w5_resolution_marker_is_the_check_not_the_arrow(tmp_path):
    paths = md(tmp_path, "CWEB-1", inquiry=["- **문의 내용**: 배송비 정책 → 기획 확인 중"])
    assert only(run({"CWEB-1": ticket(updated_days=9)}, mds={"CWEB-1": paths}), "W5")


def test_w5_resolution_drops_the_ticket_from_the_seen_map(tmp_path):
    """해소하면 seen 에서 사라진다. 월요일에 다시 펼쳐질 것이 남지 않는다."""
    open_md = md(tmp_path, "CWEB-1", inquiry=["- **문의 내용**: Q29 기준"], name="open")
    tickets = {"CWEB-1": ticket(updated_days=9)}

    alerts = run(tickets, mds={"CWEB-1": open_md})
    seen = watch.update_seen({}, alerts, TODAY)
    assert seen["CWEB-1"]["W5"] == "2026-09-09"

    done_md = md(tmp_path, "CWEB-1", inquiry=["- **문의 내용**: Q29 기준 ✅ 답 받음"], name="done")
    after = run(tickets, mds={"CWEB-1": done_md})
    assert only(after, "W5") == []
    assert "W5" not in watch.update_seen(seen, after, TODAY).get("CWEB-1", {})


# ---------------------------------------------------------------------------
# W6 blocked 장기화
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,fires", [(6, False), (7, True), (8, True)])
def test_w6_boundary(days, fires):
    tickets = {"CWEB-1": ticket(blocked_since=since(days), blocked=True)}
    alerts = only(run(tickets), "W6")

    assert bool(alerts) is fires
    if fires:
        assert alerts[0].level == "yellow"
        assert alerts[0].days == days
        assert since(days) in alerts[0].text


def test_w6_without_blocked_since():
    assert only(run({"CWEB-1": ticket(blocked=True)}), "W6") == []


@pytest.mark.parametrize("value", ["", "언젠가", None, "2026-13-45", 0])
def test_w6_garbage_blocked_since_is_silent(value):
    tickets = {"CWEB-1": ticket(blocked_since=value, blocked=True)}
    assert only(run(tickets), "W6") == []


def test_w6_threshold_is_configurable():
    tickets = {"CWEB-1": ticket(blocked_since=since(9), blocked=True)}
    assert only(run(tickets, cfg={"watch": {"blocked_long_days": 10}}), "W6") == []


def test_w6_future_blocked_since_is_silent():
    tickets = {"CWEB-1": ticket(blocked_since=since(-5), blocked=True)}
    assert only(run(tickets), "W6") == []


# ---------------------------------------------------------------------------
# W7 티켓 정체
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,fires", [(13, False), (14, True), (15, True)])
def test_w7_boundary(days, fires):
    alerts = only(run({"CWEB-1": ticket(updated_days=days)}), "W7")

    assert bool(alerts) is fires
    if fires:
        assert alerts[0].level == "yellow"
        assert alerts[0].days == days
        assert alerts[0].subject == "CWEB-1"


def test_w7_excludes_parked():
    tickets = {"CWEB-1": ticket(status="Ready to Deploy", parked=True, updated_days=20)}
    assert only(run(tickets), "W7") == []


def test_w7_excludes_completed():
    assert only(run({"CWEB-1": ticket(updated_days=20, done=True)}), "W7") == []


def test_w7_threshold_is_configurable():
    cfg = {"watch": {"ticket_stale_days": 30}}
    assert only(run({"CWEB-1": ticket(updated_days=20)}, cfg=cfg), "W7") == []


def test_w7_unparseable_updated_is_silent():
    assert only(run({"CWEB-1": {"status": "진행 중", "updated": ""}}), "W7") == []


# ---------------------------------------------------------------------------
# W8 배포대기 적체
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,fires", [(29, False), (30, True), (31, True)])
def test_w8_boundary(days, fires):
    tickets = {"CWEB-1": ticket(status="Ready to Deploy", parked=True, updated_days=days)}
    alerts = only(run(tickets), "W8")

    assert bool(alerts) is fires
    if fires:
        assert alerts[0].level == "yellow"
        assert alerts[0].days == days
        assert "Ready to Deploy" in alerts[0].text


def test_w8_needs_parked():
    assert only(run({"CWEB-1": ticket(updated_days=99)}), "W8") == []


def test_w8_detects_parked_from_config_statuses():
    """parked 엔트리에 플래그가 없어도 config 의 상태 목록으로 판정한다."""
    tickets = {"CWEB-1": ticket(status="Ready to Deploy", updated_days=40)}
    cfg = {"parked_statuses": ["Ready to Deploy"], "watch": {}}

    assert rules(run(tickets, cfg=cfg)) == ["W8"]
    assert rules(run(tickets)) == ["W7"]  # 플래그도 config 도 없으면 그냥 정체다


def test_w8_and_w7_do_not_double_up():
    tickets = {"CWEB-1": ticket(status="Ready to Deploy", parked=True, updated_days=40)}
    assert rules(run(tickets)) == ["W8"]


def test_w8_threshold_is_configurable():
    tickets = {"CWEB-1": ticket(status="Ready to Deploy", parked=True, updated_days=40)}
    assert only(run(tickets, cfg={"watch": {"parked_stale_days": 60}}), "W8") == []


# ---------------------------------------------------------------------------
# 전체 조합 · 결정론
# ---------------------------------------------------------------------------

def test_alerts_are_sorted_by_rule_then_subject():
    tickets = {
        "CWEB-2": ticket(fix_version="shop3.2.0", updated_days=40),
        "CWEB-1": ticket(fix_version="oms1.14.0", updated_days=40),
    }
    releases = rel_map(
        release("shop", "3.2.0", prod=TODAY - timedelta(days=1)),
        release("oms", "1.14.0", prod=TODAY - timedelta(days=1)),
    )

    alerts = run(tickets, releases)
    assert [(a.rule, a.subject) for a in alerts] == [
        ("W1", "oms1.14.0"),
        ("W1", "shop3.2.0"),
        ("W7", "CWEB-1"),
        ("W7", "CWEB-2"),
    ]


def test_repeated_evaluation_is_identical(tmp_path):
    paths = md(tmp_path, "CWEB-1", history=[hist(9)], inquiry=["- 스펙 확인"])
    tickets = {"CWEB-1": ticket(updated_days=20, fix_version="shop3.2.0")}
    releases = rel_map(release(prod=TODAY - timedelta(days=1)))
    args = (tickets, releases, TODAY, {}, {"CWEB-1": paths})

    assert watch.evaluate(*args) == watch.evaluate(*args)


def test_evaluate_accepts_a_list_of_entries():
    tickets = [{"key": "CWEB-1", "status": "진행 중", "updated": ago(20)}]
    assert one(run(tickets), "W7").subject == "CWEB-1"


def test_evaluate_does_not_mutate_its_inputs():
    tickets = {"CWEB-1": ticket(updated_days=20)}
    snapshot = {k: dict(v) for k, v in tickets.items()}
    run(tickets)
    assert tickets == snapshot


def test_entries_without_a_key_are_skipped():
    assert run({"": ticket(updated_days=99)}) == []


def test_non_dict_entries_are_skipped():
    assert run({"CWEB-1": None, "CWEB-2": "nope"}) == []


# ---------------------------------------------------------------------------
# partition — 반복 억제
# ---------------------------------------------------------------------------

def alert(rule="W4", subject="CWEB-1", level="yellow", days=5):
    return Alert(rule, subject, level, f"{rule} {subject}", days)


def test_partition_first_sighting_is_new():
    fresh, folded = watch.partition([alert()], {}, TODAY)
    assert [a.subject for a in fresh] == ["CWEB-1"]
    assert folded == []


def test_partition_folds_an_already_seen_yellow():
    seen = {"CWEB-1": {"W4": "2026-09-05"}}
    fresh, folded = watch.partition([alert()], seen, TODAY)
    assert fresh == []
    assert [a.subject for a in folded] == ["CWEB-1"]


def test_partition_never_folds_red():
    seen = {"shop3.2.0": {"W1": "2026-09-05"}}
    fresh, folded = watch.partition([alert("W1", "shop3.2.0", "red", 2)], seen, TODAY)
    assert [a.rule for a in fresh] == ["W1"]
    assert folded == []


def test_partition_expands_everything_on_monday():
    """주 1회는 전부 직면한다."""
    assert MONDAY.weekday() == 0
    seen = {"CWEB-1": {"W4": "2026-09-01"}, "CWEB-2": {"W7": "2026-09-01"}}
    alerts = [alert(), alert("W7", "CWEB-2")]

    fresh, folded = watch.partition(alerts, seen, MONDAY)
    assert len(fresh) == 2
    assert folded == []


def test_partition_folds_on_other_weekdays():
    assert TODAY.weekday() == 2
    seen = {"CWEB-1": {"W4": "2026-09-01"}}
    fresh, folded = watch.partition([alert()], seen, TODAY)
    assert (fresh, [a.subject for a in folded]) == ([], ["CWEB-1"])


def test_partition_keys_on_both_subject_and_rule():
    seen = {"CWEB-1": {"W4": "2026-09-01"}}
    fresh, folded = watch.partition([alert("W7", "CWEB-1")], seen, TODAY)
    assert [a.rule for a in fresh] == ["W7"]
    assert folded == []


def test_partition_handles_garbage_seen():
    for seen in ({"CWEB-1": None}, {"CWEB-1": "nope"}, {"CWEB-1": {}}, None):
        fresh, folded = watch.partition([alert()], seen, TODAY)
        assert len(fresh) == 1
        assert folded == []


def test_partition_empty():
    assert watch.partition([], {}, TODAY) == ([], [])


def test_partition_preserves_order():
    alerts = [alert("W4", "CWEB-1"), alert("W4", "CWEB-2"), alert("W7", "CWEB-3")]
    seen = {"CWEB-2": {"W4": "2026-09-01"}}
    fresh, folded = watch.partition(alerts, seen, TODAY)
    assert [a.subject for a in fresh] == ["CWEB-1", "CWEB-3"]
    assert [a.subject for a in folded] == ["CWEB-2"]


# ---------------------------------------------------------------------------
# update_seen
# ---------------------------------------------------------------------------

def test_update_seen_records_today_for_new_alerts():
    assert watch.update_seen({}, [alert()], TODAY) == {"CWEB-1": {"W4": "2026-09-09"}}


def test_update_seen_keeps_the_first_sighting_date():
    seen = {"CWEB-1": {"W4": "2026-09-01"}}
    assert watch.update_seen(seen, [alert()], TODAY)["CWEB-1"]["W4"] == "2026-09-01"


def test_update_seen_drops_resolved_entries():
    seen = {"CWEB-1": {"W4": "2026-09-01"}, "CWEB-9": {"W7": "2026-09-01"}}
    assert set(watch.update_seen(seen, [alert()], TODAY)) == {"CWEB-1"}


def test_update_seen_drops_a_resolved_rule_but_keeps_the_subject():
    seen = {"CWEB-1": {"W4": "2026-09-01", "W7": "2026-09-02"}}
    updated = watch.update_seen(seen, [alert()], TODAY)
    assert updated == {"CWEB-1": {"W4": "2026-09-01"}}


def test_update_seen_does_not_mutate_the_input():
    seen = {"CWEB-1": {"W4": "2026-09-01"}}
    watch.update_seen(seen, [alert("W7", "CWEB-2")], TODAY)
    assert seen == {"CWEB-1": {"W4": "2026-09-01"}}


def test_update_seen_replaces_garbage_dates():
    for bad in ({"CWEB-1": {"W4": "언젠가"}}, {"CWEB-1": {"W4": None}}, {"CWEB-1": 7}):
        assert watch.update_seen(bad, [alert()], TODAY) == {"CWEB-1": {"W4": "2026-09-09"}}


def test_update_seen_empty_alerts_clears_everything():
    assert watch.update_seen({"CWEB-1": {"W4": "2026-09-01"}}, [], TODAY) == {}


def test_seen_round_trip_folds_the_second_run(tmp_path):
    paths = md(tmp_path, "CWEB-1", history=[hist(5)])
    tickets = {"CWEB-1": ticket()}

    first = run(tickets, mds={"CWEB-1": paths})
    fresh, folded = watch.partition(first, {}, TODAY)
    assert len(fresh) == 1 and folded == []

    seen = watch.update_seen({}, first, TODAY)
    fresh, folded = watch.partition(first, seen, TODAY)
    assert fresh == [] and len(folded) == 1


# ---------------------------------------------------------------------------
# 접힘 요약 줄
# ---------------------------------------------------------------------------

def test_fold_lines_is_one_line_per_rule():
    folded = [alert("W4", "CWEB-1"), alert("W4", "CWEB-2"), alert("W7", "CWEB-3")]
    lines = watch.fold_lines(folded)

    assert len(lines) == 2
    assert "W4" in lines[0] and "2건" in lines[0] and "CWEB-1 외 1건" in lines[0]
    assert "W7" in lines[1] and "CWEB-3" in lines[1]


def test_fold_lines_empty():
    assert watch.fold_lines([]) == []


# ---------------------------------------------------------------------------
# 설정 연결
# ---------------------------------------------------------------------------

def test_example_config_documents_every_threshold():
    """임계값을 추가하고 예제에 안 적으면 아무도 조절할 줄 모른다."""
    import tomllib
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.toml"
    with open(example, "rb") as handle:
        table = tomllib.load(handle).get("watch")

    assert table == DEFAULTS


def test_config_passes_the_watch_table_through(tmp_path, monkeypatch):
    import config

    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                f'vault = "{tmp_path}"',
                'site = "example.atlassian.net"',
                'email = "me@example.com"',
                "[watch]",
                "ticket_stale_days = 21",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = config.load_config(path)

    assert cfg.watch == {"ticket_stale_days": 21}
    assert watch.threshold(cfg, "ticket_stale_days") == 21
    assert watch.threshold(cfg, "deploy_soon_days") == 3


def test_config_without_a_watch_table_uses_defaults(tmp_path):
    import config

    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                f'vault = "{tmp_path}"',
                'site = "example.atlassian.net"',
                'email = "me@example.com"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = config.load_config(path)

    assert cfg.watch == {}
    for key, expected in DEFAULTS.items():
        assert watch.threshold(cfg, key) == expected
