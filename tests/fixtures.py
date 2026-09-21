"""Realistic Moodle web-service response shapes (trimmed to the fields we use)."""

SITE_INFO = {"sitename": "AOU", "userid": 2550273, "fullname": "Student", "release": "5.2.1+"}

COURSES = [
    {"id": 101, "shortname": "TM112", "fullname": "Introduction to Computing", "visible": 1},
    {"id": 102, "shortname": "M140", "fullname": "Introducing Statistics", "visible": 1},
]

def event(id, name, timesort, shortname="TM112", url="https://lms/mod/assign/view.php?id=1"):
    return {
        "id": id, "name": name, "timesort": timesort, "timestart": timesort,
        "modulename": "assign", "eventtype": "due", "url": url,
        "course": {"id": 101, "shortname": shortname, "fullname": "Introduction to Computing"},
    }

EVENTS = [event(501, "TMA01 is due", 1_760_000_000), event(502, "Quiz 1 closes", 1_760_100_000, "M140")]

FORUMS = [
    {"id": 301, "course": 101, "type": "news", "name": "Announcements"},
    {"id": 302, "course": 101, "type": "general", "name": "Discussion"},
    {"id": 303, "course": 102, "type": "news", "name": "Announcements"},
]

def discussion(discussion_id, subject, message="<p>Hello <b>all</b></p>", post_id=None):
    return {
        "id": post_id or discussion_id + 1000, "discussion": discussion_id, "subject": subject,
        "message": message, "name": subject, "timemodified": 1_759_000_000, "userfullname": "Tutor",
    }

DISCUSSIONS_301 = [discussion(701, "Welcome to TM112")]
DISCUSSIONS_303 = [discussion(702, "Room change")]

CONTENTS_101 = [
    {"id": 1, "name": "General", "modules": [
        {"id": 9001, "name": "Announcements", "modname": "forum", "url": "https://lms/mod/forum/view.php?id=9001", "visible": 1, "uservisible": True},
        {"id": 9002, "name": "Week 1 slides", "modname": "resource", "url": "https://lms/mod/resource/view.php?id=9002", "visible": 1, "uservisible": True},
        {"id": 9003, "name": "Hidden thing", "modname": "quiz", "url": "https://lms/mod/quiz/view.php?id=9003", "visible": 0, "uservisible": False},
        {"id": 9004, "name": "Intro text", "modname": "label", "visible": 1, "uservisible": True},
    ]},
]
CONTENTS_102 = [{"id": 2, "name": "General", "modules": []}]

GRADES_101 = [
    {"id": 401, "itemname": "TMA01", "itemtype": "mod", "itemmodule": "assign", "graderaw": 85.0, "gradeformatted": "85.00", "grademax": 100.0},
    {"id": 402, "itemname": "Quiz 1", "itemtype": "mod", "itemmodule": "quiz", "graderaw": None, "gradeformatted": "-", "grademax": 10.0},
    {"id": 403, "itemname": None, "itemtype": "course", "graderaw": 85.0, "gradeformatted": "85.00", "grademax": 100.0},
]
GRADES_102 = []
