import json
from pathlib import Path

import pytest

import config as cfgmod

TOKEN_ENV = "ATLASSIAN_API_TOKEN"


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def token_files(tmp_path, monkeypatch):
    """Point both token files at tmp_path; neither exists yet."""
    env_file = tmp_path / "daily-track.env"
    conf_file = tmp_path / "config"
    monkeypatch.setattr(cfgmod, "ENV_FILE", env_file)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", conf_file)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    return env_file, conf_file


# --- load_token ----------------------------------------------------------


def test_load_token_prefers_environment(token_files, monkeypatch):
    env_file, conf_file = token_files
    write(env_file, f"{TOKEN_ENV}=from-env-file\n")
    write(conf_file, f"{TOKEN_ENV}=from-config\n")
    monkeypatch.setenv(TOKEN_ENV, "from-environ")

    assert cfgmod.load_token("me@example.com") == "from-environ"


def test_load_token_falls_back_to_env_file(token_files):
    env_file, conf_file = token_files
    write(
        env_file,
        "# comment\n\nATLASSIAN_SITE=example.atlassian.net\n"
        f"{TOKEN_ENV} = from-env-file \n",
    )
    write(conf_file, f"{TOKEN_ENV}=from-config\n")

    assert cfgmod.load_token("me@example.com") == "from-env-file"


def test_load_token_falls_back_to_config(token_files):
    env_file, conf_file = token_files
    write(conf_file, f"# note\n{TOKEN_ENV}=from-config\n")

    assert not env_file.exists()
    assert cfgmod.load_token("me@example.com") == "from-config"


def test_load_token_ignores_blank_value(token_files):
    env_file, conf_file = token_files
    write(env_file, f"{TOKEN_ENV}=\n")
    write(conf_file, f"{TOKEN_ENV}=from-config\n")

    assert cfgmod.load_token("me@example.com") == "from-config"


def test_load_token_raises_when_nothing_available(token_files):
    with pytest.raises(RuntimeError) as excinfo:
        cfgmod.load_token("me@example.com")
    assert TOKEN_ENV in str(excinfo.value)


def test_load_token_error_does_not_leak_other_secrets(token_files, monkeypatch):
    env_file, _ = token_files
    write(env_file, "SOMETHING_ELSE=super-secret-value\n")
    with pytest.raises(RuntimeError) as excinfo:
        cfgmod.load_token("me@example.com")
    assert "super-secret-value" not in str(excinfo.value)


# --- load_config ---------------------------------------------------------

SAMPLE_TOML = """
vault = "~/vault-root/projects"
site = "example.atlassian.net"
email = "me@example.com"
parked_statuses = ["Ready to Deploy", "QA 대기"]
qa_projects = ["WPQ", "WV2Q"]
qa_lookback_days = 7
repos = ["~/GitHub/a", "/abs/b"]
"""


def test_load_config_parses_toml_and_expands_tilde(tmp_path):
    path = write(tmp_path / "config.toml", SAMPLE_TOML)
    cfg = cfgmod.load_config(path)

    assert cfg.vault == Path.home() / "vault-root" / "projects"
    assert cfg.site == "example.atlassian.net"
    assert cfg.email == "me@example.com"
    assert cfg.parked_statuses == ["Ready to Deploy", "QA 대기"]
    assert cfg.qa_projects == ["WPQ", "WV2Q"]
    assert cfg.qa_lookback_days == 7
    assert cfg.repos == [Path.home() / "GitHub" / "a", Path("/abs/b")]


def test_load_config_daily_dir(tmp_path):
    cfg = cfgmod.load_config(write(tmp_path / "config.toml", SAMPLE_TOML))
    assert cfg.daily_dir == cfg.vault / "daily"


def test_load_config_is_frozen(tmp_path):
    cfg = cfgmod.load_config(write(tmp_path / "config.toml", SAMPLE_TOML))
    with pytest.raises(Exception):
        cfg.site = "other.atlassian.net"


def test_load_config_defaults_to_bundled_file():
    cfg = cfgmod.load_config()
    assert isinstance(cfg.vault, Path)
    assert cfg.site and "://" not in cfg.site
    assert isinstance(cfg.qa_lookback_days, int)
    assert all(isinstance(p, Path) for p in cfg.repos)


# --- load_figma_token ----------------------------------------------------


def test_load_figma_token_reads_claude_json(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "figma-console": {
                        "command": "npx",
                        "env": {"FIGMA_ACCESS_TOKEN": "figd_xyz", "OTHER": "1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfgmod, "CLAUDE_JSON", path)

    assert cfgmod.load_figma_token() == "figd_xyz"


def test_load_figma_token_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CLAUDE_JSON", tmp_path / "nope.json")
    assert cfgmod.load_figma_token() is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mcpServers": {}},
        {"mcpServers": {"figma-console": {}}},
        {"mcpServers": {"figma-console": {"env": {}}}},
        {"mcpServers": {"figma-console": {"env": {"FIGMA_ACCESS_TOKEN": ""}}}},
    ],
)
def test_load_figma_token_missing_key(tmp_path, monkeypatch, payload):
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cfgmod, "CLAUDE_JSON", path)
    assert cfgmod.load_figma_token() is None


def test_load_figma_token_bad_json(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(cfgmod, "CLAUDE_JSON", path)
    assert cfgmod.load_figma_token() is None
