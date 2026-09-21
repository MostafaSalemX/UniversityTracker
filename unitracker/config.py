"""Settings loaded from environment variables (and .env locally)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv

REQUIRED = [
    "MOODLE_URL",
    "MOODLE_USERNAME",
    "MOODLE_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]


class ConfigError(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("Missing required environment variables: " + ", ".join(missing))


@dataclass(frozen=True)
class Settings:
    moodle_url: str
    moodle_username: str
    moodle_password: str
    telegram_bot_token: str
    telegram_chat_id: str
    state_path: str = "./state.json"
    tz_name: str = "Africa/Cairo"


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ after loading .env)."""
    if env is None:
        load_dotenv()
        env = os.environ
    values = {k: (env.get(k) or "").strip() for k in REQUIRED}
    missing = [k for k in REQUIRED if not values[k]]
    if missing:
        raise ConfigError(missing)
    return Settings(
        moodle_url=values["MOODLE_URL"].rstrip("/"),
        moodle_username=values["MOODLE_USERNAME"],
        moodle_password=values["MOODLE_PASSWORD"],
        telegram_bot_token=values["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=values["TELEGRAM_CHAT_ID"],
        state_path=(env.get("STATE_PATH") or "./state.json").strip(),
        tz_name=(env.get("TZ_NAME") or "Africa/Cairo").strip(),
    )
