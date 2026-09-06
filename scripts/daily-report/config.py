"""Configuration and credential loading for daily-report.

Tokens are read here and nowhere else. They are never printed, logged, or put
into exception messages.

`config.toml` 은 공개 저장소에 커밋되지 않는다(gitignore). 그래도 개인 값
(site·email·slack_target)은 config 에 없어도 되게 두고, 없으면 env 파일에서
읽는다 — 커밋 가능한 `config.example.toml` 만으로 동작하게 하려는 것이다.
"""
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.toml")
ENV_FILE = Path("~/.config/atlassian/daily-track.env").expanduser()
CONFIG_FILE = Path("~/.config/atlassian/config").expanduser()
CLAUDE_JSON = Path("~/.claude.json").expanduser()

TOKEN_KEY = "ATLASSIAN_API_TOKEN"
SITE_KEY = "ATLASSIAN_SITE"
EMAIL_KEY = "ATLASSIAN_EMAIL"
SLACK_TARGET_KEY = "SLACK_TARGET"
FIGMA_SERVER = "figma-console"
FIGMA_TOKEN_KEY = "FIGMA_ACCESS_TOKEN"


@dataclass(frozen=True)
class Config:
    vault: Path
    site: str
    email: str
    parked_statuses: list[str]
    qa_projects: list[str]
    qa_lookback_days: int
    repos: list[Path]
    notify: dict = field(default_factory=dict)

    @property
    def daily_dir(self) -> Path:
        return self.vault / "daily"


def _path(value: str) -> Path:
    return Path(str(value)).expanduser()


def load_config(path: Path | None = None) -> Config:
    path = Path(path) if path is not None else DEFAULT_CONFIG
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(
        vault=_path(raw["vault"]),
        site=_host(_personal(raw, "site", SITE_KEY)),
        email=_personal(raw, "email", EMAIL_KEY),
        parked_statuses=list(raw.get("parked_statuses", [])),
        qa_projects=list(raw.get("qa_projects", [])),
        qa_lookback_days=int(raw.get("qa_lookback_days", 7)),
        repos=[_path(r) for r in raw.get("repos", [])],
        notify=_notify(raw),
    )


def _personal(raw: dict, key: str, env_key: str) -> str:
    """config.toml 값 > env 파일/환경변수. 둘 다 없으면 예전처럼 KeyError."""
    value = str(raw.get(key) or "").strip()
    if value:
        return value
    value = _env_value(env_key) or ""
    if value:
        return value
    raise KeyError(key)


def _notify(raw: dict) -> dict:
    """`[notify]` 가 선언된 경우에만 slack_target 을 env 로 보충한다.

    테이블 자체가 없으면 알림을 쓰지 않겠다는 뜻이다. env 에 값이 있다고
    알림을 되살리지 않는다.
    """
    table = raw.get("notify")
    if not table:
        return {}
    settings = dict(table)
    if not str(settings.get("slack_target") or "").strip():
        target = _env_value(SLACK_TARGET_KEY)
        if target:
            settings["slack_target"] = target
    return settings


def _env_value(key: str) -> str | None:
    """$KEY -> daily-track.env -> config. 없으면 None."""
    value = os.environ.get(key)
    if value:
        return value
    for path in (ENV_FILE, CONFIG_FILE):
        value = _read_key(path, key=key)
        if value:
            return value
    return None


def _host(value: str) -> str:
    """클라이언트는 스킴 없는 호스트를 기대한다. env 에 URL 이 와도 벗긴다."""
    value = value.strip()
    for scheme in ("https://", "http://"):
        if value.lower().startswith(scheme):
            value = value[len(scheme):]
            break
    return value.rstrip("/")


def _read_key(path: Path, key: str) -> str | None:
    """One value out of a `KEY=value` file. Never returns the whole file."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip("'\"") or None
    except OSError:
        return None
    return None


def load_token(email: str) -> str:
    token = os.environ.get(TOKEN_KEY)
    if token:
        return token
    for path in (ENV_FILE, CONFIG_FILE):
        token = _read_key(path, key=TOKEN_KEY)
        if token:
            return token
    raise RuntimeError(
        f"No Atlassian API token for {email}. Set ${TOKEN_KEY}, "
        f"or add a `{TOKEN_KEY}=` line to {ENV_FILE} or {CONFIG_FILE}."
    )


def load_figma_token() -> str | None:
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    server = (data.get("mcpServers") or {}).get(FIGMA_SERVER) or {}
    return (server.get("env") or {}).get(FIGMA_TOKEN_KEY) or None
