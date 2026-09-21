import copy
from unitracker.checker import H24, H72, PRUNE_AFTER, Alert, check
from unitracker.snapshot import Course, Discussion, Event, Grade, Module, Snapshot
from unitracker.state import EventState, State

NOW = 1_759_500_000


def kinds(alerts):
    return [a.kind for a in alerts]


def base_snapshot():
    return Snapshot(
        courses=[Course(101, "TM112", "Intro to Computing")],
        events=[Event(501, "TMA01 is due", "TM112", NOW + 10 * 86400, "https://lms/a")],
        discussions=[Discussion(701, "TM112", "Welcome", "<p>Hi</p>", "https://lms/d")],
        modules=[Module(9002, "TM112", "Week 1 slides", "resource", "https://lms/m")],
        grades=[Grade(401, "TM112", "TMA01", 85.0, "85.00", 100.0)],
    )


def seeded_state():
    _, s = check(base_snapshot(), State(), NOW)
    return s


def test_first_run_seeds_silently():
    alerts, s = check(base_snapshot(), State(), NOW)
    assert alerts == [Alert(kind="live", count=1)]
    assert s.initialized is True
    assert s.courses == {"101": "TM112"}
    assert s.events == {"501": EventState(due=NOW + 10 * 86400)}
    assert s.discussions == {"701"} and s.modules == {"9002"} and s.grades == {"401": "85.0"}


def test_first_run_with_zero_courses():
    alerts, s = check(Snapshot(), State(), NOW)
    assert alerts == [Alert(kind="live", count=0)] and s.initialized


def test_unchanged_snapshot_yields_nothing():
    s = seeded_state()
    alerts, s2 = check(base_snapshot(), s, NOW + 3600)
    assert alerts == [] and s2 == s


def test_check_does_not_mutate_input_state():
    s = seeded_state()
    before = copy.deepcopy(s)
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Stats"))
    check(snap, s, NOW)
    assert s == before


def test_new_course():
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Introducing Statistics"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="new_course", course="M140", title="Introducing Statistics")]
    assert s.courses["102"] == "M140"


def test_new_deadline_far_away():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 5 * 86400, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="new_deadline", course="TM112", title="Quiz 1 closes", url="https://lms/q", due=NOW + 5 * 86400)]
    assert s.events["502"] == EventState(due=NOW + 5 * 86400, reminded_3d=False, reminded_24h=False)


def test_new_deadline_within_24h_premarks_both_tiers():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 3600, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert kinds(alerts) == ["new_deadline"]
    assert s.events["502"] == EventState(due=NOW + 3600, reminded_3d=True, reminded_24h=True)


def test_new_deadline_within_72h_premarks_3d_only():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 48 * 3600, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert kinds(alerts) == ["new_deadline"]
    assert s.events["502"] == EventState(due=NOW + 48 * 3600, reminded_3d=True, reminded_24h=False)


def test_reminder_3d_fires_once():
    s = seeded_state()  # event 501 due NOW + 10d
    t = NOW + 10 * 86400 - 60 * 3600  # 60h before due
    alerts, s = check(base_snapshot(), s, t)
    assert alerts == [Alert(kind="reminder", course="TM112", title="TMA01 is due", url="https://lms/a", due=NOW + 10 * 86400, remaining=60 * 3600)]
    assert s.events["501"].reminded_3d is True and s.events["501"].reminded_24h is False
    alerts, s = check(base_snapshot(), s, t + 3600)
    assert alerts == []


def test_reminder_24h_fires_once_and_sets_both():
    s = seeded_state()
    due = NOW + 10 * 86400
    alerts, s = check(base_snapshot(), s, due - 20 * 3600)
    assert kinds(alerts) == ["reminder"] and alerts[0].remaining == 20 * 3600
    assert s.events["501"] == EventState(due=due, reminded_3d=True, reminded_24h=True)
    alerts, _ = check(base_snapshot(), s, due - 3600)
    assert alerts == []


def test_both_tiers_can_fire_in_sequence():
    s = seeded_state()
    due = NOW + 10 * 86400
    a1, s = check(base_snapshot(), s, due - 70 * 3600)
    a2, s = check(base_snapshot(), s, due - 20 * 3600)
    assert kinds(a1) == ["reminder"] and kinds(a2) == ["reminder"]


def test_no_reminder_when_past_due():
    s = seeded_state()
    due = NOW + 10 * 86400
    alerts, s = check(base_snapshot(), s, due + 10)
    assert alerts == []
    assert s.events["501"].reminded_24h is False  # untouched, simply never fires


def test_due_date_change_is_tracked():
    s = seeded_state()
    snap = base_snapshot()
    snap.events[0] = Event(501, "TMA01 is due", "TM112", NOW + 20 * 86400, "https://lms/a")
    _, s = check(snap, s, NOW)
    assert s.events["501"].due == NOW + 20 * 86400


def test_old_events_are_pruned():
    s = seeded_state()
    s.events["1"] = EventState(due=NOW - PRUNE_AFTER - 1)
    s.events["2"] = EventState(due=NOW - PRUNE_AFTER + 100)
    _, s = check(base_snapshot(), s, NOW)
    assert "1" not in s.events and "2" in s.events


def test_new_announcement():
    snap = base_snapshot()
    snap.discussions.append(Discussion(702, "TM112", "Room change", "<p>Now in B12</p>", "https://lms/d2"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="announcement", course="TM112", title="Room change", body="<p>Now in B12</p>", url="https://lms/d2")]
    assert "702" in s.discussions


def test_new_content_grouped_per_course():
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Stats"))
    snap.modules += [
        Module(9005, "TM112", "Week 2 slides", "resource", ""),
        Module(9006, "M140", "Quiz 1", "quiz", ""),
        Module(9007, "TM112", "TMA02", "assign", ""),
    ]
    s = seeded_state()
    s.courses["102"] = "M140"
    alerts, s = check(snap, s, NOW)
    assert alerts == [
        Alert(kind="new_content", course="TM112", items=[("Week 2 slides", "resource"), ("TMA02", "assign")]),
        Alert(kind="new_content", course="M140", items=[("Quiz 1", "quiz")]),
    ]
    assert {"9005", "9006", "9007"} <= s.modules


def test_grade_posted_and_changed():
    snap = base_snapshot()
    snap.grades.append(Grade(402, "TM112", "Quiz 1", None, "-", 10.0))  # ungraded: ignored
    s = seeded_state()
    alerts, s = check(snap, s, NOW)
    assert alerts == []
    snap.grades[1] = Grade(402, "TM112", "Quiz 1", 9.0, "9.00", 10.0)
    alerts, s = check(snap, s, NOW)
    assert alerts == [Alert(kind="grade", course="TM112", title="Quiz 1", body="9.00")]
    snap.grades[0] = Grade(401, "TM112", "TMA01", 90.0, "90.00", 100.0)
    alerts, s = check(snap, s, NOW)
    assert alerts == [Alert(kind="grade", course="TM112", title="TMA01", body="90.00")]
    assert s.grades == {"401": "90.0", "402": "9.0"}


def test_course_errors_become_alerts_even_on_first_run():
    snap = base_snapshot()
    snap.errors = ["M140: nopermissions: Sorry"]
    alerts, _ = check(snap, State(), NOW)
    assert alerts == [Alert(kind="live", count=1), Alert(kind="course_error", body="M140: nopermissions: Sorry")]
    alerts, _ = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="course_error", body="M140: nopermissions: Sorry")]


def test_alert_ordering():
    snap = base_snapshot()
    snap.errors = ["x"]
    snap.courses.append(Course(102, "M140", "Stats"))
    snap.events.append(Event(502, "Quiz 1 closes", "M140", NOW + 5 * 86400, ""))
    snap.discussions.append(Discussion(702, "M140", "Hi", "", ""))
    snap.modules.append(Module(9006, "M140", "Quiz 1", "quiz", ""))
    snap.grades.append(Grade(402, "M140", "Quiz 1", 9.0, "9.00", 10.0))
    s = seeded_state()
    alerts, _ = check(snap, s, NOW + 10 * 86400 - 3600)  # also triggers 24h reminder for 501
    assert kinds(alerts) == ["course_error", "new_course", "new_deadline", "reminder", "announcement", "new_content", "grade"]


def test_failing_flag_untouched():
    s = seeded_state()
    s.failing = True
    _, s2 = check(base_snapshot(), s, NOW)
    assert s2.failing is True
