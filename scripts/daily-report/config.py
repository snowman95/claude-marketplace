"""Configuration and credential loading for daily-report.

Tokens are read here and nowhere else. They are never printed, logged, or put
into exception messages.

설정 파일을 찾는 순서: ① $DAILY_REPORT_CONFIG 환경변수 ②
~/.config/atlassian/daily-report.toml (권장 — 플러그인 갱신 시 유실되지 않음)
③ 스크립트 옆 config.toml (기존 동작, 하위 호환).

`config.toml` 은 공개 저장소에 커밋되지 않는다(gitignore). 그래도 개인 값
(site·email·slack_target)은 config 에 없어도 되게 두고, 없으면 env 파일에서
읽는다 — 커밋 가능한 `config.example.toml` 만으로 동작하게 하려는 것이다.
"""
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# 플러그인 디렉토리 옆 config.toml (gitignore 대상, 하위 호환용 3번째 후보)
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.toml")
# 권장 경로: 플러그인 갱신 시 유실되지 않는 영구 위치
_XDG_CONFIG = Path("~/.config/atlassian/daily-report.toml").expanduser()

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
    watch: dict = field(default_factory=dict)
    heartbeat: dict = field(default_factory=dict)
    weekly: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)

    @property
    def daily_dir(self) -> Path:
        return self.vault / "daily"


def _path(value: str) -> Path:
    return Path(str(value)).expanduser()


def resolve_config_path(explicit: Path | None) -> Path:
    """설정 파일 경로를 아래 순서로 결정한다.

    1. ``explicit`` — 호출자가 명시적으로 전달한 경로
    2. ``$DAILY_REPORT_CONFIG`` 환경변수
    3. ``~/.config/atlassian/daily-report.toml`` (플러그인 갱신에도 유지)
    4. 스크립트 옆 ``config.toml`` (기존 동작, 하위 호환)

    하나도 존재하지 않으면 모든 후보를 메시지에 담아 FileNotFoundError 를 던진다.
    """
    tried: list[Path] = []

    if explicit is not None:
        p = Path(explicit).expanduser()
        tried.append(p)
        if p.exists():
            return p

    env = os.environ.get("DAILY_REPORT_CONFIG")
    if env:
        p = Path(env).expanduser()
        tried.append(p)
        if p.exists():
            return p

    for p in (_XDG_CONFIG, DEFAULT_CONFIG):
        if p not in tried:
            tried.append(p)
        if p.exists():
            return p

    raise FileNotFoundError(
        "daily-report 설정 파일을 찾을 수 없습니다. 아래 중 하나에 두세요:\n"
        + "\n".join(f"  {c}" for c in tried)
    )


def load_config(path: Path | None = None) -> Config:
    resolved = resolve_config_path(Path(path) if path is not None else None)
    with open(resolved, "rb") as f:
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
        watch=dict(raw.get("watch") or {}),
        heartbeat=dict(raw.get("heartbeat") or {}),
        weekly=dict(raw.get("weekly") or {}),
        decisions=dict(raw.get("decisions") or {}),
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
