from unitracker.checker import Alert
from unitracker.formatting import MAX_LEN, format_alert, format_due, format_remaining, strip_html, truncate

TZ = "Africa/Cairo"


def test_strip_html():
    assert strip_html("<p>Hello <b>all</b>&amp; friends</p>\n<br>bye") == "Hello all& friends bye"


def test_strip_html_separates_block_elements():
    assert strip_html("<p>Line one</p><p>Line two</p>") == "Line one Line two"
    assert strip_html("<ul><li>Item one</li><li>Item two</li></ul>") == "Item one Item two"
    assert strip_html("Before<br/>After") == "Before After"
    assert strip_html("x<b>y</b>z") == "xyz"


def test_strip_html_drops_comments_style_and_script():
    assert strip_html("a<!-- hidden <b>note</b> -->b") == "ab"
    assert strip_html("<style type='text/css'>p { color: red }</style><p>Hi</p>") == "Hi"
    assert strip_html("<p>Hi</p><SCRIPT>alert('x')</SCRIPT >bye") == "Hi bye"
    assert strip_html("<style>\n.a{}\n</style>x<script>\nif (a<b) {}\n</script>y") == "xy"


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
    c = Alert(kind="deadline_changed", course="TM<1>", title="TMA01 is due", url="https://lms/a?x=1&y=2", due=1790891940)
    assert format_alert(c, "UTC") == '📌 Deadline changed\n<b>TMA01 is due</b> (TM&lt;1&gt;)\nDue <b>Thu 1 Oct, 21:59</b>\n<a href="https://lms/a?x=1&amp;y=2">Open</a>'


def test_empty_course_omits_parenthetical():
    a = Alert(kind="new_deadline", course="", title="Site event", url="", due=1790891940)
    assert format_alert(a, "UTC") == "📌 New deadline\n<b>Site event</b>\nDue <b>Thu 1 Oct, 21:59</b>"
    assert format_alert(Alert(kind="new_course", course="", title="X"), "UTC") == "🎓 Enrolled in <b>X</b>"
    r = Alert(kind="reminder", course="", title="Site event", url="", due=1790891940, remaining=3600)
    assert format_alert(r, "UTC") == "⏰ Due in 1 hour\n<b>Site event</b>\nDue <b>Thu 1 Oct, 21:59</b>"


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
    out = format_alert(a, TZ)
    assert len(out) <= 4000
    assert out.endswith("(resource)\n…")  # cut on a line break, not mid-bullet


def test_truncate_prefers_line_break_near_cap():
    lines = "\n".join(f"line {i:04d} " + "x" * 50 for i in range(200))
    out = truncate(lines)
    assert len(out) <= MAX_LEN and out.endswith("\n…")
    assert out[:-2] == lines[: len(out) - 2] and lines[len(out) - 2] == "\n"  # a whole-line prefix


def test_truncate_hard_cuts_when_no_newline_near_cap():
    text = "head\n" + "y" * 5000
    out = truncate(text)
    assert out == text[: MAX_LEN - 1] + "…" and len(out) == MAX_LEN
    assert truncate("short") == "short"
