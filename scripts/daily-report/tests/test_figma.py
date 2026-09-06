import pytest
from conftest import fixture

from atlassian import ApiError
from figma import FigmaClient

TOKEN = "figd_s3cr3t"


@pytest.fixture
def client():
    return FigmaClient(TOKEN)


def test_last_modified_returns_iso_timestamp(client, http):
    http.add_json(fixture("figma_file.json"))

    assert client.last_modified("AbC123") == "2026-08-20T04:11:00Z"

    url = http.calls[0].full_url
    assert url.startswith("https://api.figma.com/v1/files/AbC123")
    assert http.query()["depth"] == ["1"]
    assert http.headers()["x-figma-token"] == TOKEN
    assert "authorization" not in http.headers()


def test_last_modified_missing_field(client, http):
    http.add_json({"name": "no timestamp"})
    assert client.last_modified("AbC123") is None


def test_last_modified_quotes_file_key(client, http):
    http.add_json(fixture("figma_file.json"))
    client.last_modified("a b/c")
    assert " " not in http.calls[0].full_url
    assert http.calls[0].full_url.startswith("https://api.figma.com/v1/files/a%20b%2Fc")


@pytest.mark.parametrize("code", [403, 404])
def test_last_modified_returns_none_on_403_404(client, http, code):
    http.add_error(code, b'{"err":"Not found"}')
    assert client.last_modified("AbC123") is None


@pytest.mark.parametrize("code", [400, 429, 500, 503])
def test_last_modified_raises_api_error(client, http, code):
    http.add_error(code, b'{"err":"boom"}')
    with pytest.raises(ApiError) as excinfo:
        client.last_modified("AbC123")
    err = excinfo.value
    assert err.status == code
    assert err.path == "/v1/files/AbC123"
    assert "boom" in err.body


def test_error_never_leaks_token(client, http):
    http.add_error(500, b"boom")
    with pytest.raises(ApiError) as excinfo:
        client.last_modified("AbC123")
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in excinfo.value.body
    assert TOKEN not in repr(client)
