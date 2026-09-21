# Moodle Checker v2 — Live sessions, submission-aware deadlines, notifications, 10-minute cadence

**Date:** 2026-09-21
**Status:** Approved in chat; implementation deferred until the semester starts
**Builds on:** `2026-09-21-moodle-checker-design.md` (v1, deployed)

## Goal

Make the alerts actionable rather than merely informative:

1. **Submission-aware deadlines** — every deadline alert says whether you have
   actually submitted (assignments) or attempted (quizzes); reminders stop once
   you have.
2. **Live-session alerts** — a Telegram message within ~10 minutes of a
   BigBlueButton session starting in any of your courses.
3. **Notifications** — Moodle's bell-icon notifications (assignment feedback,
   quiz results, course welcome messages, …) forwarded to Telegram.
4. **10-minute cadence** — the checker runs every 10 minutes instead of 3×/day.

## Findings from probing the live site (2026-09-21)

- `core_message_*` → `{"errorcode": "disabled", "message": "Messaging is disabled on this site"}`.
  **Moodle inbox forwarding is not possible on AOU's site.** Dropped from scope.
- `message_popup_get_popup_notifications(useridto)` → `{"notifications": [], "unreadcount": 0}`. Works.
- `mod_bigbluebuttonbn_get_bigbluebuttonbns_by_courses(courseids=[])` → `{"bigbluebuttonbns": [], "warnings": []}`. Plugin active.
- `mod_assign_get_submission_status`, `mod_quiz_get_user_attempts`, `mod_quiz_get_user_best_grade`,
  `mod_bigbluebuttonbn_meeting_info` are all in the account's function list.

## Alerts (additions and changes to the v1 table)

| Type | Trigger | Message shape |
|---|---|---|
| 📌 New deadline / 📌 Deadline changed / ⏰ Reminder | unchanged | gain a **status line** when known: `❌ Not submitted` · `📝 Draft — not submitted` · `✅ Submitted` · `❌ No attempts yet` · `✅ 1 attempt · best 8.00/10.00` |
| ⏰ Reminder | **suppressed** when `submission == "submitted"` or `attempts >= 1`; the tier is marked done silently | — |
| 🔴 Live session | BBB room whose `running` flips false → true (room id not in `state.live_rooms`) | `🔴 Live now: <b>{room name}</b> ({course})` + link to `mod/bigbluebuttonbn/view.php?id={cmid}` — once per session; no "ended" message |
| 🔔 Notification | Popup notification id not in `state.notifications`, `component != "mod_forum"` (forum-post notifications duplicate our 📢 announcements) | `🔔 {subject}` + `{smallmessage}` (HTML stripped, ≤300 chars) + link to `contexturl` |

Status lookup horizon: submission/attempt status is fetched only for events due
within **7 days** (`STATUS_HORIZON = 7*86400`). Farther-out events carry no
status line; both reminder tiers (≤72h) are always inside the horizon, so
suppression always has data.

First run and newly-appearing courses seed live rooms and notifications
silently, exactly as v1 seeds discussions/modules/grades.

Alert order per run: live → course_error → new_course → new_deadline →
deadline_changed → reminder → session_live → announcement → new_content →
grade → notification.

## Schedule

`*/10 * * * *` on Railway (`.railway/railway.ts`) and in the GitHub Actions
fallback. Each run is ~5–10 s; ~144 runs/day. v1's reminder windows are
unchanged, so behaviour is identical except that everything arrives within
10 minutes instead of up to 8 hours.

## Data flow additions (per run)

After v1's per-course fetches:

- For each upcoming event with `modulename in ("assign", "quiz")` and
  `due - now <= STATUS_HORIZON`:
  - `assign` → `mod_assign_get_submission_status(assignid=instance)` →
    `lastattempt.submission.status` (`"new"` | `"draft"` | `"submitted"`; absent ⇒ `"new"`).
  - `quiz` → `mod_quiz_get_user_attempts(quizid=instance, status="all")` → count of
    attempts with `state == "finished"`; `mod_quiz_get_user_best_grade(quizid)` →
    `grade` when `hasgrade`.
  - Failures are captured per course as `"{shortname}/status"` in `snapshot.errors`.
- `mod_bigbluebuttonbn_get_bigbluebuttonbns_by_courses(courseids)` once → for
  each room `mod_bigbluebuttonbn_meeting_info(bigbluebuttonbnid=id)` → `running`.
  Failures captured as `"bbb"` / `"{shortname}/bbb"`.
- `message_popup_get_popup_notifications(useridto=userid, limit=20, offset=0)`
  once. Failure captured as `"notifications"`.

Call budget for a typical semester (6 courses, 10 near deadlines, 6 rooms):
v1's ~24 + 10 + 7 + 1 ≈ 42 calls, ≈ 6 s.

## State additions

```json
{
  "live_rooms": ["17"],
  "notifications": ["88101", "88102"]
}
```

`EventState` is unchanged; suppression uses the existing `reminded_*` flags.

## Snapshot additions

- `Event` gains `modulename: str`, `instance: int`, `submission: str | None`,
  `attempts: int | None`, `best_grade: str` (formatted, `""` when none).
- `LiveRoom(id: int, cmid: int, course_shortname: str, name: str, running: bool, url: str)`
- `Notification(id: int, subject: str, text_html: str, url: str, component: str)`
- `Snapshot.live_rooms: list[LiveRoom]`, `Snapshot.notifications: list[Notification]`.

## Error handling

Unchanged from v1: every new fetch is in its own `try`, captured into
`snapshot.errors` with a stable key, alerted once per distinct message.
A missing BBB plugin or disabled notifications would surface once as ⚠️ and
then stay quiet.

## Testing

Same fixture-driven style as v1. New coverage:
- moodle helpers unwrap the four new envelopes.
- snapshot: status fetched only inside the horizon; `"new"` when submission absent;
  quiz attempt counting ignores `inprogress`; rooms map `running`; notifications
  keep `component`.
- checker: reminder suppressed when submitted / attempted (and tier marked
  done); status carried on new_deadline/changed/reminder alerts; session_live
  fires once on false→true and again after false→true→false→true; notification
  new-id alert, `mod_forum` skipped, first-run seed.
- formatting: each status line variant; the two new templates; empty text omitted.
- Live smoke: `python -m unitracker --dry-run` still prints "Checker is live".

## Out of scope

Moodle inbox (disabled site-wide), "session ended" messages, per-course
opt-outs, quiz-window "opens" alerts, calendar sync. See `docs/ROADMAP.md`.
