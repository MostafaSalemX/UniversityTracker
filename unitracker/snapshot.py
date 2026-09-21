"""Fetch everything we care about from Moodle into plain dataclasses."""
from __future__ import annotations

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
    errors: list[str] = field(default_factory=list)


def build_snapshot(client: MoodleClient, userid: int, now: int) -> Snapshot:
    snap = Snapshot()

    snap.courses = [
        Course(int(c["id"]), c.get("shortname", ""), c.get("fullname", ""))
        for c in client.courses(userid)
    ]
    names = {c.id: c.shortname for c in snap.courses}

    snap.events = [
        Event(
            int(e["id"]),
            e.get("name", ""),
            (e.get("course") or {}).get("shortname", ""),
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
            snap.errors.append(f"forums: {exc}")

    for course in snap.courses:
        try:
            for forum in forums_by_course.get(course.id, []):
                for d in client.discussions(int(forum["id"])):
                    did = int(d["discussion"])
                    snap.discussions.append(
                        Discussion(
                            did,
                            course.shortname,
                            d.get("subject", ""),
                            d.get("message", "") or "",
                            f"{client.base_url}/mod/forum/discuss.php?d={did}",
                        )
                    )
            for section in client.course_contents(course.id):
                for m in section.get("modules", []):
                    if m.get("uservisible") is False:
                        continue
                    snap.modules.append(
                        Module(int(m["id"]), course.shortname, m.get("name", ""), m.get("modname", ""), m.get("url") or "")
                    )
            for g in client.grade_items(course.id, userid):
                if g.get("itemtype") in ("course", "category"):
                    continue
                snap.grades.append(
                    Grade(
                        int(g["id"]),
                        course.shortname,
                        g.get("itemname") or "",
                        g.get("graderaw"),
                        str(g.get("gradeformatted") or ""),
                        g.get("grademax"),
                    )
                )
        except MoodleError as exc:
            snap.errors.append(f"{course.shortname}: {exc}")

    return snap
