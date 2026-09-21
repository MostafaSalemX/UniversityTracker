"""Render Alerts as Telegram HTML."""
from __future__ import annotations

import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .checker import Alert

MAX_LEN = 4000
_TAG = re.compile(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
_WS = re.compile(r"\s+")
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "td", "th", "table", "blockquote", "pre", "hr",
}


def _tag_repl(m: re.Match) -> str:
    return " " if m.group(1).lower() in _BLOCK_TAGS else ""


def strip_html(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(_tag_repl, s))).strip()


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


def _course(shortname: str) -> str:
    return f" ({html.escape(shortname)})" if shortname else ""


def _deadline(head: str, a: Alert, tz_name: str) -> str:
    return f"{head}\n<b>{html.escape(a.title)}</b>{_course(a.course)}\nDue <b>{format_due(a.due, tz_name)}</b>{_link(a.url)}"


def format_alert(a: Alert, tz_name: str) -> str:
    e = html.escape
    if a.kind == "live":
        text = f"✅ Checker is live. Tracking {a.count} course(s)."
    elif a.kind == "new_course":
        text = f"🎓 Enrolled in <b>{e(a.title)}</b>{_course(a.course)}"
    elif a.kind == "new_deadline":
        text = _deadline("📌 New deadline", a, tz_name)
    elif a.kind == "deadline_changed":
        text = _deadline("📌 Deadline changed", a, tz_name)
    elif a.kind == "reminder":
        text = _deadline(f"⏰ Due {format_remaining(a.remaining)}", a, tz_name)
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
