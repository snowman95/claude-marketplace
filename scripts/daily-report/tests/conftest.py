"""Shared test helpers: sys.path wiring, a fake urlopen, and a spawn guard."""
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fixture(name):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeHTTP:
    """Queue of canned responses; records every Request that goes through."""

    def __init__(self):
        self.calls = []
        self._queue = []

    def add_json(self, payload):
        self._queue.append(("json", payload))

    def add_error(self, code, body=b"boom"):
        self._queue.append(("error", (code, body)))

    def add_handler(self, fn):
        """fn(request) -> payload dict, evaluated at call time."""
        self._queue.append(("fn", fn))

    # --- introspection helpers -------------------------------------------
    def query(self, index=0):
        url = self.calls[index].full_url
        return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    def path(self, index=0):
        return urllib.parse.urlparse(self.calls[index].full_url).path

    def headers(self, index=0):
        return {k.lower(): v for k, v in self.calls[index].headers.items()}

    # --- urlopen replacement ---------------------------------------------
    def __call__(self, req, timeout=None):
        self.calls.append(req)
        if not self._queue:
            raise AssertionError(f"unexpected request: {req.full_url}")
        kind, value = self._queue.pop(0)
        if kind == "fn":
            kind, value = "json", value(req)
        if kind == "error":
            code, body = value
            raise urllib.error.HTTPError(
                req.full_url, code, "err", {}, io.BytesIO(body)
            )
        return FakeResponse(json.dumps(value).encode())


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


# ---------------------------------------------------------------------------
# spawn 차단
# ---------------------------------------------------------------------------

class FakeProcess:
    def __init__(self, pid):
        self.pid = pid


class SpawnRecorder:
    """`subprocess.Popen` 자리에 꽂는다. 기록만 하고 아무것도 띄우지 않는다."""

    def __init__(self):
        self.calls = []
        self.pid = 4242
        self.error = None

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        return FakeProcess(self.pid)

    @property
    def argvs(self):
        return [call["argv"] for call in self.calls]


@pytest.fixture(autouse=True)
def spawns(monkeypatch):
    """**실제 프로세스를 띄우지 않는다.**

    폴링의 결정 자동 처리는 기본 켜짐이라, 픽스처가 없으면 테스트가 실제
    `claude -p` 를 띄울 수 있다. autouse 로 전 테스트에 깔아 그 경로를 막는다.
    """
    recorder = SpawnRecorder()
    monkeypatch.setattr(subprocess, "Popen", recorder)
    return recorder
