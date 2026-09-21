from tests import fixtures as fx
from unitracker.moodle import MoodleApiError
from unitracker.snapshot import Course, Discussion, Event, Grade, Module, build_snapshot


class FakeClient:
    base_url = "https://lms"

    def __init__(self, *, fail_course_contents_for=None, fail_grades_for=None, fail_forums=False):
        self.fail_for = fail_course_contents_for
        self.fail_grades_for = fail_grades_for
        self.fail_forums = fail_forums

    def courses(self, userid):
        return fx.COURSES

    def upcoming_events(self, timesortfrom, limitnum=50):
        return fx.EVENTS

    def news_forums(self, course_ids):
        if self.fail_forums:
            raise MoodleApiError("invalidrecord", "Can't find data record")
        return [f for f in fx.FORUMS if f["type"] == "news" and f["course"] in course_ids]

    def discussions(self, forum_id):
        return {301: fx.DISCUSSIONS_301, 303: fx.DISCUSSIONS_303}[forum_id]

    def course_contents(self, course_id):
        if course_id == self.fail_for:
            raise MoodleApiError("nopermissions", "Sorry")
        return {101: fx.CONTENTS_101, 102: fx.CONTENTS_102}[course_id]

    def grade_items(self, course_id, userid):
        if course_id == self.fail_grades_for:
            raise MoodleApiError("nopermissiontoviewgrades", "No permission to view grades")
        return {101: fx.GRADES_101, 102: fx.GRADES_102}[course_id]


def test_builds_all_sections():
    snap = build_snapshot(FakeClient(), userid=1, now=1_759_500_000)
    assert snap.courses == [
        Course(101, "TM112", "Introduction to Computing"),
        Course(102, "M140", "Introducing Statistics"),
    ]
    assert snap.events == [
        Event(501, "TMA01 is due", "TM112", 1_760_000_000, "https://lms/mod/assign/view.php?id=1"),
        Event(502, "Quiz 1 closes", "M140", 1_760_100_000, "https://lms/mod/assign/view.php?id=1"),
    ]
    assert snap.discussions == [
        Discussion(701, "TM112", "Welcome to TM112", "<p>Hello <b>all</b></p>", "https://lms/mod/forum/discuss.php?d=701"),
        Discussion(702, "M140", "Room change", "<p>Hello <b>all</b></p>", "https://lms/mod/forum/discuss.php?d=702"),
    ]
    assert [m.id for m in snap.modules] == [9001, 9002, 9004]  # hidden one skipped
    assert snap.modules[1] == Module(9002, "TM112", "Week 1 slides", "resource", "https://lms/mod/resource/view.php?id=9002")
    assert snap.modules[2].url == ""
    assert snap.grades == [
        Grade(401, "TM112", "TMA01", 85.0, "85.00", 100.0),
        Grade(402, "TM112", "Quiz 1", None, "-", 10.0),
    ]  # course-total item skipped
    assert snap.errors == {}


def test_course_error_is_captured_and_others_continue():
    snap = build_snapshot(FakeClient(fail_course_contents_for=101), userid=1, now=0)
    assert snap.errors == {"TM112/contents": "TM112 contents: nopermissions: Sorry"}
    assert [c.id for c in snap.courses] == [101, 102]
    assert snap.discussions[0].id == 701          # 101's announcements unaffected
    assert snap.modules == []                     # 101's contents failed; 102 has none
    assert [g.item_id for g in snap.grades] == [401, 402]  # 101's grades still fetched


def test_grades_error_is_keyed_separately():
    snap = build_snapshot(FakeClient(fail_grades_for=101), userid=1, now=0)
    assert snap.errors == {"TM112/grades": "TM112 grades: nopermissiontoviewgrades: No permission to view grades"}
    assert [m.id for m in snap.modules] == [9001, 9002, 9004]
    assert snap.grades == []


def test_forum_list_error_keeps_contents_and_grades():
    snap = build_snapshot(FakeClient(fail_forums=True), userid=1, now=0)
    assert list(snap.errors) == ["forums"] and snap.errors["forums"].startswith("forums: invalidrecord")
    assert snap.discussions == []
    assert [m.id for m in snap.modules] == [9001, 9002, 9004]
    assert [g.item_id for g in snap.grades] == [401, 402]


def test_no_courses_is_fine():
    class Empty(FakeClient):
        def courses(self, userid):
            return []

        def upcoming_events(self, timesortfrom, limitnum=50):
            return []

    snap = build_snapshot(Empty(), userid=1, now=0)
    assert snap.courses == [] and snap.events == [] and snap.errors == {}
