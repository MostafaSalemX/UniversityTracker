"""Fetch everything we care about from Moodle into plain dataclasses."""
from __future__ import annotations

import html
from dataclasses import dataclass, field

from .moodle import MoodleClient, MoodleError


@dataclass(frozen=True)
class Course:
    id: int
    shortname: str
    fullname: str


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    course_shortname: str
    due: int
    url: str


@dataclass(frozen=True)
class Discussion:
    id: int
    course_shortname: str
    subject: str
    message_html: str
    url: str


@dataclass(frozen=True)
class Module:
    id: int
    course_shortname: str
    name: str
    modname: str
    url: str


@dataclass(frozen=True)
class Grade:
    item_id: int
    course_shortname: str
    itemname: str
    graderaw: float | None
    gradeformatted: str
    grademax: float | None


@dataclass
class Snapshot:
    courses: list[Course] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    discussions: list[Discussion] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    grades: list[Grade] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # "forums" | "<shortname>/<part>" -> message


def _text(value) -> str:
    """Moodle entity-escapes display strings (names, subjects, grades) before
    returning them; undo that here so formatting escapes exactly once."""
    return html.unescape(str(value)) if value else ""


def _num(value) -> float | None:
    return None if value is None else float(value)


def build_snapshot(client: MoodleClient, userid: int, now: int) -> Snapshot:
    snap = Snapshot()

    snap.courses = [
        Course(int(c["id"]), _text(c.get("shortname")), _text(c.get("fullname")))
        for c in client.courses(userid)
    ]
    names = {c.id: c.shortname for c in snap.courses}

    snap.events = [
        Event(
            int(e["id"]),
            _text(e.get("name")),
            _text((e.get("course") or {}).get("shortname")),
            int(e["timesort"]),
            e.get("url", ""),
        )
        for e in client.upcoming_events(timesortfrom=now)
    ]

    # Announcements: one forum-list call for all courses, then per-forum discussions.
    forums_by_course: dict[int, list[dict]] = {}
    if snap.courses:
        try:
            for f in client.news_forums(list(names)):
                forums_by_course.setdefault(int(f["course"]), []).append(f)
        except MoodleError as exc:
            snap.errors["forums"] = f"forums: {exc}"

    # Each per-course fetch is isolated so one failure doesn't hide the others.
    for course in snap.courses:
        try:
            for forum in forums_by_course.get(course.id, []):
                for d in client.discussions(int(forum["id"])):
                    did = int(d["discussion"])
                    snap.discussions.append(
                        Discussion(
                            did,
                            course.shortname,
                            _text(d.get("subject")),
                            d.get("message") or "",  # raw HTML; strip_html unescapes it
                            f"{client.base_url}/mod/forum/discuss.php?d={did}",
                        )
                    )
        except MoodleError as exc:
            snap.errors[f"{course.shortname}/discussions"] = f"{course.shortname} announcements: {exc}"
        try:
            for section in client.course_contents(course.id):
                for m in section.get("modules", []):
                    if m.get("uservisible") is False:
                        continue
                    snap.modules.append(
                        Module(int(m["id"]), course.shortname, _text(m.get("name")), m.get("modname", ""), m.get("url") or "")
                    )
        except MoodleError as exc:
            snap.errors[f"{course.shortname}/contents"] = f"{course.shortname} contents: {exc}"
        try:
            for g in client.grade_items(course.id, userid):
                if g.get("itemtype") in ("course", "category"):
                    continue
                snap.grades.append(
                    Grade(
                        int(g["id"]),
                        course.shortname,
                        _text(g.get("itemname")),
                        _num(g.get("graderaw")),
                        _text(g.get("gradeformatted")),
                        _num(g.get("grademax")),
                    )
                )
        except MoodleError as exc:
            snap.errors[f"{course.shortname}/grades"] = f"{course.shortname} grades: {exc}"

    return snap
