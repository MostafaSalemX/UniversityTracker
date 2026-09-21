"""Pure diff: (snapshot, previous state, now) -> (alerts, new state)."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .snapshot import Snapshot
from .state import EventState, State

H72 = 72 * 3600
H24 = 24 * 3600
PRUNE_AFTER = 30 * 86400


@dataclass
class Alert:
    kind: str
    course: str = ""
    title: str = ""
    body: str = ""
    url: str = ""
    due: int | None = None
    remaining: int | None = None
    items: list[tuple[str, str]] = field(default_factory=list)
    count: int = 0


def check(snapshot: Snapshot, state: State, now: int) -> tuple[list[Alert], State]:
    s = copy.deepcopy(state)
    first = not s.initialized
    alerts: list[Alert] = []

    if first:
        alerts.append(Alert(kind="live", count=len(snapshot.courses)))
    alerts += [Alert(kind="course_error", body=msg) for msg in snapshot.errors]

    # Courses
    for c in snapshot.courses:
        key = str(c.id)
        if key not in s.courses and not first:
            alerts.append(Alert(kind="new_course", course=c.shortname, title=c.fullname))
        s.courses[key] = c.shortname

    # Deadlines + reminders
    new_deadlines: list[Alert] = []
    reminders: list[Alert] = []
    for e in snapshot.events:
        key = str(e.id)
        remaining = e.due - now
        if key not in s.events:
            es = EventState(due=e.due)
            if remaining <= H72:
                es.reminded_3d = True
            if remaining <= H24:
                es.reminded_24h = True
            s.events[key] = es
            if not first:
                new_deadlines.append(Alert(kind="new_deadline", course=e.course_shortname, title=e.name, url=e.url, due=e.due))
            continue
        es = s.events[key]
        es.due = e.due
        if 0 < remaining <= H24 and not es.reminded_24h:
            es.reminded_24h = True
            es.reminded_3d = True
            reminders.append(Alert(kind="reminder", course=e.course_shortname, title=e.name, url=e.url, due=e.due, remaining=remaining))
        elif 0 < remaining <= H72 and not es.reminded_3d:
            es.reminded_3d = True
            reminders.append(Alert(kind="reminder", course=e.course_shortname, title=e.name, url=e.url, due=e.due, remaining=remaining))
    for key in [k for k, es in s.events.items() if es.due < now - PRUNE_AFTER]:
        del s.events[key]
    alerts += new_deadlines + reminders

    # Announcements
    for d in snapshot.discussions:
        key = str(d.id)
        if key not in s.discussions and not first:
            alerts.append(Alert(kind="announcement", course=d.course_shortname, title=d.subject, body=d.message_html, url=d.url))
        s.discussions.add(key)

    # New content, grouped per course in snapshot order
    grouped: dict[str, list[tuple[str, str]]] = {}
    for m in snapshot.modules:
        key = str(m.id)
        if key not in s.modules and not first:
            grouped.setdefault(m.course_shortname, []).append((m.name, m.modname))
        s.modules.add(key)
    alerts += [Alert(kind="new_content", course=course, items=items) for course, items in grouped.items()]

    # Grades
    for g in snapshot.grades:
        if g.graderaw is None:
            continue
        key, val = str(g.item_id), str(g.graderaw)
        if s.grades.get(key) != val and not first:
            alerts.append(Alert(kind="grade", course=g.course_shortname, title=g.itemname, body=g.gradeformatted))
        s.grades[key] = val

    s.initialized = True
    return alerts, s
