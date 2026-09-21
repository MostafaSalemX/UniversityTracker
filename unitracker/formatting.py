"""Render Alerts as Telegram HTML."""
from __future__ import annotations

import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .checker import Alert

MAX_LEN = 4000
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub("", s))).strip()


def format_due(ts: int, tz_name: str) -> str:
    dt = datetime.fromtimestamp(ts, ZoneInfo(tz_name))
    return f"{dt:%a} {dt.day} {dt:%b}, {dt:%H:%M}"


def format_remaining(seconds: int) -> str:
    if seconds <= 24 * 3600:
        n = max(1, math.ceil(seconds / 3600))
        return f"in {n} hour" + ("" if n == 1 else "s")
    n = math.ceil(seconds / 86400)
    return f"in {n} day" + ("" if n == 1 else "s")


def _link(url: str) -> str:
    return f'\n<a href="{html.escape(url, quote=True)}">Open</a>' if url else ""


def format_alert(a: Alert, tz_name: str) -> str:
    e = html.escape
    if a.kind == "live":
        text = f"✅ Checker is live. Tracking {a.count} course(s)."
    elif a.kind == "new_course":
        text = f"🎓 Enrolled in <b>{e(a.title)}</b> ({e(a.course)})"
    elif a.kind == "new_deadline":
        text = f"📌 New deadline\n<b>{e(a.title)}</b> ({e(a.course)})\nDue <b>{format_due(a.due, tz_name)}</b>{_link(a.url)}"
    elif a.kind == "reminder":
        text = f"⏰ Due {format_remaining(a.remaining)}\n<b>{e(a.title)}</b> ({e(a.course)})\nDue <b>{format_due(a.due, tz_name)}</b>{_link(a.url)}"
    elif a.kind == "announcement":
        body = strip_html(a.body)
        if len(body) > 300:
            body = body[:300] + "…"
        text = f"📢 <b>{e(a.course)}</b>: {e(a.title)}"
        if body:
            text += f"\n{e(body)}"
        text += _link(a.url)
    elif a.kind == "new_content":
        bullets = "\n".join(f"• {e(name)} ({e(modname)})" for name, modname in a.items)
        text = f"📄 New in <b>{e(a.course)}</b>:\n{bullets}"
    elif a.kind == "grade":
        text = f"📊 <b>{e(a.course)}</b> — {e(a.title)}: <b>{e(a.body)}</b>"
    elif a.kind == "course_error":
        text = f"⚠️ Problem checking a course: {e(a.body)}"
    else:
        text = e(f"{a.kind}: {a.title} {a.body}")
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 1] + "…"
    return text
