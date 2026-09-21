# Roadmap — what else the Moodle API lets us build

Written 2026-09-21, before the semester started (the account had zero courses).
Review this once real courses appear and pick what's worth building.

Everything here was checked against the live site: the account can call
**431** web-service functions (`core_webservice_get_site_info` → `functions`).
Two hard limits found by probing:

- **Moodle messaging is disabled site-wide** (`core_message_*` → `errorcode: disabled`).
  Anything "inbox"-shaped is impossible. Notifications (bell icon) still work.
- **No attendance plugin** (`mod_attendance_*` absent). Attendance can't be tracked.
- The **class timetable / room schedule** lives in AOU's student-information
  system, not Moodle. We only see it if tutors post it as announcements or
  calendar events (which we already catch).

## Status

| Version | State | What it does |
|---|---|---|
| v1 | **Deployed** (Railway, 3×/day) | enrolments, deadlines (+changes, 3d/24h reminders), announcements, new content, grades, failure/recovery alerts |
| v2 | **Planned** — `docs/superpowers/plans/2026-09-21-v2-sessions-submissions-notifications.md` | submission-aware deadlines (reminders stop once submitted), 🔴 BigBlueButton live-session alerts, 🔔 notifications, every 10 minutes |

## Candidate improvements (after v2)

Ordered roughly by expected payoff for "don't miss classes, quizzes, assignments".
Effort: S = an hour or two, M = half a day, L = a day+.

### A. Deadlines & assessment

| # | Idea | API | Effort | Notes |
|---|---|---|---|---|
| A1 | **Daily digest at 07:00**: everything due in the next 7 days with submission status, one message | data already in snapshot | S | Complements event-driven alerts; one glanceable morning list. Needs a "last digest date" in state. |
| A2 | **Quiz "opens" alerts** with the close date and time limit | `mod_quiz_get_quizzes_by_courses` (`timeopen`, `timeclose`, `timelimit`, `attempts`) | S | Calendar action events only cover *close*; opening windows are invisible today. |
| A3 | **Assignment cut-off / late-penalty awareness**: "due in 24h; late submissions accepted until X" | `mod_assign_get_assignments` (`cutoffdate`, `allowsubmissionsfromdate`, `maxattempts`) | S | Prevents giving up when a late window still exists. |
| A4 | **Feedback text on grade alerts**: include the tutor's comment | `mod_assign_get_submission_status` → `feedback.plugins[…].editorfields` | S | Currently grade alerts show the number only. |
| A5 | **Extension detection**: alert when you've been granted a personal extension | `mod_assign_get_user_flags` / `get_submission_status` (`lastattempt.extensionduedate`) | S | Otherwise the calendar still shows the original date. |
| A6 | **Workshop / peer-assessment phases** | `mod_workshop_get_workshops_by_courses`, `get_user_plan` | M | Only if any course uses Workshop. |
| A7 | **Choice / Feedback / Questionnaire deadlines**: polls and surveys with closing dates, and whether you've answered | `mod_choice_get_choices_by_courses`, `mod_feedback_get_feedbacks_by_courses`, `get_last_completed` | M | These don't appear as action events unless configured to. |

### B. Live sessions & recordings

| # | Idea | API | Effort | Notes |
|---|---|---|---|---|
| B1 | **New BBB recording posted** ("Lecture 3 recording is up") | `mod_bigbluebuttonbn_get_recordings` | S | Great for catching up on missed sessions. |
| B2 | **Scheduled-session reminder**: "Tutorial starts in 30 min" | `mod_bigbluebuttonbn_get_bigbluebuttonbns_by_courses` (`openingtime`), calendar events with `modulename == "bigbluebuttonbn"` | S | v2 alerts only once the room is running; this gives a heads-up before. Only works if tutors set opening times. |
| B3 | Session ended + duration ("you missed a 55-min session") | `meeting_info` transitions | S | Useful as a nudge to watch the recording (B1). |

### C. Course content & progress

| # | Idea | API | Effort | Notes |
|---|---|---|---|---|
| C1 | **Weekly outstanding-items summary**: activities with completion tracking you haven't completed | `core_completion_get_activities_completion_status` | M | Only meaningful if tutors enable completion tracking. Check on one course first. |
| C2 | **Changed content** (a file replaced, an assignment description edited), not just new | `core_course_get_updates_since` / `check_updates` | M | Catches "the TMA questions were updated". |
| C3 | **Direct file links** in new-content alerts (open the PDF from Telegram) | `core_course_get_contents` → `contents[].fileurl` + `?token=` | S | The mobile token allows `webservice/pluginfile.php` downloads. |
| C4 | **Section-aware content alerts** ("Week 5 → Lecture slides") | `core_course_get_contents` (`sections[].name`) | S | Cosmetic but helps orientation. |
| C5 | All-forum tracking (not just Announcements), optionally only tutor posts | `mod_forum_get_forum_discussions` on `type != "news"`, filter by author role | M | Q&A forums where tutors answer questions. Could be noisy in busy courses; per-course opt-in. |
| C6 | **Replies to discussions you've posted in** | `mod_forum_get_discussion_posts` | M | Only if you actually post. |

### D. Delivery & UX

| # | Idea | Effort | Notes |
|---|---|---|---|
| D1 | **Telegram bot commands**: `/due`, `/grades`, `/today`, `/status` answered on demand | M | Requires a long-running process or webhook (Railway service instead of cron), or a second tiny service that reads `state.json` from the volume. |
| D2 | **Snooze / mute** a course or an alert type from Telegram | M | Depends on D1. |
| D3 | **Google Calendar sync** of deadlines and sessions | S–M | `core_calendar_get_calendar_export_token` gives an iCal URL Google can subscribe to — possibly zero code. Verify the token works for the mobile service. |
| D4 | **Quiet hours** (no reminders 00:00–07:00, queue them) | S | Only matters once v2's 10-min cadence lands. |
| D5 | **Per-course emoji / colour** in messages | S | Faster scanning when 6 courses are active. |
| D6 | **Weekly health report** ("checker ran 1,008 times, 0 failures, 14 alerts") | S | Confidence that it's alive without noise. |

### E. Robustness (do these once real data has flowed for a week)

| # | Idea | Effort | Notes |
|---|---|---|---|
| E1 | Verify real response shapes for forums, contents, grades, BBB, notifications against fixtures; adjust parsers | S | Everything in v1/v2 was written from API docs, not observed AOU data. |
| E2 | Cap `retry_after` sleeps (Telegram can ask for minutes) | S | Noted in final review of v1. |
| E3 | Handle Moodle maintenance mode (HTML instead of JSON) with a friendlier ⚠️ | S | Currently surfaces as `JSONDecodeError`. |
| E4 | State-file compaction (prune old discussions/modules/notifications after a semester) | S | `state.json` grows ~1 KB/day; fine for a year, tidy eventually. |
| E5 | Second Telegram chat (e.g. a study-group channel) for announcements only | S | Config: list of chat ids per alert kind. |

## Deliberately not planned

- **Attendance** — plugin not installed.
- **Timetable / room changes** — not in Moodle.
- **Moodle inbox** — disabled site-wide.
- **Auto-submitting or auto-attempting anything** — the API allows it (`mod_assign_save_submission`, `mod_quiz_start_attempt`), but no.
- **Web dashboard** — Telegram is the interface; a dashboard would be a separate project.

## How to pick things up

Each item above is bounded enough for the normal brainstorm → short design in
chat → implement flow. Bigger ones (D1, C1, C5) deserve a spec like v2's.
When the semester starts: run `python -m unitracker --dry-run` locally once,
look at what real data looks like, do E1 first, then choose.
