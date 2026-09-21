"""Entry point: python -m unitracker [--dry-run]"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import traceback

from . import config, state as state_mod
from .checker import check
from .formatting import format_alert
from .moodle import MoodleClient
from .snapshot import build_snapshot
from .telegram import TelegramError, send_message

SEND_INTERVAL = 1.0  # seconds between consecutive messages


def _try_send(sender, token: str, chat_id: str, text: str) -> None:
    try:
        sender(token, chat_id, text)
    except Exception as exc:  # best effort only
        print(f"telegram send failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def _utf8_console() -> None:
    """Windows consoles default to a legacy code page; emoji would crash print()."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, io.UnsupportedOperation):
            pass


def run(argv=None, *, env=None, now=None, client_factory=None, sender=None, sleep=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="unitracker")
    parser.add_argument("--dry-run", action="store_true", help="print alerts instead of sending; don't save state")
    args = parser.parse_args(argv)
    client_factory = client_factory if client_factory is not None else MoodleClient
    sender = sender if sender is not None else send_message
    sleep = sleep if sleep is not None else time.sleep

    try:
        settings = config.load(env)
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        src = env if env is not None else os.environ
        tok, chat = src.get("TELEGRAM_BOT_TOKEN"), src.get("TELEGRAM_CHAT_ID")
        if tok and chat:
            text = "⚠️ Checker misconfigured: missing " + ", ".join(exc.missing)
            if args.dry_run:
                print(f"[dry-run] would send: {text}")
            else:
                _try_send(sender, tok, chat, text)
        return 2

    now = now if now is not None else int(time.time())
    state = state_mod.State()

    try:
        state = state_mod.load(settings.state_path)
        client = client_factory(settings.moodle_url)
        client.login(settings.moodle_username, settings.moodle_password)
        userid = int(client.site_info()["userid"])
        snapshot = build_snapshot(client, userid, now)
        alerts, new_state = check(snapshot, state, now)
        messages = [format_alert(a, settings.tz_name) for a in alerts]
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        text = f"⚠️ Checker failed: {type(exc).__name__}: {str(exc)[:200]}"
        if not state.failing:
            if args.dry_run:
                print(f"[dry-run] would send: {text}")
            else:
                _try_send(sender, settings.telegram_bot_token, settings.telegram_chat_id, text)
        state.failing = True
        if not args.dry_run:
            state_mod.save(state, settings.state_path)
        return 1

    if state.failing:
        messages.insert(0, "✅ Checker recovered.")
    new_state.failing = False

    if args.dry_run:
        print("\n---\n".join(messages) if messages else "(no alerts)")
        return 0

    try:
        for i, text in enumerate(messages):
            if i:
                sleep(SEND_INTERVAL)  # stay under Telegram's per-chat rate limit
            sender(settings.telegram_bot_token, settings.telegram_chat_id, text)
    except TelegramError as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    state_mod.save(new_state, settings.state_path)
    print(f"OK: {len(messages)} alert(s) sent")
    return 0


if __name__ == "__main__":
    sys.exit(run())
