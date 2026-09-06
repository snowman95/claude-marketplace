"""Jira / Confluence REST clients (stdlib only).

Credentials live in the Authorization header and never appear in URLs or in
ApiError, so error text is always safe to print.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60
BATCH_SIZE = 250
BODY_LIMIT = 300


class ApiError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        self.status = status
        self.path = path
        self.body = body
        super().__init__(f"{status} {path} :: {body}")


class _Client:
    def __init__(self, base: str, email: str, token: str):
        self._base = base
        self._auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base={self._base!r})"

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._auth}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read()[:BODY_LIMIT].decode(errors="replace")
            # Full URL path (query stripped): `/wiki/...` for Confluence, and no
            # room for a credential to ride along in it.
            raise ApiError(e.code, urllib.parse.urlparse(url).path, body) from None


class JiraClient(_Client):
    def __init__(self, site: str, email: str, token: str):
        super().__init__(f"https://{site}", email, token)

    def search(self, jql: str, fields: list[str], max_results: int = 100) -> list[dict]:
        data = self.get(
            "/rest/api/3/search/jql",
            {"jql": jql, "maxResults": max_results, "fields": ",".join(fields)},
        )
        return data.get("issues", [])


class ConfluenceClient(_Client):
    def __init__(self, site: str, email: str, token: str):
        super().__init__(f"https://{site}/wiki", email, token)

    def page_versions(self, ids: list[str]) -> dict[str, int]:
        """{page_id: version number}. Ids the API does not return are omitted."""
        out: dict[str, int] = {}
        ids = [str(i) for i in ids]
        for i in range(0, len(ids), BATCH_SIZE):
            data = self.get(
                "/api/v2/pages",
                {"id": ids[i:i + BATCH_SIZE], "limit": BATCH_SIZE},
            )
            for page in data.get("results", []):
                number = (page.get("version") or {}).get("number")
                if number is not None:
                    out[str(page["id"])] = number
        return out
