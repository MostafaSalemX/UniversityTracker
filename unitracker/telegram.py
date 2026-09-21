"""Send a message via the Telegram Bot API."""
from __future__ import annotations

import time

import requests

MAX_429_RETRIES = 3


class TelegramError(Exception):
    pass


def _post(session, url: str, body: dict, token: str) -> tuple[int, dict]:
    try:
        resp = session.post(url, json=body, timeout=30)
    except requests.RequestException as exc:
        raise TelegramError(f"{type(exc).__name__}: {str(exc).replace(token, '<token>')}") from None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    return resp.status_code, payload if isinstance(payload, dict) else {}


def send_message(token: str, chat_id: str, text: str, session=None, sleep=time.sleep) -> None:
    """Send one HTML message. Waits out flood control (429) up to MAX_429_RETRIES
    times, honouring Telegram's retry_after; falls back to plain text once if
    Telegram rejects the HTML markup."""
    session = session or requests.Session()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    retries = 0
    while True:
        status, payload = _post(session, url, body, token)
        if status < 300 and payload.get("ok"):
            return
        description = str(payload.get("description", "unknown error"))
        if status == 429 and retries < MAX_429_RETRIES:
            retries += 1
            sleep((payload.get("parameters") or {}).get("retry_after", 1))
            continue
        if status == 400 and "parse entities" in description and "parse_mode" in body:
            body = {k: v for k, v in body.items() if k != "parse_mode"}
            continue
        raise TelegramError(f"HTTP {status}: {description}")
