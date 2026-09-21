import pytest
from unitracker import config

FULL = {
    "MOODLE_URL": "https://egylms.arabou.edu.kw/",
    "MOODLE_USERNAME": "u",
    "MOODLE_PASSWORD": "p",
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_CHAT_ID": "c",
}


def test_load_full_env_and_defaults():
    s = config.load(FULL)
    assert s.moodle_url == "https://egylms.arabou.edu.kw"  # trailing slash stripped
    assert s.moodle_username == "u"
    assert s.telegram_chat_id == "c"
    assert s.state_path == "./state.json"
    assert s.tz_name == "Africa/Cairo"


def test_load_optional_overrides():
    s = config.load({**FULL, "STATE_PATH": "/data/state.json", "TZ_NAME": "UTC"})
    assert s.state_path == "/data/state.json"
    assert s.tz_name == "UTC"


def test_whitespace_only_optionals_fall_back_to_defaults():
    s = config.load({**FULL, "STATE_PATH": "   ", "TZ_NAME": "\t"})
    assert s.state_path == "./state.json"
    assert s.tz_name == "Africa/Cairo"
    assert config.load({**FULL, "TZ_NAME": " UTC "}).tz_name == "UTC"


def test_missing_vars_raise_with_names():
    env = {k: v for k, v in FULL.items() if k not in ("MOODLE_PASSWORD", "TELEGRAM_CHAT_ID")}
    with pytest.raises(config.ConfigError) as ei:
        config.load(env)
    assert ei.value.missing == ["MOODLE_PASSWORD", "TELEGRAM_CHAT_ID"]
    assert "MOODLE_PASSWORD" in str(ei.value)


def test_blank_counts_as_missing():
    with pytest.raises(config.ConfigError) as ei:
        config.load({**FULL, "MOODLE_URL": "  "})
    assert ei.value.missing == ["MOODLE_URL"]
