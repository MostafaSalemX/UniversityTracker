# Moodle Checker v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add submission-aware deadlines, BigBlueButton live-session alerts, Moodle notification forwarding, and a 10-minute cadence to the deployed v1 checker.

**Architecture:** Same pipeline as v1 — `moodle.py` gains thin helpers, `snapshot.py` fetches the new data into dataclasses (each fetch isolated), `state.py` remembers live rooms and notification ids, `checker.py` (pure) decides what to alert, `formatting.py` renders. Cadence is infrastructure only (`.railway/railway.ts` + workflow).

**Tech Stack:** Python 3.13, `requests`, `python-dotenv`, `tzdata`, `pytest`. Railway IaC via `.railway/railway.ts`.

**Spec:** `docs/superpowers/specs/2026-09-21-v2-sessions-submissions-notifications-design.md`

## Global Constraints

- `checker.py` stays pure: no network, no clock; `now` is injected. `check()` never mutates its input state.
- Every user-supplied string is HTML-escaped exactly once, in `formatting.py`. `snapshot.py` unescapes Moodle's pre-escaped display strings via `_text()`; raw HTML bodies (`message_html`, `text_html`) stay raw and go through `strip_html`.
- Every new Moodle fetch lives in its own `try/except MoodleError` and is captured into `snapshot.errors` under a stable key; never let one fetch abort the run.
- `STATUS_HORIZON = 7 * 86400`. Status is fetched only for `assign`/`quiz` events with `0 <= due - now <= STATUS_HORIZON`.
- Reminder suppression: `submission == "submitted"` or `attempts >= 1` ⇒ no reminder alert, tier flags still set.
- Notifications with `component == "mod_forum"` are ignored entirely (never stored, never alerted).
- Alert order: live, course_error, new_course, new_deadline, deadline_changed, reminder, session_live, announcement, new_content, grade, notification.
- Cron: `*/10 * * * *` in both `.railway/railway.ts` and `.github/workflows/check.yml`.
- Tests: `.venv/Scripts/python -m pytest -q -W error` from the repo root; must stay green with zero warnings (79 tests at the start of this plan). Commit after each task with the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Never print or commit secrets; `.env` and `state.json` are gitignored.

---

## File Structure

```
unitracker/
  moodle.py      – +assign_submission_status, quiz_user_attempts, quiz_best_grade,
                    bbb_rooms, bbb_meeting_info, popup_notifications
  snapshot.py    – Event +modulename/instance/submission/attempts/best_grade;
                    +LiveRoom, +Notification; Snapshot +live_rooms/+notifications;
                    build_snapshot: status lookups, rooms, notifications
  state.py       – State +live_rooms: set[str], +notifications: set[str]
  checker.py     – Alert +submission/+attempts/+best_grade; reminder suppression;
                    session_live + notification alerts
  formatting.py  – status line; 🔴 / 🔔 templates
tests/
  fixtures.py    – +SUBMISSION_*, QUIZ_ATTEMPTS_*, BEST_GRADE_*, BBB_ROOMS, MEETING_*, NOTIFICATIONS
  test_moodle.py, test_snapshot.py, test_state.py, test_checker.py, test_formatting.py – extended
.railway/railway.ts, .github/workflows/check.yml, README.md – cadence
```

---

### Task 1: Moodle client helpers

**Files:**
- Modify: `unitracker/moodle.py` (append after `grade_items`)
- Test: `tests/test_moodle.py` (append)

**Interfaces:**
- Produces on `MoodleClient`:
  - `assign_submission_status(assignid: int) -> dict` — returns the raw payload (`lastattempt`, `feedback`, …).
  - `quiz_user_attempts(quizid: int) -> list[dict]` — `attempts` list, `status="all"`.
  - `quiz_best_grade(quizid: int) -> dict` — `{"hasgrade": bool, "grade": float|None, ...}`.
  - `bbb_rooms(course_ids: list[int]) -> list[dict]` — `bigbluebuttonbns` list; `[]` when no ids.
  - `bbb_meeting_info(room_id: int) -> dict` — `{"running": bool, "participantcount": int, ...}`.
  - `popup_notifications(userid: int, limit: int = 20) -> list[dict]` — `notifications` list.

Moodle REST facts:
- `mod_assign_get_submission_status(assignid)` → `{"lastattempt": {"submission": {"status": "new"|"draft"|"submitted", ...}, "cansubmit": bool, ...}, "feedback": {...}, "warnings": []}`. `lastattempt.submission` is absent when the student never opened the assignment.
- `mod_quiz_get_user_attempts(quizid, status="all")` → `{"attempts": [{"id", "state": "inprogress"|"finished"|"abandoned", "sumgrades", ...}], "warnings": []}`.
- `mod_quiz_get_user_best_grade(quizid)` → `{"hasgrade": bool, "grade": float, "gradetopass": float|absent}`.
- `mod_bigbluebuttonbn_get_bigbluebuttonbns_by_courses(courseids[])` → `{"bigbluebuttonbns": [{"id", "coursemodule", "course", "name", ...}], "warnings": []}`.
- `mod_bigbluebuttonbn_meeting_info(bigbluebuttonbnid, groupid=0, updatecache=0)` → `{"running": bool, "participantcount": int, "statusrunning": str, ...}`.
- `message_popup_get_popup_notifications(useridto, limit, offset)` → `{"notifications": [{"id", "subject", "smallmessage", "fullmessagehtml", "contexturl", "contexturlname", "component", "eventtype", "timecreated", "read"}], "unreadcount": int}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_moodle.py`:
```python
def test_v2_helpers_unwrap_envelopes():
    s = FakeSession(
        {"token": "abc"},
        {"lastattempt": {"submission": {"status": "draft"}}, "feedback": {}, "warnings": []},
        {"attempts": [{"id": 1, "state": "finished"}], "warnings": []},
        {"hasgrade": True, "grade": 8.0},
        {"bigbluebuttonbns": [{"id": 17, "coursemodule": 9010, "course": 101, "name": "Tutorial"}], "warnings": []},
        {"running": True, "participantcount": 3},
        {"notifications": [{"id": 88101, "subject": "Hi"}], "unreadcount": 1},
    )
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    assert c.assign_submission_status(5)["lastattempt"]["submission"]["status"] == "draft"
    assert s.calls[1][1]["assignid"] == 5
    assert c.quiz_user_attempts(6) == [{"id": 1, "state": "finished"}]
    assert s.calls[2][1]["quizid"] == 6 and s.calls[2][1]["status"] == "all"
    assert c.quiz_best_grade(6) == {"hasgrade": True, "grade": 8.0}
    assert c.bbb_rooms([101, 102])[0]["id"] == 17
    assert s.calls[4][1]["courseids[0]"] == 101 and s.calls[4][1]["courseids[1]"] == 102
    assert c.bbb_meeting_info(17)["running"] is True
    assert s.calls[5][1]["bigbluebuttonbnid"] == 17
    assert c.popup_notifications(2550273) == [{"id": 88101, "subject": "Hi"}]
    assert s.calls[6][1]["useridto"] == 2550273 and s.calls[6][1]["limit"] == 20


def test_bbb_rooms_with_no_courses_makes_no_call():
    s = FakeSession({"token": "abc"})
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    assert c.bbb_rooms([]) == []
    assert len(s.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_moodle.py -q`
Expected: 2 failures — `AttributeError: 'MoodleClient' object has no attribute 'assign_submission_status'` / `bbb_rooms`.

- [ ] **Step 3: Implement the helpers**

Append to `unitracker/moodle.py` inside `MoodleClient`, after `grade_items`:
```python
    # --- v2: submissions, live sessions, notifications --------------------

    def assign_submission_status(self, assignid: int) -> dict:
        return self.call("mod_assign_get_submission_status", assignid=assignid)

    def quiz_user_attempts(self, quizid: int) -> list[dict]:
        return self.call("mod_quiz_get_user_attempts", quizid=quizid, status="all").get("attempts", [])

    def quiz_best_grade(self, quizid: int) -> dict:
        return self.call("mod_quiz_get_user_best_grade", quizid=quizid)

    def bbb_rooms(self, course_ids: list[int]) -> list[dict]:
        if not course_ids:
            return []
        return self.call("mod_bigbluebuttonbn_get_bigbluebuttonbns_by_courses", courseids=course_ids).get("bigbluebuttonbns", [])

    def bbb_meeting_info(self, room_id: int) -> dict:
        return self.call("mod_bigbluebuttonbn_meeting_info", bigbluebuttonbnid=room_id)

    def popup_notifications(self, userid: int, limit: int = 20) -> list[dict]:
        return self.call("message_popup_get_popup_notifications", useridto=userid, limit=limit, offset=0).get("notifications", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_moodle.py -q`
Expected: all pass (9 tests).

- [ ] **Step 5: Commit**

```bash
git add unitracker/moodle.py tests/test_moodle.py
git commit -m "feat(v2): Moodle helpers for submissions, quiz attempts, BBB rooms, notifications"
```

---

### Task 2: State additions

**Files:**
- Modify: `unitracker/state.py`
- Test: `tests/test_state.py` (append)

**Interfaces:**
- `State.live_rooms: set[str]` (room ids currently running as of the last run), `State.notifications: set[str]` (seen notification ids). Both default empty; `load()` tolerates their absence in old files; `save()` serialises them as sorted lists.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state.py`:
```python
def test_v2_fields_round_trip_and_default(tmp_path):
    p = tmp_path / "state.json"
    s = st.State(initialized=True, live_rooms={"17"}, notifications={"88101", "88102"})
    st.save(s, str(p))
    loaded = st.load(str(p))
    assert loaded.live_rooms == {"17"} and loaded.notifications == {"88101", "88102"}
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["live_rooms"] == ["17"] and raw["notifications"] == ["88101", "88102"]
    # v1 state file without the new keys still loads
    p.write_text(json.dumps({"version": 1, "initialized": True}), encoding="utf-8")
    old = st.load(str(p))
    assert old.live_rooms == set() and old.notifications == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_state.py -q`
Expected: FAIL — `TypeError: State.__init__() got an unexpected keyword argument 'live_rooms'`.

- [ ] **Step 3: Implement**

In `unitracker/state.py`:
- Add to `State` after `course_errors`:
  ```python
      live_rooms: set[str] = field(default_factory=set)      # BBB room ids running at last check
      notifications: set[str] = field(default_factory=set)   # popup notification ids already alerted
  ```
- In `load()`, add to the `State(...)` call:
  ```python
          live_rooms=set(raw.get("live_rooms", [])),
          notifications=set(raw.get("notifications", [])),
  ```
- In `save()`, after `raw["modules"] = sorted(state.modules)`:
  ```python
      raw["live_rooms"] = sorted(state.live_rooms)
      raw["notifications"] = sorted(state.notifications)
  ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_state.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add unitracker/state.py tests/test_state.py
git commit -m "feat(v2): remember live rooms and seen notifications in state"
```

---

### Task 3: Snapshot — status lookups, rooms, notifications

**Files:**
- Modify: `unitracker/snapshot.py`
- Modify: `tests/fixtures.py` (append)
- Test: `tests/test_snapshot.py` (modify `FakeClient`, append tests)

**Interfaces:**
- Consumes Task 1 helpers.
- Produces:
  - `Event(id, name, course_shortname, due, url, modulename: str = "", instance: int = 0, submission: str | None = None, attempts: int | None = None, best_grade: str = "")` — new fields have defaults so v1 call sites/tests keep working.
  - `LiveRoom(id: int, cmid: int, course_shortname: str, name: str, running: bool, url: str)` (frozen).
  - `Notification(id: int, subject: str, text_html: str, url: str, component: str)` (frozen).
  - `Snapshot.live_rooms: list[LiveRoom]`, `Snapshot.notifications: list[Notification]`.
  - `STATUS_HORIZON = 7 * 86400` (module constant in `snapshot.py`).

Rules:
- Events: `modulename = e.get("modulename") or ""`, `instance = int(e.get("instance") or 0)`.
- Status lookup only when `modulename in ("assign", "quiz")`, `instance > 0`, and `0 <= due - now <= STATUS_HORIZON`.
  - assign: `status = ((payload.get("lastattempt") or {}).get("submission") or {}).get("status") or "new"` → `submission`.
  - quiz: `attempts = count of attempts with state == "finished"`; `best_grade = f"{grade:.2f}"` when `hasgrade` else `""`.
  - Any `MoodleError` → `snap.errors[f"{shortname}/status"] = f"{shortname} submission status: {exc}"`; the event keeps `submission=None`/`attempts=None`. One error entry per course (first failure wins; later events in that course are still attempted).
- Rooms: one `bbb_rooms(list(names))` call; failure → `snap.errors["bbb"]`. Per room `bbb_meeting_info(id)`; failure → `snap.errors[f"{shortname}/bbb"]`, room skipped. `url = f"{base_url}/mod/bigbluebuttonbn/view.php?id={cmid}"`. Rooms for unknown course ids are skipped.
- Notifications: `popup_notifications(userid)`; failure → `snap.errors["notifications"]`. Skip `component == "mod_forum"`. `subject = _text(subject)`, `text_html = smallmessage or fullmessagehtml or ""` (raw), `url = contexturl or ""`.

- [ ] **Step 1: Add fixtures**

Append to `tests/fixtures.py`:
```python
# --- v2 -----------------------------------------------------------------

def event_v2(id, name, timesort, modulename, instance, shortname="TM112"):
    e = event(id, name, timesort, shortname)
    e["modulename"] = modulename
    e["instance"] = instance
    return e

SUBMISSION_NEW = {"lastattempt": {"cansubmit": True, "submissionsenabled": True}, "feedback": {}, "warnings": []}
SUBMISSION_DRAFT = {"lastattempt": {"submission": {"id": 1, "status": "draft", "timemodified": 1_759_400_000}}, "warnings": []}
SUBMISSION_SUBMITTED = {"lastattempt": {"submission": {"id": 1, "status": "submitted", "timemodified": 1_759_400_000}}, "warnings": []}

QUIZ_ATTEMPTS_NONE = []
QUIZ_ATTEMPTS_ONE = [{"id": 31, "state": "finished", "sumgrades": 8.0}, {"id": 32, "state": "inprogress", "sumgrades": None}]
BEST_GRADE_NONE = {"hasgrade": False}
BEST_GRADE_8 = {"hasgrade": True, "grade": 8.0, "gradetopass": 5.0}

BBB_ROOMS = [
    {"id": 17, "coursemodule": 9010, "course": 101, "name": "Weekly tutorial", "intro": ""},
    {"id": 18, "coursemodule": 9011, "course": 102, "name": "Office hours", "intro": ""},
]
MEETING_RUNNING = {"running": True, "participantcount": 4, "statusrunning": "This session is in progress."}
MEETING_IDLE = {"running": False, "participantcount": 0, "statusrunning": "This session has not started."}

NOTIFICATIONS = [
    {"id": 88101, "subject": "You have been graded for TMA01", "smallmessage": "<p>Grade: <b>85</b></p>",
     "fullmessagehtml": "", "contexturl": "https://lms/mod/assign/view.php?id=1", "contexturlname": "TMA01",
     "component": "mod_assign", "eventtype": "assign_notification", "timecreated": 1_759_450_000, "read": False},
    {"id": 88102, "subject": "Welcome to TM112 (forum post)", "smallmessage": "", "fullmessagehtml": "<p>x</p>",
     "contexturl": "https://lms/mod/forum/discuss.php?d=701", "contexturlname": "Welcome",
     "component": "mod_forum", "eventtype": "posts", "timecreated": 1_759_440_000, "read": True},
]
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_snapshot.py`, extend `FakeClient` with the new methods (add inside the class):
```python
    submission = {}      # instance -> payload
    attempts = {}        # instance -> list
    best = {}            # instance -> payload
    rooms = []
    meetings = {}        # room id -> payload
    notifications = []
    fail_bbb_for = None  # room id whose meeting_info raises

    def assign_submission_status(self, assignid):
        self.status_calls = getattr(self, "status_calls", []) + [("assign", assignid)]
        return self.submission[assignid]

    def quiz_user_attempts(self, quizid):
        self.status_calls = getattr(self, "status_calls", []) + [("quiz", quizid)]
        return self.attempts[quizid]

    def quiz_best_grade(self, quizid):
        return self.best[quizid]

    def bbb_rooms(self, course_ids):
        return self.rooms

    def bbb_meeting_info(self, room_id):
        if room_id == self.fail_bbb_for:
            raise MoodleApiError("bbb_error", "server down")
        return self.meetings[room_id]

    def popup_notifications(self, userid, limit=20):
        return self.notifications
```

Append tests:
```python
from unitracker.snapshot import STATUS_HORIZON, LiveRoom, Notification

NOW2 = 1_759_500_000


def status_client():
    c = FakeClient()
    c.rooms = []
    c.notifications = []
    return c


def test_status_fetched_only_inside_horizon():
    c = status_client()
    c.submission = {5: fx.SUBMISSION_DRAFT, 6: fx.SUBMISSION_SUBMITTED}
    c.attempts = {7: fx.QUIZ_ATTEMPTS_ONE}
    c.best = {7: fx.BEST_GRADE_8}
    c.upcoming_events = lambda timesortfrom, limitnum=50: [
        fx.event_v2(501, "TMA01 is due", NOW2 + 2 * 86400, "assign", 5),
        fx.event_v2(502, "TMA02 is due", NOW2 + STATUS_HORIZON + 1, "assign", 6),   # outside horizon
        fx.event_v2(503, "Quiz 1 closes", NOW2 + 3600, "quiz", 7, "M140"),
        fx.event_v2(504, "Lecture", NOW2 + 3600, "bigbluebuttonbn", 17),            # not assign/quiz
    ]
    snap = build_snapshot(c, userid=1, now=NOW2)
    by_id = {e.id: e for e in snap.events}
    assert by_id[501].submission == "draft" and by_id[501].modulename == "assign" and by_id[501].instance == 5
    assert by_id[502].submission is None
    assert by_id[503].attempts == 1 and by_id[503].best_grade == "8.00"
    assert by_id[504].submission is None and by_id[504].attempts is None
    assert c.status_calls == [("assign", 5), ("quiz", 7)]


def test_missing_submission_means_new_and_no_attempts_means_zero():
    c = status_client()
    c.submission = {5: fx.SUBMISSION_NEW}
    c.attempts = {7: fx.QUIZ_ATTEMPTS_NONE}
    c.best = {7: fx.BEST_GRADE_NONE}
    c.upcoming_events = lambda timesortfrom, limitnum=50: [
        fx.event_v2(501, "TMA01 is due", NOW2 + 3600, "assign", 5),
        fx.event_v2(503, "Quiz 1 closes", NOW2 + 3600, "quiz", 7),
    ]
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert snap.events[0].submission == "new"
    assert snap.events[1].attempts == 0 and snap.events[1].best_grade == ""


def test_status_error_is_captured_per_course():
    c = status_client()
    c.assign_submission_status = lambda assignid: (_ for _ in ()).throw(MoodleApiError("nopermissions", "Sorry"))
    c.upcoming_events = lambda timesortfrom, limitnum=50: [
        fx.event_v2(501, "TMA01 is due", NOW2 + 3600, "assign", 5),
        fx.event_v2(502, "TMA02 is due", NOW2 + 7200, "assign", 6),
    ]
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert snap.errors == {"TM112/status": "TM112 submission status: nopermissions: Sorry"}
    assert all(e.submission is None for e in snap.events)


def test_rooms_and_running_state():
    c = status_client()
    c.rooms = fx.BBB_ROOMS
    c.meetings = {17: fx.MEETING_RUNNING, 18: fx.MEETING_IDLE}
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert snap.live_rooms == [
        LiveRoom(17, 9010, "TM112", "Weekly tutorial", True, "https://lms/mod/bigbluebuttonbn/view.php?id=9010"),
        LiveRoom(18, 9011, "M140", "Office hours", False, "https://lms/mod/bigbluebuttonbn/view.php?id=9011"),
    ]


def test_room_meeting_error_is_captured_and_others_continue():
    c = status_client()
    c.rooms = fx.BBB_ROOMS
    c.meetings = {18: fx.MEETING_IDLE}
    c.fail_bbb_for = 17
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert [r.id for r in snap.live_rooms] == [18]
    assert snap.errors == {"TM112/bbb": "TM112 live session: bbb_error: server down"}


def test_notifications_skip_forum_and_keep_raw_html():
    c = status_client()
    c.notifications = fx.NOTIFICATIONS
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert snap.notifications == [
        Notification(88101, "You have been graded for TMA01", "<p>Grade: <b>85</b></p>", "https://lms/mod/assign/view.php?id=1", "mod_assign"),
    ]


def test_notifications_error_is_captured():
    c = status_client()
    c.popup_notifications = lambda userid, limit=20: (_ for _ in ()).throw(MoodleApiError("disabled", "Messaging is disabled"))
    snap = build_snapshot(c, userid=1, now=NOW2)
    assert snap.errors == {"notifications": "notifications: disabled: Messaging is disabled"}
```

Also update the existing `FakeClient` used by v1 tests so `build_snapshot` doesn't hit unset attributes: the class-level defaults above (`rooms = []`, `notifications = []`, `submission = {}` …) cover it, and v1 fixture events have no `instance`, so no status calls are made.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_snapshot.py -q`
Expected: ImportError on `STATUS_HORIZON`/`LiveRoom`/`Notification`.

- [ ] **Step 4: Implement**

In `unitracker/snapshot.py`:

Add the constant and dataclasses (after `Course`):
```python
STATUS_HORIZON = 7 * 86400  # only look up submission/attempt status for deadlines this close
```
Replace `Event` with:
```python
@dataclass(frozen=True)
class Event:
    id: int
    name: str
    course_shortname: str
    due: int
    url: str
    modulename: str = ""
    instance: int = 0
    submission: str | None = None   # assign: "new" | "draft" | "submitted"
    attempts: int | None = None     # quiz: finished attempts
    best_grade: str = ""            # quiz: formatted best grade, "" when none
```
Add after `Grade`:
```python
@dataclass(frozen=True)
class LiveRoom:
    id: int
    cmid: int
    course_shortname: str
    name: str
    running: bool
    url: str


@dataclass(frozen=True)
class Notification:
    id: int
    subject: str
    text_html: str
    url: str
    component: str
```
Add to `Snapshot`:
```python
    live_rooms: list[LiveRoom] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
```
Replace the events block in `build_snapshot` with:
```python
    snap.events = [
        Event(
            int(e["id"]),
            _text(e.get("name")),
            _text((e.get("course") or {}).get("shortname")),
            int(e["timesort"]),
            e.get("url", ""),
            modulename=e.get("modulename") or "",
            instance=int(e.get("instance") or 0),
        )
        for e in client.upcoming_events(timesortfrom=now)
    ]
    snap.events = [_with_status(client, e, now, snap.errors) for e in snap.events]
```
Add the module-level helper (before `build_snapshot`):
```python
def _with_status(client: MoodleClient, e: Event, now: int, errors: dict[str, str]) -> Event:
    """Attach submission/attempt status for near assignments and quizzes."""
    if e.modulename not in ("assign", "quiz") or e.instance <= 0 or not (0 <= e.due - now <= STATUS_HORIZON):
        return e
    key = f"{e.course_shortname}/status"
    try:
        if e.modulename == "assign":
            payload = client.assign_submission_status(e.instance)
            status = ((payload.get("lastattempt") or {}).get("submission") or {}).get("status") or "new"
            return replace(e, submission=status)
        attempts = sum(1 for a in client.quiz_user_attempts(e.instance) if a.get("state") == "finished")
        best = client.quiz_best_grade(e.instance)
        best_grade = f"{float(best['grade']):.2f}" if best.get("hasgrade") and best.get("grade") is not None else ""
        return replace(e, attempts=attempts, best_grade=best_grade)
    except MoodleError as exc:
        errors.setdefault(key, f"{e.course_shortname} submission status: {exc}")
        return e
```
(`from dataclasses import dataclass, field, replace`.)

Append at the end of `build_snapshot`, before `return snap`:
```python
    # Live sessions (BigBlueButton): one room-list call, then one status call per room.
    rooms: list[dict] = []
    if snap.courses:
        try:
            rooms = client.bbb_rooms(list(names))
        except MoodleError as exc:
            snap.errors["bbb"] = f"live sessions: {exc}"
    for r in rooms:
        shortname = names.get(int(r.get("course") or 0))
        if not shortname:
            continue
        try:
            info = client.bbb_meeting_info(int(r["id"]))
        except MoodleError as exc:
            snap.errors.setdefault(f"{shortname}/bbb", f"{shortname} live session: {exc}")
            continue
        cmid = int(r.get("coursemodule") or 0)
        snap.live_rooms.append(
            LiveRoom(int(r["id"]), cmid, shortname, _text(r.get("name")), bool(info.get("running")),
                     f"{client.base_url}/mod/bigbluebuttonbn/view.php?id={cmid}")
        )

    # Notifications (the bell icon). Forum-post notifications duplicate announcements.
    try:
        for n in client.popup_notifications(userid):
            if n.get("component") == "mod_forum":
                continue
            snap.notifications.append(
                Notification(int(n["id"]), _text(n.get("subject")), n.get("smallmessage") or n.get("fullmessagehtml") or "",
                             n.get("contexturl") or "", n.get("component") or "")
            )
    except MoodleError as exc:
        snap.errors["notifications"] = f"notifications: {exc}"
```

- [ ] **Step 5: Run the snapshot tests, then the full suite**

Run: `.venv/Scripts/python -m pytest tests/test_snapshot.py -q` then `.venv/Scripts/python -m pytest -q -W error`
Expected: all pass. If a v1 snapshot/main test fails with `AttributeError` on a fake client (e.g. `tests/test_main.py::FakeClient`), add the same no-op methods there (`bbb_rooms` → `[]`, `popup_notifications` → `[]`).

- [ ] **Step 6: Commit**

```bash
git add unitracker/snapshot.py tests/fixtures.py tests/test_snapshot.py tests/test_main.py
git commit -m "feat(v2): snapshot submission status, BBB rooms, notifications"
```

---

### Task 4: Checker — suppression, live sessions, notifications

**Files:**
- Modify: `unitracker/checker.py`
- Test: `tests/test_checker.py` (append)

**Interfaces:**
- `Alert` gains `submission: str | None = None`, `attempts: int | None = None`, `best_grade: str = ""`.
- New kinds: `"session_live"` (`course`, `title`=room name, `url`), `"notification"` (`title`=subject, `body`=text_html, `url`).
- Deadline alerts (`new_deadline`, `deadline_changed`, `reminder`) carry the event's `submission`/`attempts`/`best_grade`.

Rules:
- `_done(e) = e.submission == "submitted" or (e.attempts or 0) >= 1`. In the reminder branches: if `_done(e)`, set the tier flags exactly as today but do **not** append a reminder.
- Live rooms: `running_now = {str(r.id) for r in snapshot.live_rooms if r.running}`. For each running room whose id is not in `s.live_rooms` and not `seeding(r.course_shortname)` → `session_live` alert. Then `s.live_rooms = running_now` (rooms that stopped are dropped, so the next start alerts again).
- Notifications: id not in `s.notifications` and not `first` → `notification` alert; always add id. Order the alerts by ascending id so older ones come first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_checker.py`:
```python
from unitracker.snapshot import LiveRoom, Notification


def ev(id, due, **kw):
    return Event(id, f"E{id}", "TM112", due, "https://lms/e", **kw)


def test_deadline_alerts_carry_status():
    snap = base_snapshot()
    snap.events.append(ev(502, NOW + 5 * 86400, modulename="assign", instance=5, submission="draft"))
    alerts, _ = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="new_deadline", course="TM112", title="E502", url="https://lms/e", due=NOW + 5 * 86400, submission="draft")]


def test_reminder_suppressed_when_submitted_but_tier_marked():
    s = seeded_state()
    due = NOW + 10 * 86400
    snap = base_snapshot()
    snap.events[0] = Event(501, "TMA01 is due", "TM112", due, "https://lms/a", modulename="assign", instance=5, submission="submitted")
    alerts, s = check(snap, s, due - 60 * 3600)
    assert alerts == []
    assert s.events["501"].reminded_3d is True and s.events["501"].reminded_24h is False
    alerts, s = check(snap, s, due - 3600)
    assert alerts == [] and s.events["501"].reminded_24h is True


def test_reminder_fires_with_status_when_not_submitted():
    s = seeded_state()
    due = NOW + 10 * 86400
    snap = base_snapshot()
    snap.events[0] = Event(501, "TMA01 is due", "TM112", due, "https://lms/a", modulename="assign", instance=5, submission="new")
    alerts, _ = check(snap, s, due - 20 * 3600)
    assert alerts == [Alert(kind="reminder", course="TM112", title="TMA01 is due", url="https://lms/a", due=due, remaining=20 * 3600, submission="new")]


def test_quiz_attempt_suppresses_reminder_and_carries_best_grade():
    s = seeded_state()
    due = NOW + 10 * 86400
    snap = base_snapshot()
    snap.events[0] = Event(501, "Quiz 1 closes", "TM112", due, "https://lms/q", modulename="quiz", instance=7, attempts=1, best_grade="8.00")
    alerts, s = check(snap, s, due - 3600)
    assert alerts == []
    snap.events[0] = Event(501, "Quiz 1 closes", "TM112", due, "https://lms/q", modulename="quiz", instance=7, attempts=0)
    s = seeded_state()
    alerts, _ = check(snap, s, due - 3600)
    assert alerts[0].kind == "reminder" and alerts[0].attempts == 0


def test_session_live_fires_once_per_session():
    room = LiveRoom(17, 9010, "TM112", "Weekly tutorial", True, "https://lms/bbb")
    snap = base_snapshot()
    snap.live_rooms = [room]
    s = seeded_state()
    alerts, s = check(snap, s, NOW)
    assert alerts == [Alert(kind="session_live", course="TM112", title="Weekly tutorial", url="https://lms/bbb")]
    assert s.live_rooms == {"17"}
    alerts, s = check(snap, s, NOW + 600)          # still running: quiet
    assert alerts == []
    snap.live_rooms = [LiveRoom(17, 9010, "TM112", "Weekly tutorial", False, "https://lms/bbb")]
    alerts, s = check(snap, s, NOW + 1200)         # ended: quiet, forgotten
    assert alerts == [] and s.live_rooms == set()
    snap.live_rooms = [room]
    alerts, s = check(snap, s, NOW + 1800)         # started again: alert again
    assert kinds(alerts) == ["session_live"]


def test_session_live_seeded_on_first_run_and_new_course():
    room = LiveRoom(17, 9010, "TM112", "Weekly tutorial", True, "https://lms/bbb")
    snap = base_snapshot()
    snap.live_rooms = [room]
    alerts, s = check(snap, State(), NOW)
    assert kinds(alerts) == ["live"] and s.live_rooms == {"17"}
    snap2 = base_snapshot()
    snap2.courses.append(Course(102, "M140", "Stats"))
    snap2.live_rooms = [LiveRoom(18, 9011, "M140", "Office hours", True, "https://lms/bbb2")]
    alerts, s = check(snap2, seeded_state(), NOW)
    assert kinds(alerts) == ["new_course"] and "18" in s.live_rooms


def test_notifications_new_ids_alert_in_id_order_and_seed_first_run():
    n1 = Notification(88102, "Second", "<p>b</p>", "https://lms/n2", "mod_assign")
    n2 = Notification(88101, "First", "<p>a</p>", "https://lms/n1", "mod_quiz")
    snap = base_snapshot()
    snap.notifications = [n1, n2]
    alerts, s = check(snap, State(), NOW)
    assert kinds(alerts) == ["live"] and s.notifications == {"88101", "88102"}
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [
        Alert(kind="notification", title="First", body="<p>a</p>", url="https://lms/n1"),
        Alert(kind="notification", title="Second", body="<p>b</p>", url="https://lms/n2"),
    ]
    alerts, _ = check(snap, s, NOW)
    assert alerts == []


def test_v2_alert_ordering():
    snap = base_snapshot()
    snap.live_rooms = [LiveRoom(17, 9010, "TM112", "Tutorial", True, "")]
    snap.notifications = [Notification(88101, "N", "", "", "mod_assign")]
    snap.discussions.append(Discussion(702, "TM112", "Hi", "", ""))
    snap.grades.append(Grade(402, "TM112", "Quiz 1", 9.0, "9.00", 10.0))
    alerts, _ = check(snap, seeded_state(), NOW + 10 * 86400 - 3600)  # 24h reminder for 501 too
    assert kinds(alerts) == ["reminder", "session_live", "announcement", "grade", "notification"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_checker.py -q`
Expected: failures on `submission` kwarg to `Alert`, missing `session_live`/`notification` handling.

- [ ] **Step 3: Implement**

In `unitracker/checker.py`:

Extend `Alert`:
```python
    submission: str | None = None   # assign: "new" | "draft" | "submitted"
    attempts: int | None = None     # quiz: finished attempts
    best_grade: str = ""
```

Add helpers after the constants:
```python
def _done(e) -> bool:
    """Already submitted / attempted: no point reminding."""
    return e.submission == "submitted" or (e.attempts or 0) >= 1


def _deadline_alert(kind: str, e, **extra) -> Alert:
    return Alert(kind=kind, course=e.course_shortname, title=e.name, url=e.url, due=e.due,
                 submission=e.submission, attempts=e.attempts, best_grade=e.best_grade, **extra)
```

Replace the three `Alert(kind="new_deadline"...)`, `Alert(kind="deadline_changed"...)` and both `Alert(kind="reminder"...)` constructions with `_deadline_alert("new_deadline", e)`, `_deadline_alert("deadline_changed", e)`, `_deadline_alert("reminder", e, remaining=remaining)`. Change the two reminder branches to:
```python
        if 0 < remaining <= H24 and not es.reminded_24h:
            es.reminded_24h = True
            es.reminded_3d = True
            if not _done(e):
                reminders.append(_deadline_alert("reminder", e, remaining=remaining))
        elif 0 < remaining <= H72 and not es.reminded_3d:
            es.reminded_3d = True
            if not _done(e):
                reminders.append(_deadline_alert("reminder", e, remaining=remaining))
```

After `alerts += new_deadlines + changed_deadlines + reminders`, add:
```python
    # Live sessions: alert when a room goes from not-running to running.
    running_now = {str(r.id) for r in snapshot.live_rooms if r.running}
    for r in snapshot.live_rooms:
        if r.running and str(r.id) not in s.live_rooms and not seeding(r.course_shortname):
            alerts.append(Alert(kind="session_live", course=r.course_shortname, title=r.name, url=r.url))
    s.live_rooms = running_now
```

After the grades block (before `s.initialized = True`), add:
```python
    # Notifications (site-level, so only first-run seeding applies).
    for n in sorted(snapshot.notifications, key=lambda n: n.id):
        key = str(n.id)
        if key not in s.notifications and not first:
            alerts.append(Alert(kind="notification", title=n.subject, body=n.text_html, url=n.url))
        s.notifications.add(key)
```

- [ ] **Step 4: Run checker tests, then the full suite**

Run: `.venv/Scripts/python -m pytest tests/test_checker.py -q` then `.venv/Scripts/python -m pytest -q -W error`
Expected: all pass. The existing `test_alert_ordering` still passes (no rooms/notifications in its snapshot).

- [ ] **Step 5: Commit**

```bash
git add unitracker/checker.py tests/test_checker.py
git commit -m "feat(v2): submission-aware reminders, live-session and notification alerts"
```

---

### Task 5: Formatting

**Files:**
- Modify: `unitracker/formatting.py`
- Test: `tests/test_formatting.py` (append)

**Interfaces:**
- `format_status(a: Alert) -> str` — `""` when no status known; otherwise one of:
  `❌ Not submitted` (`submission == "new"`), `📝 Draft — not submitted` (`"draft"`), `✅ Submitted` (`"submitted"`),
  `❌ No attempts yet` (`attempts == 0`), `✅ {n} attempt(s)` + ` · best {best_grade}` when non-empty (`attempts >= 1`).
- Deadline messages append `\n{status}` before the link when status is non-empty.
- `session_live` → `🔴 Live now: <b>{title}</b>{_course}{link}`.
- `notification` → `🔔 <b>{title}</b>` + `\n{strip_html(body)[:300]…}` when non-empty + link.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_formatting.py`:
```python
from unitracker.formatting import format_status


def test_format_status_variants():
    assert format_status(Alert(kind="reminder")) == ""
    assert format_status(Alert(kind="reminder", submission="new")) == "❌ Not submitted"
    assert format_status(Alert(kind="reminder", submission="draft")) == "📝 Draft — not submitted"
    assert format_status(Alert(kind="reminder", submission="submitted")) == "✅ Submitted"
    assert format_status(Alert(kind="reminder", attempts=0)) == "❌ No attempts yet"
    assert format_status(Alert(kind="reminder", attempts=1)) == "✅ 1 attempt"
    assert format_status(Alert(kind="reminder", attempts=2, best_grade="8.00")) == "✅ 2 attempts · best 8.00"


def test_deadline_with_status_line():
    a = Alert(kind="new_deadline", course="TM112", title="TMA01 is due", url="https://lms/a", due=1790891940, submission="new")
    assert format_alert(a, "UTC") == (
        '📌 New deadline\n<b>TMA01 is due</b> (TM112)\nDue <b>Thu 1 Oct, 21:59</b>\n❌ Not submitted\n<a href="https://lms/a">Open</a>'
    )


def test_session_live_and_notification():
    assert format_alert(Alert(kind="session_live", course="TM112", title="Weekly <tutorial>", url="https://lms/bbb"), TZ) == (
        '🔴 Live now: <b>Weekly &lt;tutorial&gt;</b> (TM112)\n<a href="https://lms/bbb">Open</a>'
    )
    n = Alert(kind="notification", title="Graded", body="<p>Grade: <b>85</b> &amp; feedback</p>", url="https://lms/n")
    assert format_alert(n, TZ) == '🔔 <b>Graded</b>\nGrade: 85 &amp; feedback\n<a href="https://lms/n">Open</a>'
    assert format_alert(Alert(kind="notification", title="Plain", body="", url=""), TZ) == "🔔 <b>Plain</b>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_formatting.py -q`
Expected: ImportError on `format_status`.

- [ ] **Step 3: Implement**

In `unitracker/formatting.py`:

Add after `_course`:
```python
def format_status(a: Alert) -> str:
    if a.submission == "new":
        return "❌ Not submitted"
    if a.submission == "draft":
        return "📝 Draft — not submitted"
    if a.submission == "submitted":
        return "✅ Submitted"
    if a.attempts is None:
        return ""
    if a.attempts == 0:
        return "❌ No attempts yet"
    text = f"✅ {a.attempts} attempt" + ("" if a.attempts == 1 else "s")
    return text + (f" · best {html.escape(a.best_grade)}" if a.best_grade else "")


def _excerpt(body_html: str) -> str:
    body = strip_html(body_html)
    return body[:300] + "…" if len(body) > 300 else body
```

Replace `_deadline` with:
```python
def _deadline(head: str, a: Alert, tz_name: str) -> str:
    status = format_status(a)
    return (f"{head}\n<b>{html.escape(a.title)}</b>{_course(a.course)}\nDue <b>{format_due(a.due, tz_name)}</b>"
            + (f"\n{status}" if status else "") + _link(a.url))
```

Simplify the announcement branch to use `_excerpt` (same output as before):
```python
    elif a.kind == "announcement":
        body = _excerpt(a.body)
        text = f"📢 <b>{e(a.course)}</b>: {e(a.title)}"
        if body:
            text += f"\n{e(body)}"
        text += _link(a.url)
```

Add the two new branches before `elif a.kind == "course_error":`:
```python
    elif a.kind == "session_live":
        text = f"🔴 Live now: <b>{e(a.title)}</b>{_course(a.course)}{_link(a.url)}"
    elif a.kind == "notification":
        body = _excerpt(a.body)
        text = f"🔔 <b>{e(a.title)}</b>"
        if body:
            text += f"\n{e(body)}"
        text += _link(a.url)
```

- [ ] **Step 4: Run formatting tests, then the full suite**

Run: `.venv/Scripts/python -m pytest tests/test_formatting.py -q` then `.venv/Scripts/python -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add unitracker/formatting.py tests/test_formatting.py
git commit -m "feat(v2): render submission status, live sessions, notifications"
```

---

### Task 6: 10-minute cadence, docs, deploy, smoke

**Files:**
- Modify: `.railway/railway.ts`, `.github/workflows/check.yml`, `README.md`, `docs/superpowers/specs/2026-09-21-moodle-checker-design.md` (Alerts table)

- [ ] **Step 1: Cadence**

`.railway/railway.ts` — replace the `deploy` block:
```ts
    deploy: {
      // Every 10 minutes: live-session alerts need this; everything else lands within minutes.
      cronSchedule: "*/10 * * * *",
      // A cron job must exit; never restart it.
      restartPolicyType: "NEVER",
    },
```
`.github/workflows/check.yml` — `cron: "*/10 * * * *"`.

- [ ] **Step 2: README**

- Intro list: add "live BigBlueButton sessions" and "Moodle notifications"; note deadline alerts show submission status and reminders stop once submitted.
- "Deploy on Railway" step 4: cron is now `*/10 * * * *` (drop the summer/winter mapping sentence).
- Add a short "What each alert means" table mirroring the spec's alert rows (v1 + v2).
- Note under Local run: a real local run now also seeds live rooms/notifications.

- [ ] **Step 3: v1 spec Alerts table**

Add rows for 🔴 Live session and 🔔 Notification, and a sentence under Reminder rules: "Reminders are suppressed once the assignment is submitted or the quiz has a finished attempt; the tier is still marked so it never fires later."

- [ ] **Step 4: Full suite + smoke**

Run: `.venv/Scripts/python -m pytest -q -W error` → all pass, 0 warnings.
Run: `.venv/Scripts/python -m unitracker --dry-run` → `✅ Checker is live. Tracking N course(s).` (or, once the semester has started and state exists on Railway only, whatever the local first run shows), exit 0, no `state.json` written.

- [ ] **Step 5: Commit and deploy**

```bash
git add .railway/railway.ts .github/workflows/check.yml README.md docs/superpowers/specs/2026-09-21-moodle-checker-design.md
git commit -m "feat(v2): run every 10 minutes; document live-session, status and notification alerts"
git push origin main
```
Then apply the cadence (Windows Git Bash):
```bash
RW="$APPDATA/npm/node_modules/@railway/cli/bin/railway.exe"
env _="$RW" "$RW" config plan     # expect: 1 to change — deploy.cronSchedule
env _="$RW" "$RW" config apply --yes
railway status --json | python -c "import sys,json; n=json.load(sys.stdin)['environments']['edges'][0]['node']['serviceInstances']['edges'][0]['node']; print(n['cronSchedule'], n['nextCronRunAt'])"
```
Expected: `*/10 * * * *` and a `nextCronRunAt` within 10 minutes.

---

## Self-review

**Spec coverage:** status line + suppression (T3, T4, T5); 🔴 live session once per session, seeding (T3, T4, T5); 🔔 notifications, `mod_forum` skip, seeding (T3, T4, T5); `STATUS_HORIZON` (T3); error keys `"{shortname}/status"`, `"bbb"`, `"{shortname}/bbb"`, `"notifications"` (T3); state fields (T2); alert order (T4 `test_v2_alert_ordering`); cadence + docs + deploy (T6). Messaging/inbox explicitly out of scope. ✔

**Placeholder scan:** none.

**Type consistency:** `Event` new fields used identically in T3/T4/T5 (`submission`, `attempts`, `best_grade`, `modulename`, `instance`); `LiveRoom`/`Notification` field order matches between T3 construction and T4 tests; `Alert` new fields match T4 `_deadline_alert` and T5 `format_status`; helper names match T1 ↔ T3 `FakeClient`.
