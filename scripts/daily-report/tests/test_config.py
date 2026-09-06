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


# --- [notify] ------------------------------------------------------------

NOTIFY_TOML = SAMPLE_TOML + """
[notify]
channel = "slack"
slack_target = "U0000000000"
"""


def test_load_config_carries_the_notify_table(tmp_path):
    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NOTIFY_TOML))

    assert cfg.notify == {"channel": "slack", "slack_target": "U0000000000"}


def test_load_config_without_notify_is_an_empty_dict(tmp_path):
    cfg = cfgmod.load_config(write(tmp_path / "config.toml", SAMPLE_TOML))

    assert cfg.notify == {}
    # 기존 필드는 그대로다
    assert cfg.site == "example.atlassian.net"
    assert cfg.parked_statuses == ["Ready to Deploy", "QA 대기"]
    assert cfg.daily_dir == cfg.vault / "daily"


def test_notify_table_is_not_shared_between_configs(tmp_path):
    a = cfgmod.load_config(write(tmp_path / "a.toml", SAMPLE_TOML))
    b = cfgmod.load_config(write(tmp_path / "b.toml", SAMPLE_TOML))

    a.notify["channel"] = "osascript"

    assert b.notify == {}


def test_bundled_config_declares_a_notify_channel():
    cfg = cfgmod.load_config()
    assert cfg.notify.get("channel") == "slack"
    assert cfg.notify.get("slack_target")


# --- 개인 값의 env 폴백 ---------------------------------------------------

SITE_ENV = "ATLASSIAN_SITE"
EMAIL_ENV = "ATLASSIAN_EMAIL"
SLACK_TARGET_ENV = "SLACK_TARGET"

# site·email 이 없는 커밋 가능한 config. 개인 값은 env 파일에서 온다.
NO_IDENTITY_TOML = """
vault = "~/vault-root/projects"
parked_statuses = ["Ready to Deploy"]
qa_projects = ["WPQ", "WV2Q"]
qa_lookback_days = 7
repos = ["~/GitHub/a"]

[notify]
channel = "slack"
"""


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    """ENV_FILE/CONFIG_FILE 을 tmp 로 돌리고 관련 환경변수를 비운다."""
    env_file = tmp_path / "daily-track.env"
    conf_file = tmp_path / "config"
    monkeypatch.setattr(cfgmod, "ENV_FILE", env_file)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", conf_file)
    for key in (TOKEN_ENV, SITE_ENV, EMAIL_ENV, SLACK_TARGET_ENV):
        monkeypatch.delenv(key, raising=False)
    return env_file, conf_file


def test_load_config_reads_site_and_email_from_env_file(tmp_path, env_files):
    env_file, _ = env_files
    write(env_file, f"{SITE_ENV}=env.atlassian.net\n{EMAIL_ENV}=env@example.com\n")

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))

    assert cfg.site == "env.atlassian.net"
    assert cfg.email == "env@example.com"


def test_load_config_strips_scheme_from_env_site(tmp_path, env_files):
    env_file, _ = env_files
    write(
        env_file,
        f"{SITE_ENV}=https://env.atlassian.net/\n{EMAIL_ENV}=env@example.com\n",
    )

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))

    assert cfg.site == "env.atlassian.net"


def test_load_config_reads_identity_from_environment(tmp_path, env_files, monkeypatch):
    monkeypatch.setenv(SITE_ENV, "http://shell.atlassian.net")
    monkeypatch.setenv(EMAIL_ENV, "shell@example.com")

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))

    assert cfg.site == "shell.atlassian.net"
    assert cfg.email == "shell@example.com"


def test_load_config_prefers_toml_over_env(tmp_path, env_files):
    env_file, _ = env_files
    write(env_file, f"{SITE_ENV}=env.atlassian.net\n{EMAIL_ENV}=env@example.com\n")

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", SAMPLE_TOML))

    assert cfg.site == "example.atlassian.net"
    assert cfg.email == "me@example.com"


def test_load_config_raises_when_site_missing_everywhere(tmp_path, env_files):
    with pytest.raises(KeyError) as excinfo:
        cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))
    assert "site" in str(excinfo.value)


def test_load_config_raises_when_email_missing_everywhere(tmp_path, env_files):
    env_file, _ = env_files
    write(env_file, f"{SITE_ENV}=env.atlassian.net\n")

    with pytest.raises(KeyError) as excinfo:
        cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))
    assert "email" in str(excinfo.value)


def test_load_config_fills_slack_target_from_env(tmp_path, env_files):
    env_file, _ = env_files
    write(
        env_file,
        f"{SITE_ENV}=env.atlassian.net\n{EMAIL_ENV}=env@example.com\n"
        f"{SLACK_TARGET_ENV}=U0ENVTARGET\n",
    )

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NO_IDENTITY_TOML))

    assert cfg.notify == {"channel": "slack", "slack_target": "U0ENVTARGET"}


def test_load_config_prefers_toml_slack_target_over_env(tmp_path, env_files):
    env_file, _ = env_files
    write(env_file, f"{SLACK_TARGET_ENV}=U0ENVTARGET\n")

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", NOTIFY_TOML))

    assert cfg.notify["slack_target"] != "U0ENVTARGET"
    assert cfg.notify["slack_target"] in NOTIFY_TOML


def test_env_slack_target_does_not_invent_a_notify_table(tmp_path, env_files):
    """`[notify]` 가 없으면 알림을 안 쓰겠다는 뜻이다. env 로 되살리지 않는다."""
    env_file, _ = env_files
    write(env_file, f"{SLACK_TARGET_ENV}=U0ENVTARGET\n")

    cfg = cfgmod.load_config(write(tmp_path / "config.toml", SAMPLE_TOML))

    assert cfg.notify == {}


def test_example_config_has_no_personal_values():
    """커밋되는 템플릿에 실제 개인 값이 들어가면 안 된다.

    값을 리터럴로 적으면 이 파일이 곧 유출 경로가 된다. 로컬 설정에서 읽어
    비교한다.
    """
    text = cfgmod.DEFAULT_CONFIG.with_name("config.example.toml").read_text("utf-8")
    cfg = cfgmod.load_config()

    for leaked in (cfg.site, cfg.email, cfg.notify.get("slack_target")):
        if leaked:
            assert str(leaked) not in text
