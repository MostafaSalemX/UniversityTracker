from unitracker.checker import Alert
from unitracker.formatting import format_alert, format_due, format_remaining, strip_html

TZ = "Africa/Cairo"


def test_strip_html():
    assert strip_html("<p>Hello <b>all</b>&amp; friends</p>\n<br>bye") == "Hello all& friends bye"


def test_format_due_in_cairo():
    # 2026-10-01 21:59 UTC == 2026-10-02 00:59 Cairo (UTC+3, DST)
    assert format_due(1790891940, TZ) == "Fri 2 Oct, 00:59"
    assert format_due(1790891940, "UTC") == "Thu 1 Oct, 21:59"


def test_format_remaining():
    assert format_remaining(3600) == "in 1 hour"
    assert format_remaining(3601) == "in 2 hours"
    assert format_remaining(24 * 3600) == "in 24 hours"
    assert format_remaining(24 * 3600 + 1) == "in 2 days"
    assert format_remaining(60 * 3600) == "in 3 days"


def test_live_and_new_course():
    assert format_alert(Alert(kind="live", count=2), TZ) == "✅ Checker is live. Tracking 2 course(s)."
    assert format_alert(Alert(kind="new_course", course="TM112", title="Intro <Computing>"), TZ) == "🎓 Enrolled in <b>Intro &lt;Computing&gt;</b> (TM112)"


def test_new_deadline_and_reminder():
    a = Alert(kind="new_deadline", course="TM112", title="TMA01 is due", url="https://lms/a", due=1790891940)
    assert format_alert(a, "UTC") == '📌 New deadline\n<b>TMA01 is due</b> (TM112)\nDue <b>Thu 1 Oct, 21:59</b>\n<a href="https://lms/a">Open</a>'
    r = Alert(kind="reminder", course="TM112", title="TMA01 is due", url="", due=1790891940, remaining=5 * 3600)
    assert format_alert(r, "UTC") == "⏰ Due in 5 hours\n<b>TMA01 is due</b> (TM112)\nDue <b>Thu 1 Oct, 21:59</b>"


def test_announcement_truncates_and_escapes():
    body = "<p>" + "x" * 400 + "</p>"
    a = Alert(kind="announcement", course="TM112", title="Room <B>", body=body, url="https://lms/d")
    out = format_alert(a, TZ)
    assert out.startswith("📢 <b>TM112</b>: Room &lt;B&gt;\n" + "x" * 300 + "…")
    assert out.endswith('<a href="https://lms/d">Open</a>')
    assert format_alert(Alert(kind="announcement", course="C", title="T", body="", url=""), TZ) == "📢 <b>C</b>: T"


def test_new_content_grade_error():
    a = Alert(kind="new_content", course="TM112", items=[("Week 2", "resource"), ("Quiz 1", "quiz")])
    assert format_alert(a, TZ) == "📄 New in <b>TM112</b>:\n• Week 2 (resource)\n• Quiz 1 (quiz)"
    assert format_alert(Alert(kind="grade", course="TM112", title="TMA01", body="85.00"), TZ) == "📊 <b>TM112</b> — TMA01: <b>85.00</b>"
    assert format_alert(Alert(kind="course_error", body="M140: nopermissions"), TZ) == "⚠️ Problem checking a course: M140: nopermissions"


def test_hard_cap_4000():
    a = Alert(kind="new_content", course="C", items=[("n" * 100, "resource")] * 100)
    assert len(format_alert(a, TZ)) <= 4000
