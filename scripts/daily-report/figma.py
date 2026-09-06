"""Figma REST client (stdlib only).

The token travels in the X-Figma-Token header and is never echoed back.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from atlassian import ApiError

API_BASE = "https://api.figma.com"
TIMEOUT = 60
BODY_LIMIT = 300
SILENT_STATUSES = (403, 404)


class FigmaClient:
    def __init__(self, token: str):
        self._token = token

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def last_modified(self, file_key: str) -> str | None:
        """ISO8601 mtime of a file. None when the file is gone or unreadable."""
        path = f"/v1/files/{urllib.parse.quote(str(file_key), safe='')}"
        url = f"{API_BASE}{path}?" + urllib.parse.urlencode({"depth": 1})
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "X-Figma-Token": self._token},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in SILENT_STATUSES:
                return None
            body = e.read()[:BODY_LIMIT].decode(errors="replace")
            raise ApiError(e.code, path, body) from None
        return data.get("lastModified")
