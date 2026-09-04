"""Configuration and credential loading for daily-report.

Tokens are read here and nowhere else. They are never printed, logged, or put
into exception messages.
"""
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.toml")
ENV_FILE = Path("~/.config/atlassian/daily-track.env").expanduser()
CONFIG_FILE = Path("~/.config/atlassian/config").expanduser()
CLAUDE_JSON = Path("~/.claude.json").expanduser()

TOKEN_KEY = "ATLASSIAN_API_TOKEN"
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
        site=raw["site"],
        email=raw["email"],
        parked_statuses=list(raw.get("parked_statuses", [])),
        qa_projects=list(raw.get("qa_projects", [])),
        qa_lookback_days=int(raw.get("qa_lookback_days", 7)),
        repos=[_path(r) for r in raw.get("repos", [])],
    )


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
