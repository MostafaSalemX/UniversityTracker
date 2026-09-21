# Moodle Checker — Design

**Date:** 2026-09-21
**Status:** Approved (brainstorming)

## Goal

Check the Arab Open University Moodle site (`https://egylms.arabou.edu.kw`) three
times a day and send a Telegram message whenever something new appears that the
student would otherwise miss: new deadlines, announcements, course content,
grades, and course enrolments. Also alert when the checker itself fails, so a
silent outage can't recreate the problem it was built to solve.

## Findings from the probe (2026-09-21)

- Moodle 5.2.1+. The mobile web service is enabled: `login/token.php` with
  `service=moodle_mobile_app` returns a token for the student's credentials.
- All required `wsfunction`s are available to this account:
  `core_webservice_get_site_info`, `core_enrol_get_users_courses`,
  `core_calendar_get_action_events_by_timesort`, `core_course_get_contents`,
  `mod_forum_get_forums_by_courses`, `mod_forum_get_forum_discussions`,
  `gradereport_user_get_grade_items`.
- The account currently has **zero enrolments** (semester not started). The
  checker must handle that as a normal state and alert when courses appear.

## Approach

Python 3.13 script that calls Moodle's JSON web-service API (no browser, no
HTML scraping), diffs the result against a JSON state file, sends Telegram
messages for the differences, and exits. Runs on a Railway cron-scheduled
service. Portable to GitHub Actions or a local Task Scheduler job unchanged.

Rejected: Playwright scraping (fragile, heavy, unnecessary since the API works);
no-code automation (diff logic awkward, more effort for a worse result).

## Alerts

All times formatted in `Africa/Cairo` (configurable via `TZ_NAME`). One
Telegram message per alert type per run; nothing sent when nothing changed.
Messages use Telegram HTML parse mode; all user-supplied text is HTML-escaped.

| Type | Trigger | Message shape |
|---|---|---|
| 🎓 New course | Course id not in state | `Enrolled in <b>{fullname}</b>` |
| 📌 New deadline | Calendar action event id not in state | `<b>{name}</b> ({course shortname}) due <b>{Thu 2 Oct, 23:59}</b>` + link |
| 📌 Deadline changed | Known event whose `timesort` differs from state | `Deadline changed: <b>{name}</b> ({course}) due <b>…</b>` + link; both reminder tiers are reset for the new date |
| ⏰ Reminder (3d) | Event known, `0 < due − now ≤ 72h`, `reminded_3d` not set | `Due in {N} days: …` |
| ⏰ Reminder (24h) | Event known, `0 < due − now ≤ 24h`, `reminded_24h` not set | `Due in {N} hours: …` |
| 📢 Announcement | Discussion id not in state, forum type `news` | `<b>{course}</b>: {subject}` + first 300 chars of message (HTML stripped) + link |
| 📄 New content | Course module id not in state, module visible to user | Grouped per course: `<b>{course}</b>: {name} ({modname}), …` |
| 📊 Grade posted | Grade item id whose `graderaw` changed from null → value or value → different value | `<b>{course}</b> — {itemname}: {gradeformatted}` (falls back to `graderaw/grademax`) |
| ⚠️ Checker failed | Any unhandled exception in the run | `Checker failed: {ExceptionClass}: {message[:200]}` — sent once; suppressed while `failing=true` in state |
| ✅ Recovered | Run succeeds while `failing=true` | `Checker recovered.` |
| First run | State file absent | `Checker is live. Tracking {N} course(s).` Seeds state; sends no other alerts |

A course seen for the first time mid-life is seeded silently like a first run:
only the 🎓 alert (and its deadlines) is sent, not its historical announcements,
content or grades. Course/category total items are excluded from grade alerts.
Per-course fetch errors are alerted once per distinct message (keyed per course
and part, remembered in state) rather than on every run.

Reminder rules:
- A deadline already past due when first seen gets no reminder.
- Each reminder tier fires at most once per event (flags stored in state).
- A "new deadline" that is already within 72h fires the new-deadline alert only
  and marks the reminder tiers it already qualifies for as done (avoid three
  messages for one item).

## Schedule

Three runs daily at 07:00, 13:00, 20:00 Africa/Cairo.
Railway cron (UTC): `0 4,10,17 * * *`. (Egypt is UTC+3 in summer DST; adjust
to `0 5,11,18 * * *` in winter if exactness matters — a one-hour drift is
acceptable.)

## Architecture

```
unitracker/
  __init__.py
  __main__.py   – `python -m unitracker [--dry-run]`
  config.py     – Settings dataclass loaded from env (.env via python-dotenv)
  moodle.py     – MoodleClient: get_token(), site_info(), courses(), upcoming_events(),
                  news_forums(course_ids), discussions(forum_id), course_contents(course_id),
                  grade_items(course_id, user_id)
  snapshot.py   – build_snapshot(client) -> Snapshot (plain dataclasses, per-course error capture)
  telegram.py   – send_message(token, chat_id, html_text)
  state.py      – State dataclass + load(path) / save(path). JSON on disk.
  checker.py    – check(snapshot, state, now) -> (alerts: list[Alert], new_state)
                  Pure: no network, no clock reads (now is injected).
  formatting.py – Alert -> Telegram HTML string; date formatting in TZ_NAME
tests/
  test_checker.py, test_formatting.py, test_state.py, test_snapshot.py
  fixtures/*.json  – realistic Moodle API response shapes
Dockerfile, railway.json, requirements.txt, .env.example, .gitignore, README.md
.github/workflows/check.yml  – fallback scheduler
```

### Data flow per run

1. `config.load()` — fail fast with a clear message if any required var missing.
2. `MoodleClient.get_token()` → `site_info()` (gives `userid`).
3. `build_snapshot`: courses; upcoming action events (`limitnum=50`, from
   `now`); for each course: news-forum discussions, course contents (flattened
   modules), grade items. A failure inside one course is captured as a
   per-course error string in the snapshot rather than aborting the run.
4. `checker.check(snapshot, state, now)` → alerts + new state.
5. Send alerts (each a separate Telegram message; per-course errors become one
   ⚠️ message). In `--dry-run`, print instead of sending and do not save state.
6. Save state. Exit 0.

On any exception escaping steps 1–5: send ⚠️ (unless already `failing`), set
`failing=true` in state, save only that flag, exit 1. Success after failure
sends ✅ and clears the flag.

### State file (`state.json`)

```json
{
  "version": 1,
  "failing": false,
  "courses": {"123": "TM112"},
  "events": {"456": {"due": 1760000000, "reminded_3d": false, "reminded_24h": false}},
  "discussions": ["789"],
  "modules": ["1011"],
  "grades": {"1213": "85.00"}
}
```

Path from `STATE_PATH` (default `./state.json`). On Railway: volume mounted at
`/data`, `STATE_PATH=/data/state.json`.

### Configuration (env vars)

| Var | Required | Notes |
|---|---|---|
| `MOODLE_URL` | yes | `https://egylms.arabou.edu.kw` |
| `MOODLE_USERNAME` | yes | |
| `MOODLE_PASSWORD` | yes | |
| `TELEGRAM_BOT_TOKEN` | yes | from @BotFather |
| `TELEGRAM_CHAT_ID` | yes | |
| `STATE_PATH` | no | default `./state.json` |
| `TZ_NAME` | no | default `Africa/Cairo` |

Secrets live in `.env` locally (gitignored) and Railway service variables in
production. Never logged. Token is fetched fresh every run.

## Error handling

- Missing config → clear stderr message, exit 2. If the Telegram vars are
  present but Moodle vars are missing, still send ⚠️ first.
- Moodle `token.php` returns `{"error": ...}` → raise `MoodleAuthError` → ⚠️.
- Any web-service call returning `{"exception": ...}` → raise `MoodleApiError`
  with `errorcode`.
- HTTP timeouts 30s; one retry on connection error.
- Telegram send failure → log to stderr, exit 1, state not saved.
- Alerts are sent before state is saved; if sending fails mid-way, next run
  re-sends the unsent ones (duplicates are preferable to silence).

## Testing

- `checker.py` unit tests (no network, injected `now`):
  - first run seeds state, emits only the "live" alert
  - unchanged snapshot → zero alerts
  - each of: new course, new event, new discussion, new module, changed grade →
    exactly one alert of the right type
  - reminder fires once at ≤72h, once at ≤24h, never for past-due, never twice
  - new event already ≤24h → one alert, both reminder flags set
  - per-course error → one ⚠️ alert, other courses still processed
- `formatting.py` tests: HTML escaping, date rendering in Cairo TZ.
- `state.py` tests: round-trip, missing file → fresh state.
- `snapshot.py` tests: fixture API responses → Snapshot; a course raising
  `MoodleApiError` becomes a per-course error, not an exception.
- Live smoke: `python -m unitracker --dry-run` against the real account, run at
  the end of implementation. Expected today: "Tracking 0 course(s)".

## Deployment (README)

User-side steps: create Telegram bot via @BotFather and get chat id; create a
private GitHub repo and push; on Railway create a service from the repo, add a
volume at `/data`, set the env vars, set cron schedule `0 4,10,17 * * *`.
Fallback: GitHub Actions workflow file included, using a cache for
`state.json`, in case Railway cron + volume is a problem.

## Out of scope (for now)

Non-news forums, per-course opt-outs, daily digest, web UI, multiple users.
