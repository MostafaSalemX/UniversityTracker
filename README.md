# UniversityTracker — Moodle checker

Checks the AOU Moodle site three times a day and sends Telegram alerts for:
new deadlines (+ 3-day and 24-hour reminders), announcements, new course
content, posted grades, new enrolments — and for the checker itself failing.

## Local run

    python -m venv .venv
    .venv\Scripts\pip install -r requirements-dev.txt
    copy .env.example .env      # fill in values
    .venv\Scripts\python -m unitracker --dry-run   # prints, sends nothing, saves nothing
    .venv\Scripts\python -m unitracker             # real run
    .venv\Scripts\python -m pytest -q

`--dry-run` also covers failure alerts: if the checker itself errors, the
"⚠️ Checker failed" message is printed instead of sent to Telegram.

The first real run only sends "Checker is live" and records what exists;
alerts start from the second run. Likewise, when a new course appears you get
one "Enrolled in ..." message (plus its deadlines); its existing announcements,
content and grades are recorded silently rather than dumped as history.

Do not run real (non-`--dry-run`) local runs while Railway or Actions is also
running: two state files diverge and you get every alert twice.

Notes on what is and isn't alerted:

- Course and category totals are excluded from grade alerts; only individual
  items (TMAs, quizzes, ...) count.
- A course with "Show gradebook to students = No" surfaces once as a
  "⚠️ Problem checking a course" message and is then silent until the error
  changes or clears (and once more if it reappears later).
- A wrong Moodle password is retried three times a day for as long as it stays
  wrong. Fix the credentials promptly to avoid an account lockout.

## Telegram setup (2 minutes)

1. In Telegram, open **@BotFather** → `/newbot` → follow prompts → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it any message (e.g. "hi").
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser; find `"chat":{"id":123456789` → `TELEGRAM_CHAT_ID`.

## Deploy on Railway

The Railway project (service, cron schedule, restart policy, volume, variables) is defined in `.railway/railway.ts` and applied with the Railway CLI. Secrets are `preserve()`d there — their values live only in Railway, never in the repo.

1. Push this repo to a **private** GitHub repo and create a Railway project from it (Railway → New Project → Deploy from GitHub repo).
2. One-time local setup: `npm install` (pulls the Railway IaC SDK) and `npm install -g @railway/cli`, then `railway login` and `railway link`.
3. Set the secrets once (they're not in the repo):
   `railway variables --set MOODLE_URL=... --set MOODLE_USERNAME=... --set MOODLE_PASSWORD=... --set TELEGRAM_BOT_TOKEN=... --set TELEGRAM_CHAT_ID=...`
4. Apply the infrastructure: `railway config plan` to preview, `railway config apply` to apply. This sets the Dockerfile build, cron schedule `0 4,10,17 * * *` (07:00 / 13:00 / 20:00 Cairo during summer DST, UTC+3; in winter, UTC+2, the same local times are `0 5,11,18 * * *` — a one-hour drift is fine), restart policy `NEVER`, the `/data` volume, and `STATE_PATH`/`TZ_NAME`.
   - On Windows Git Bash the SDK's CLI-version check needs the real exe: `RW="$APPDATA/npm/node_modules/@railway/cli/bin/railway.exe"; env _="$RW" "$RW" config apply`
5. Railway cron services run at the next scheduled tick, not on deploy — `railway status --json` shows `nextCronRunAt`. To test immediately, run `python -m unitracker` once locally with the same env and confirm the "Checker is live" Telegram message arrives — then delete the local `state.json` so it doesn't diverge from the one on the volume.

## Fallback: GitHub Actions

`.github/workflows/check.yml` runs the same schedule. Add the five variables as
repository **Secrets** and enable Actions. State is kept in the Actions cache.

Caveats: GitHub disables scheduled workflows after 60 days without repository
activity (a commit or a manual run re-enables them), and schedule ticks are
frequently delayed 10–30+ minutes under load.

## Files

- `unitracker/moodle.py` – Moodle web-service client
- `unitracker/snapshot.py` – fetch courses/deadlines/announcements/content/grades
- `unitracker/checker.py` – pure diff against `state.json`, produces alerts
- `unitracker/formatting.py` – Telegram HTML rendering
- `unitracker/__main__.py` – entry point, failure alerts, `--dry-run`

## What next

Planned v2 (live sessions, submission-aware reminders, notifications, 10-minute cadence) and the full list of further ideas live in [`docs/ROADMAP.md`](docs/ROADMAP.md).
