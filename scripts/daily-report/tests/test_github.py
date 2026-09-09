"""github.py — `gh` CLI 로 내 열린 PR 을 읽는 계층의 테스트.

**실제 `gh` 를 부르지 않는다.** `subprocess.run` 을 갈아끼우고 고정 JSON 을 쓴다.
실제로 부르면 테스트가 네트워크·인증·계정 상태에 묶이고, CI 에서는 인증이 없어
전부 빨개진다.

이 모듈의 계약은 "실패해도 조용히 빈 리스트" 다. PR 조회가 폴링을 죽이면
감시 8개가 같이 죽는다 — 그래서 예외를 밖으로 던지지 않는 것을 규칙마다 짚는다.
"""

import json
import subprocess
from datetime import date

import pytest

import github
from github import PullRequest

TODAY = date(2026, 9, 9)
SLUG = "weverse/web_weverseshop"


# ---------------------------------------------------------------------------
# 조립 도우미
# ---------------------------------------------------------------------------

class Completed:
    """`subprocess.CompletedProcess` 대역."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRun:
    """argv 를 기록하고 미리 정한 결과를 돌려준다. 규칙은 위에서부터 먼저 맞는 것."""

    def __init__(self):
        self.calls = []
        self.rules = []
        self.fallback = Completed()

    def on(self, needle, result):
        self.rules.append((needle, result))
        return self

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": [str(a) for a in argv], "kwargs": kwargs})
        joined = " ".join(str(a) for a in argv)
        for needle, result in self.rules:
            if needle in joined:
                return self._value(result)
        return self._value(self.fallback)

    @staticmethod
    def _value(result):
        if isinstance(result, BaseException):
            raise result
        return result

    # --- 조회 ------------------------------------------------------------
    @property
    def argvs(self):
        return [call["argv"] for call in self.calls]

    def argv(self, index=0):
        return self.calls[index]["argv"]

    def kwargs(self, index=0):
        return self.calls[index]["kwargs"]


@pytest.fixture
def run(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(github.subprocess, "run", fake)
    monkeypatch.setattr(github.shutil, "which", lambda name: f"/opt/bin/{name}")
    return fake


def row(number=101, title="CWEB-1547 쿠폰 할인 표시", branch="features/CWEB-1547",
        created="2026-09-01T02:00:00Z", draft=False, mergeable="MERGEABLE",
        review="REVIEW_REQUIRED"):
    return {
        "number": number,
        "title": title,
        "headRefName": branch,
        "createdAt": created,
        "isDraft": draft,
        "mergeable": mergeable,
        "reviewDecision": review,
    }


def listing(*rows):
    return Completed(stdout=json.dumps(list(rows)))


def detail(commits=("2026-09-02T05:00:00Z",), reviews=()):
    """`gh pr view --json commits,reviews` 의 응답."""
    payload = {}
    if commits is not None:
        payload["commits"] = [{"committedDate": stamp} for stamp in commits]
    if reviews is not None:
        payload["reviews"] = [
            {"state": state, "submittedAt": stamp} for state, stamp in reviews
        ]
    return Completed(stdout=json.dumps(payload))


# ---------------------------------------------------------------------------
# PullRequest 계약
# ---------------------------------------------------------------------------

def pull(**over):
    fields = {
        "repo": SLUG,
        "number": 101,
        "title": "제목",
        "branch": "features/CWEB-1547",
        "created": date(2026, 9, 1),
        "draft": False,
        "mergeable": "MERGEABLE",
        "review": "",
        "last_commit": None,
    }
    fields.update(over)
    return PullRequest(**fields)


def test_pull_request_is_frozen():
    with pytest.raises(Exception):
        pull().number = 7


def test_pull_request_subject_is_the_dedup_key():
    assert pull(repo="a/b", number=2974).subject == "a/b#2974"


def test_pull_request_review_at_defaults_to_none():
    """스펙의 9개 필드만 위치 인자로 넘겨도 조립된다."""
    made = PullRequest(SLUG, 1, "t", "b", date(2026, 9, 1), False, "", "", None)
    assert made.review_at is None


# ---------------------------------------------------------------------------
# repo_slug
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/weverse/web_weverseshop.git", "weverse/web_weverseshop"),
        ("https://github.com/weverse/web_weverseshop", "weverse/web_weverseshop"),
        ("git@github.com:weverse/web_weverseshop.git", "weverse/web_weverseshop"),
        ("ssh://git@github.com/weverse/web_weverseshop.git", "weverse/web_weverseshop"),
        ("https://github.com/weverse/web_weverseshop/", "weverse/web_weverseshop"),
        ("  https://github.com/weverse/shop.git  \n", "weverse/shop"),
        ("git@github.enterprise.co.kr:team/repo.git", "team/repo"),
    ],
)
def test_repo_slug_reads_the_origin_url(run, url, expected):
    run.fallback = Completed(stdout=url + "\n")
    assert github.repo_slug("/repos/shop") == expected


def test_repo_slug_passes_the_path_to_git(run):
    run.fallback = Completed(stdout="https://github.com/a/b.git\n")
    github.repo_slug("/repos/shop")
    argv = run.argv()
    assert argv[0] == "git"
    assert "/repos/shop" in argv
    assert argv[-3:] == ["remote", "get-url", "origin"]


def test_repo_slug_strips_a_token_embedded_in_the_url(run):
    """`https://user:token@host/...` 형태가 슬러그로 새어 나가지 않는다."""
    run.fallback = Completed(stdout="https://x-token:ghp_secret@github.com/a/b.git\n")
    assert github.repo_slug("/repos/shop") == "a/b"


def test_repo_slug_without_a_remote_is_none(run):
    run.fallback = Completed(stderr="error: No such remote 'origin'", returncode=2)
    assert github.repo_slug("/repos/shop") is None


def test_repo_slug_missing_path_is_none(run):
    run.fallback = FileNotFoundError("no such directory")
    assert github.repo_slug("/nope") is None


def test_repo_slug_empty_path_does_not_run_git(run):
    assert github.repo_slug("") is None
    assert github.repo_slug(None) is None
    assert run.calls == []


@pytest.mark.parametrize("url", ["", "\n", "origin", "/Users/me/repo", "https://github.com/"])
def test_repo_slug_unparseable_url_is_none(run, url):
    run.fallback = Completed(stdout=url)
    assert github.repo_slug("/repos/shop") is None


def test_repo_slug_never_raises(run):
    run.fallback = subprocess.TimeoutExpired(cmd="git", timeout=1)
    assert github.repo_slug("/repos/shop") is None


def test_repo_slug_is_quiet_about_a_missing_remote(run, capsys):
    """origin 이 없는 로컬 리포는 흔하다. 폴링마다 한 줄씩 남길 일이 아니다."""
    run.fallback = Completed(stderr="fatal: not a git repository", returncode=128)
    github.repo_slug("/repos/shop")
    assert capsys.readouterr().err == ""


def test_repo_slug_accepts_a_path_object(run, tmp_path):
    run.fallback = Completed(stdout="git@github.com:a/b.git\n")
    assert github.repo_slug(tmp_path) == "a/b"


# ---------------------------------------------------------------------------
# list_open_prs — 정상 경로
# ---------------------------------------------------------------------------

def test_list_open_prs_parses_a_row(run):
    run.fallback = listing(row())

    prs = github.list_open_prs([SLUG], TODAY)

    assert len(prs) == 1
    pr = prs[0]
    assert pr.repo == SLUG
    assert pr.number == 101
    assert pr.title == "CWEB-1547 쿠폰 할인 표시"
    assert pr.branch == "features/CWEB-1547"
    assert pr.created == date(2026, 9, 1)
    assert pr.draft is False
    assert pr.mergeable == "MERGEABLE"
    assert pr.review == "REVIEW_REQUIRED"
    assert pr.last_commit is None   # 변경요청이 아니면 상세를 묻지 않는다
    assert pr.review_at is None


def test_list_open_prs_builds_the_expected_command(run):
    run.fallback = listing(row())
    github.list_open_prs([SLUG], TODAY)

    argv = run.argv()
    assert argv[:3] == ["gh", "pr", "list"]
    assert argv[argv.index("--repo") + 1] == SLUG
    assert argv[argv.index("--author") + 1] == "@me"
    assert argv[argv.index("--state") + 1] == "open"
    fields = argv[argv.index("--json") + 1].split(",")
    assert "number" in fields and "mergeable" in fields and "reviewDecision" in fields


def test_list_open_prs_never_asks_for_commits_in_the_listing(run):
    """실측: `--limit 100` × `commits` 는 GraphQL 노드 한도(50만)를 넘어 **목록
    전체가 실패한다.** 무거운 필드 하나 때문에 PR 감시가 통째로 사라졌다.
    """
    run.fallback = listing(row())
    github.list_open_prs([SLUG], TODAY)

    fields = run.argv()[run.argv().index("--json") + 1].split(",")
    assert "commits" not in fields
    assert "reviews" not in fields


def test_list_open_prs_always_passes_a_timeout(run):
    run.fallback = listing(row())
    github.list_open_prs([SLUG], TODAY)
    kwargs = run.kwargs()
    assert kwargs["capture_output"] is True
    assert isinstance(kwargs["timeout"], (int, float))
    assert kwargs["timeout"] > 0


def test_list_open_prs_covers_every_slug(run):
    run.fallback = listing(row())
    prs = github.list_open_prs(["a/b", "c/d"], TODAY)
    assert [pr.repo for pr in prs] == ["a/b", "c/d"]
    assert len(run.calls) == 2


def test_list_open_prs_dedups_slugs(run):
    run.fallback = listing(row())
    prs = github.list_open_prs(["a/b", "a/b", "", None], TODAY)
    assert len(prs) == 1
    assert len(run.calls) == 1


def test_list_open_prs_without_slugs_does_not_touch_gh(run):
    assert github.list_open_prs([], TODAY) == []
    assert github.list_open_prs(None, TODAY) == []
    assert run.calls == []


def test_list_open_prs_keeps_drafts(run):
    """드래프트 제외는 규칙(W9)의 판단이다. 여기서 지우면 다른 규칙이 못 쓴다."""
    run.fallback = listing(row(draft=True))
    assert github.list_open_prs([SLUG], TODAY)[0].draft is True


def test_list_open_prs_converts_timestamps_to_kst(run):
    """UTC 15:00 은 KST 로 다음 날이다. 하루 차이가 경계 규칙을 어긋나게 한다."""
    run.fallback = listing(row(created="2026-09-01T15:30:00Z"))
    assert github.list_open_prs([SLUG], TODAY)[0].created == date(2026, 9, 2)


def test_list_open_prs_clamps_a_future_created_date(run):
    """미래 날짜는 음수 경과일을 만든다. 오늘로 눌러 규칙이 산수만 하게 둔다."""
    run.fallback = listing(row(created="2026-09-20T02:00:00Z"))
    assert github.list_open_prs([SLUG], TODAY)[0].created == TODAY


def test_list_open_prs_missing_fields_fall_back_to_blanks(run):
    run.fallback = Completed(stdout=json.dumps([{"number": 5}]))
    pr = github.list_open_prs([SLUG], TODAY)[0]
    assert pr.number == 5
    assert pr.title == ""
    assert pr.branch == ""
    assert pr.mergeable == ""
    assert pr.review == ""
    assert pr.created == TODAY
    assert pr.last_commit is None


def test_list_open_prs_skips_rows_without_a_number(run):
    run.fallback = Completed(stdout=json.dumps([{"title": "no number"}, row()]))
    assert [pr.number for pr in github.list_open_prs([SLUG], TODAY)] == [101]


def test_list_open_prs_skips_non_dict_rows(run):
    run.fallback = Completed(stdout=json.dumps(["nope", 3, None, row()]))
    assert len(github.list_open_prs([SLUG], TODAY)) == 1


# ---------------------------------------------------------------------------
# 상세 조회 — 변경요청 PR 에만
# ---------------------------------------------------------------------------

def requested(**over):
    return listing(row(review="CHANGES_REQUESTED", **over))


def test_details_are_only_fetched_for_a_change_request(run):
    """실측 11건 중 변경요청은 0건이다. 대개 상세 조회는 일어나지 않는다."""
    run.fallback = listing(row(review="APPROVED"), row(number=2, review=""))
    github.list_open_prs([SLUG], TODAY)
    assert [argv[1:3] for argv in run.argvs] == [["pr", "list"]]


def test_details_are_fetched_for_a_change_request(run):
    run.on("pr view", detail())
    run.fallback = requested()

    pr = github.list_open_prs([SLUG], TODAY)[0]

    assert pr.last_commit == date(2026, 9, 2)
    argv = run.argv(1)
    assert argv[:4] == ["gh", "pr", "view", "101"]
    assert argv[argv.index("--repo") + 1] == SLUG
    assert argv[argv.index("--json") + 1].split(",") == ["commits", "reviews"]


def test_details_use_the_latest_commit(run):
    run.on("pr view", detail(commits=(
        "2026-09-02T05:00:00Z", "2026-09-07T01:00:00Z", "2026-08-30T05:00:00Z",
    )))
    run.fallback = requested()
    assert github.list_open_prs([SLUG], TODAY)[0].last_commit == date(2026, 9, 7)


def test_details_without_commits_leave_last_commit_none(run):
    """없는 데이터로 판정하지 않는다 — W9c 가 스스로 빠진다."""
    run.on("pr view", detail(commits=()))
    run.fallback = requested()
    assert github.list_open_prs([SLUG], TODAY)[0].last_commit is None


def test_details_read_the_changes_requested_review_date(run):
    run.on("pr view", detail(reviews=(
        ("COMMENTED", "2026-09-01T01:00:00Z"),
        ("CHANGES_REQUESTED", "2026-09-03T01:00:00Z"),
        ("CHANGES_REQUESTED", "2026-09-05T01:00:00Z"),
    )))
    run.fallback = requested()
    assert github.list_open_prs([SLUG], TODAY)[0].review_at == date(2026, 9, 5)


def test_details_ignore_other_review_states(run):
    run.on("pr view", detail(reviews=(("APPROVED", "2026-09-05T01:00:00Z"),)))
    run.fallback = requested()
    assert github.list_open_prs([SLUG], TODAY)[0].review_at is None


def test_a_detail_failure_keeps_the_pull_request(run):
    """상세를 못 얻어도 PR 은 남는다 — W9a·W9b·W9d 는 그대로 돌아야 한다."""
    run.on("pr view", Completed(stderr="boom", returncode=1))
    run.fallback = requested()

    prs = github.list_open_prs([SLUG], TODAY)

    assert len(prs) == 1
    assert prs[0].last_commit is None
    assert prs[0].review_at is None


def test_a_detail_timeout_keeps_the_pull_request(run):
    run.on("pr view", subprocess.TimeoutExpired(cmd="gh", timeout=20))
    run.fallback = requested()
    assert len(github.list_open_prs([SLUG], TODAY)) == 1


def test_detail_bad_json_keeps_the_pull_request(run):
    run.on("pr view", Completed(stdout="{not json"))
    run.fallback = requested()
    assert len(github.list_open_prs([SLUG], TODAY)) == 1


def test_detail_non_dict_json_keeps_the_pull_request(run):
    run.on("pr view", Completed(stdout="[]"))
    run.fallback = requested()
    assert github.list_open_prs([SLUG], TODAY)[0].last_commit is None


# ---------------------------------------------------------------------------
# list_open_prs — 실패는 전부 빈 리스트
# ---------------------------------------------------------------------------

def test_list_open_prs_without_gh_is_empty(run, monkeypatch, capsys):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)

    assert github.list_open_prs([SLUG], TODAY) == []

    assert run.calls == []
    assert capsys.readouterr().err.strip().count("\n") == 0


def test_list_open_prs_without_gh_says_so_once(run, monkeypatch, capsys):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    github.list_open_prs(["a/b", "c/d"], TODAY)
    err = capsys.readouterr().err
    assert "gh" in err
    assert err.strip().count("\n") == 0


def test_list_open_prs_timeout_is_empty(run):
    run.fallback = subprocess.TimeoutExpired(cmd="gh", timeout=20)
    assert github.list_open_prs([SLUG], TODAY) == []


def test_list_open_prs_timeout_reports_one_line(run, capsys):
    run.fallback = subprocess.TimeoutExpired(cmd="gh", timeout=20)
    github.list_open_prs([SLUG], TODAY)
    assert capsys.readouterr().err.strip().count("\n") == 0


def test_list_open_prs_bad_json_is_empty(run):
    run.fallback = Completed(stdout="{not json")
    assert github.list_open_prs([SLUG], TODAY) == []


def test_list_open_prs_non_list_json_is_empty(run):
    run.fallback = Completed(stdout=json.dumps({"message": "Not Found"}))
    assert github.list_open_prs([SLUG], TODAY) == []


def test_list_open_prs_empty_stdout_is_empty(run):
    run.fallback = Completed(stdout="")
    assert github.list_open_prs([SLUG], TODAY) == []


def test_list_open_prs_auth_failure_is_empty(run, capsys):
    run.fallback = Completed(
        stderr="gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN",
        returncode=4,
    )
    assert github.list_open_prs([SLUG], TODAY) == []
    assert "gh" in capsys.readouterr().err


def test_list_open_prs_truncates_stderr(run, capsys):
    run.fallback = Completed(stderr="x" * 4000, returncode=1)
    github.list_open_prs([SLUG], TODAY)
    err = capsys.readouterr().err
    assert err.count("x") <= 200
    assert len(err) < 400


def test_list_open_prs_collapses_multiline_stderr(run, capsys):
    run.fallback = Completed(stderr="line one\nline two\nline three", returncode=1)
    github.list_open_prs([SLUG], TODAY)
    assert capsys.readouterr().err.strip().count("\n") == 0


def test_list_open_prs_one_bad_repo_does_not_sink_the_rest(run):
    run.on("a/b", Completed(stderr="boom", returncode=1))
    run.fallback = listing(row(number=7))
    prs = github.list_open_prs(["a/b", "c/d"], TODAY)
    assert [(pr.repo, pr.number) for pr in prs] == [("c/d", 7)]


def test_list_open_prs_unexpected_exception_is_swallowed(run):
    """조회 실패가 폴링을 죽이면 감시 8개가 같이 죽는다."""
    run.fallback = RuntimeError("something nobody predicted")
    assert github.list_open_prs([SLUG], TODAY) == []


def test_list_open_prs_garbage_timestamps_do_not_raise(run):
    run.on("pr view", detail(commits=("nope",), reviews=(("CHANGES_REQUESTED", "nope"),)))
    run.fallback = requested(created="어제")
    pr = github.list_open_prs([SLUG], TODAY)[0]
    assert pr.created == TODAY
    assert pr.last_commit is None
    assert pr.review_at is None


# ---------------------------------------------------------------------------
# 재시도하지 않는다 — 같은 질문에는 같은 답이 온다
# ---------------------------------------------------------------------------

def test_list_open_prs_does_not_retry_a_failed_listing(run):
    run.fallback = Completed(stderr="boom", returncode=1)
    assert github.list_open_prs([SLUG], TODAY) == []
    assert len(run.calls) == 1


def test_list_open_prs_does_not_retry_on_bad_json(run):
    """명령은 성공했고 출력이 이상한 것이다. 다시 물어도 같은 답이 온다."""
    run.fallback = Completed(stdout="{not json")
    github.list_open_prs([SLUG], TODAY)
    assert len(run.calls) == 1


# ---------------------------------------------------------------------------
# 시계
# ---------------------------------------------------------------------------

def test_module_never_reads_the_clock():
    """`today` 는 주입받는다. 시계를 직접 읽으면 재현이 불가능해진다."""
    import inspect

    source = inspect.getsource(github)
    assert "date.today(" not in source
    assert "datetime.now(" not in source
