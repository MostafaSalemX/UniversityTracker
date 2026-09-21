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
alerts start from the second run.

## Telegram setup (2 minutes)

1. In Telegram, open **@BotFather** → `/newbot` → follow prompts → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it any message (e.g. "hi").
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser; find `"chat":{"id":123456789` → `TELEGRAM_CHAT_ID`.

## Deploy on Railway

1. Push this repo to a **private** GitHub repo.
2. Railway → New Project → Deploy from GitHub repo → pick it. `railway.json` sets the Dockerfile build and cron schedule `0 4,10,17 * * *` (07:00 / 13:00 / 20:00 Cairo during DST).
3. Service → **Variables**: add `MOODLE_URL`, `MOODLE_USERNAME`, `MOODLE_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. (`STATE_PATH=/data/state.json` is set by the Dockerfile.)
4. Service → **Volumes** → add a volume mounted at `/data`. Without it, state resets every run and you'd get "Checker is live" three times a day.
5. Trigger a run manually once (Deployments → redeploy) and confirm the "Checker is live" Telegram message arrives.

## Fallback: GitHub Actions

`.github/workflows/check.yml` runs the same schedule. Add the five variables as
repository **Secrets** and enable Actions. State is kept in the Actions cache.

## Files

- `unitracker/moodle.py` – Moodle web-service client
- `unitracker/snapshot.py` – fetch courses/deadlines/announcements/content/grades
- `unitracker/checker.py` – pure diff against `state.json`, produces alerts
- `unitracker/formatting.py` – Telegram HTML rendering
- `unitracker/__main__.py` – entry point, failure alerts, `--dry-run`
