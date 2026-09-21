"""Send a message via the Telegram Bot API."""
from __future__ import annotations

import requests


class TelegramError(Exception):
    pass


def send_message(token: str, chat_id: str, text: str, session=None) -> None:
    session = session or requests.Session()
    resp = session.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 300 or not payload.get("ok"):
        raise TelegramError(f"HTTP {resp.status_code}: {payload.get('description', 'unknown error')}")
