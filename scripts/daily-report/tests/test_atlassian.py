import base64

import pytest
from conftest import fixture

from atlassian import ApiError, ConfluenceClient, JiraClient

SITE = "example.atlassian.net"
EMAIL = "me@example.com"
TOKEN = "s3cr3t-token"


@pytest.fixture
def jira():
    return JiraClient(SITE, EMAIL, TOKEN)


@pytest.fixture
def confluence():
    return ConfluenceClient(SITE, EMAIL, TOKEN)


# --- ApiError ------------------------------------------------------------


def test_api_error_carries_status_path_body():
    err = ApiError(500, "/rest/api/3/search/jql", "internal boom")
    assert err.status == 500
    assert err.path == "/rest/api/3/search/jql"
    assert err.body == "internal boom"
    assert "500" in str(err)
    assert "internal boom" in str(err)


# --- JiraClient ----------------------------------------------------------


def test_jira_search_builds_request(jira, http):
    http.add_json(fixture("jira_search.json"))

    issues = jira.search(
        'project = CWEB AND assignee = currentUser() ORDER BY updated DESC',
        ["summary", "status", "updated"],
        max_results=50,
    )

    assert [i["key"] for i in issues] == ["CWEB-1547", "CWEB-1548"]
    assert http.path() == "/rest/api/3/search/jql"
    assert http.calls[0].full_url.startswith(f"https://{SITE}/rest/api/3/search/jql?")
    q = http.query()
    assert q["jql"] == [
        "project = CWEB AND assignee = currentUser() ORDER BY updated DESC"
    ]
    assert q["fields"] == ["summary,status,updated"]
    assert q["maxResults"] == ["50"]


def test_jira_search_default_max_results(jira, http):
    http.add_json({"issues": []})
    jira.search("project = CWEB", ["summary"])
    assert http.query()["maxResults"] == ["100"]


def test_jira_search_encodes_special_characters(jira, http):
    http.add_json({"issues": []})
    jql = 'status != "Ready to Deploy" AND updated >= -7d & key in (A-1)'
    jira.search(jql, ["summary"])

    raw_query = http.calls[0].full_url.split("?", 1)[1]
    assert " " not in raw_query
    assert '"' not in raw_query
    assert "&jql" not in raw_query  # the literal & inside the jql must be escaped
    assert http.query()["jql"] == [jql]


def test_jira_search_sends_basic_auth(jira, http):
    http.add_json({"issues": []})
    jira.search("project = CWEB", ["summary"])
    expected = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    assert http.headers()["authorization"] == f"Basic {expected}"
    assert http.headers()["accept"] == "application/json"


def test_jira_search_missing_issues_key(jira, http):
    http.add_json({"total": 0})
    assert jira.search("project = CWEB", ["summary"]) == []


def test_jira_search_raises_api_error(jira, http):
    http.add_error(400, b'{"errorMessages":["bad jql"]}')
    with pytest.raises(ApiError) as excinfo:
        jira.search("nonsense", ["summary"])
    err = excinfo.value
    assert err.status == 400
    assert err.path == "/rest/api/3/search/jql"
    assert "bad jql" in err.body


def test_jira_error_never_leaks_token(jira, http):
    http.add_error(401, b"unauthorized")
    with pytest.raises(ApiError) as excinfo:
        jira.search("project = CWEB", ["summary"])
    err = excinfo.value
    assert TOKEN not in str(err)
    assert TOKEN not in err.body
    assert TOKEN not in err.path
    assert TOKEN not in repr(jira)


# --- ConfluenceClient ----------------------------------------------------


def test_page_versions_returns_id_to_version(confluence, http):
    http.add_json(fixture("confluence_pages.json"))

    got = confluence.page_versions(["5919834330", "5919834331"])

    assert got == {"5919834330": 13, "5919834331": 2}
    assert http.path() == "/wiki/api/v2/pages"
    q = http.query()
    assert q["id"] == ["5919834330", "5919834331"]
    assert q["limit"] == ["250"]


def test_page_versions_drops_ids_absent_from_response(confluence, http):
    http.add_json(fixture("confluence_pages.json"))
    got = confluence.page_versions(["5919834330", "5919834331", "9999999999"])
    assert "9999999999" not in got
    assert set(got) == {"5919834330", "5919834331"}


def test_page_versions_empty_input_makes_no_request(confluence, http):
    assert confluence.page_versions([]) == {}
    assert http.calls == []


def test_page_versions_batches_over_250(confluence, http):
    ids = [str(100000 + i) for i in range(600)]

    def respond(req):
        from urllib.parse import parse_qs, urlparse

        asked = parse_qs(urlparse(req.full_url).query)["id"]
        return {
            "results": [
                {"id": pid, "version": {"number": int(pid) % 7 + 1}} for pid in asked
            ]
        }

    for _ in range(3):
        http.add_handler(respond)

    got = confluence.page_versions(ids)

    assert len(http.calls) == 3
    sizes = [len(http.query(i)["id"]) for i in range(3)]
    assert sizes == [250, 250, 100]
    assert http.query(0)["id"][0] == ids[0]
    assert http.query(2)["id"][-1] == ids[-1]
    assert len(got) == 600
    assert got[ids[0]] == int(ids[0]) % 7 + 1


def test_page_versions_normalizes_int_ids_from_response(confluence, http):
    http.add_json({"results": [{"id": 12345, "version": {"number": 4}}]})
    assert confluence.page_versions(["12345"]) == {"12345": 4}


def test_page_versions_skips_entries_without_version(confluence, http):
    http.add_json(
        {"results": [{"id": "1", "version": {"number": 2}}, {"id": "2"}]}
    )
    assert confluence.page_versions(["1", "2"]) == {"1": 2}


def test_page_versions_raises_api_error(confluence, http):
    http.add_error(500, b"server exploded")
    with pytest.raises(ApiError) as excinfo:
        confluence.page_versions(["1"])
    assert excinfo.value.status == 500
    assert excinfo.value.path == "/wiki/api/v2/pages"
    assert TOKEN not in str(excinfo.value)
