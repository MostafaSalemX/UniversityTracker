# Moodle Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python script that checks the AOU Moodle site 3×/day via its JSON web-service API and sends Telegram alerts for new deadlines, announcements, course content, grades, enrolments, and checker failures.

**Architecture:** `moodle.py` is a thin API client; `snapshot.py` turns API responses into plain dataclasses; `checker.py` is a pure function diffing a snapshot against `state.py`'s persisted state and producing `Alert`s; `formatting.py` renders alerts to Telegram HTML; `__main__.py` wires it together with fail-safe error handling. Runs as a Railway cron service; a GitHub Actions workflow is included as fallback.

**Tech Stack:** Python 3.13, `requests`, `python-dotenv`, `tzdata` (for `zoneinfo` on Windows/slim containers), `pytest`. No browser, no HTML scraping.

**Spec:** `docs/superpowers/specs/2026-09-21-moodle-checker-design.md`

## Global Constraints

- Python 3.13. Runtime deps only: `requests`, `python-dotenv`, `tzdata`. Dev dep: `pytest`.
- Moodle base URL: `https://egylms.arabou.edu.kw`; token service name `moodle_mobile_app`.
- Secrets come only from env vars (`MOODLE_URL`, `MOODLE_USERNAME`, `MOODLE_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Never log or print them. `.env` and `state.json` are gitignored.
- Optional env: `STATE_PATH` (default `./state.json`), `TZ_NAME` (default `Africa/Cairo`).
- `checker.py` must be pure: no network, no `time.time()`; `now` is an injected int Unix timestamp.
- Telegram messages use `parse_mode=HTML`; every user-supplied string is escaped with `html.escape`.
- Reminder windows: 3-day tier = `0 < due - now <= 72*3600`; 24h tier = `0 < due - now <= 24*3600`. Each tier fires at most once per event.
- Exit codes: 0 success, 1 runtime failure, 2 config error.
- All tests run with `python -m pytest -q` from the repo root. Commit after each task.
- Windows shell: commands below are POSIX (Git Bash). `python` is Python 3.13.3.

---

## File Structure

```
unitracker/
  __init__.py       – empty
  __main__.py       – CLI entry: parse --dry-run, run(), exit codes
  config.py         – Settings dataclass, ConfigError, load(env)
  moodle.py         – MoodleClient + MoodleError/MoodleAuthError/MoodleApiError
  snapshot.py       – Course/Event/Discussion/Module/Grade/Snapshot dataclasses, build_snapshot()
  state.py          – State/EventState dataclasses, load(path)/save(state, path)
  checker.py        – Alert dataclass, check(snapshot, state, now)
  formatting.py     – format_alert(alert, tz_name), format_due(), strip_html()
  telegram.py       – send_message(token, chat_id, text, session=None), TelegramError
tests/
  __init__.py
  fixtures.py       – realistic Moodle API response dicts
  test_config.py
  test_state.py
  test_moodle.py
  test_snapshot.py
  test_checker.py
  test_formatting.py
  test_telegram.py
  test_main.py
requirements.txt, requirements-dev.txt, pytest.ini, .env.example, .gitignore (exists)
Dockerfile, railway.json, .github/workflows/check.yml, README.md
```

---

### Task 1: Scaffold + config loading

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.env.example`
- Create: `unitracker/__init__.py`, `unitracker/config.py`
- Test: `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.Settings` (frozen dataclass: `moodle_url, moodle_username, moodle_password, telegram_bot_token, telegram_chat_id, state_path="./state.json", tz_name="Africa/Cairo"`), `config.ConfigError(Exception)` with `.missing: list[str]`, `config.load(env: Mapping[str,str] | None = None) -> Settings`.

- [ ] **Step 1: Create scaffold files**

`requirements.txt`:
```
requests>=2.32
python-dotenv>=1.0
tzdata>=2024.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

`.env.example`:
```
MOODLE_URL=https://egylms.arabou.edu.kw
MOODLE_USERNAME=your_student_id
MOODLE_PASSWORD=your_password
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
# Optional
STATE_PATH=./state.json
TZ_NAME=Africa/Cairo
```

`unitracker/__init__.py` and `tests/__init__.py`: empty files.

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt`
(Subsequent commands assume `.venv/Scripts/python` is on PATH as `python`, or prefix accordingly.)

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from unitracker import config

FULL = {
    "MOODLE_URL": "https://egylms.arabou.edu.kw/",
    "MOODLE_USERNAME": "u",
    "MOODLE_PASSWORD": "p",
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_CHAT_ID": "c",
}


def test_load_full_env_and_defaults():
    s = config.load(FULL)
    assert s.moodle_url == "https://egylms.arabou.edu.kw"  # trailing slash stripped
    assert s.moodle_username == "u"
    assert s.telegram_chat_id == "c"
    assert s.state_path == "./state.json"
    assert s.tz_name == "Africa/Cairo"


def test_load_optional_overrides():
    s = config.load({**FULL, "STATE_PATH": "/data/state.json", "TZ_NAME": "UTC"})
    assert s.state_path == "/data/state.json"
    assert s.tz_name == "UTC"


def test_missing_vars_raise_with_names():
    env = {k: v for k, v in FULL.items() if k not in ("MOODLE_PASSWORD", "TELEGRAM_CHAT_ID")}
    with pytest.raises(config.ConfigError) as ei:
        config.load(env)
    assert ei.value.missing == ["MOODLE_PASSWORD", "TELEGRAM_CHAT_ID"]
    assert "MOODLE_PASSWORD" in str(ei.value)


def test_blank_counts_as_missing():
    with pytest.raises(config.ConfigError) as ei:
        config.load({**FULL, "MOODLE_URL": "  "})
    assert ei.value.missing == ["MOODLE_URL"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'config'` / module not found.

- [ ] **Step 4: Implement config.py**

`unitracker/config.py`:
```python
"""Settings loaded from environment variables (and .env locally)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv

REQUIRED = [
    "MOODLE_URL",
    "MOODLE_USERNAME",
    "MOODLE_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]


class ConfigError(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("Missing required environment variables: " + ", ".join(missing))


@dataclass(frozen=True)
class Settings:
    moodle_url: str
    moodle_username: str
    moodle_password: str
    telegram_bot_token: str
    telegram_chat_id: str
    state_path: str = "./state.json"
    tz_name: str = "Africa/Cairo"


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ after loading .env)."""
    if env is None:
        load_dotenv()
        env = os.environ
    values = {k: (env.get(k) or "").strip() for k in REQUIRED}
    missing = [k for k in REQUIRED if not values[k]]
    if missing:
        raise ConfigError(missing)
    return Settings(
        moodle_url=values["MOODLE_URL"].rstrip("/"),
        moodle_username=values["MOODLE_USERNAME"],
        moodle_password=values["MOODLE_PASSWORD"],
        telegram_bot_token=values["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=values["TELEGRAM_CHAT_ID"],
        state_path=(env.get("STATE_PATH") or "./state.json").strip(),
        tz_name=(env.get("TZ_NAME") or "Africa/Cairo").strip(),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini .env.example unitracker tests
git commit -m "feat: scaffold package and env config loading"
```

---

### Task 2: State persistence

**Files:**
- Create: `unitracker/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `state.EventState` dataclass: `due: int, reminded_3d: bool = False, reminded_24h: bool = False`
  - `state.State` dataclass: `version: int = 1, initialized: bool = False, failing: bool = False, courses: dict[str, str], events: dict[str, EventState], discussions: set[str], modules: set[str], grades: dict[str, str]` (collections default to empty).
  - `state.load(path: str) -> State` — missing file → fresh `State()`.
  - `state.save(state: State, path: str) -> None` — atomic write (temp file + `os.replace`), creates parent dir.

Note: `initialized` is not in the spec's JSON example; it is needed because a failed first run writes `failing=true` before the seed happened, and "state file absent" would then be wrong as the first-run test. `initialized=False` is the first-run signal.

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`:
```python
import json
from unitracker import state as st


def test_load_missing_file_gives_fresh_state(tmp_path):
    s = st.load(str(tmp_path / "nope.json"))
    assert s == st.State()
    assert s.initialized is False and s.failing is False
    assert s.courses == {} and s.events == {} and s.discussions == set()
    assert s.modules == set() and s.grades == {}


def test_round_trip(tmp_path):
    p = tmp_path / "sub" / "state.json"
    s = st.State(
        initialized=True,
        failing=True,
        courses={"1": "TM112"},
        events={"9": st.EventState(due=1700000000, reminded_3d=True)},
        discussions={"5", "6"},
        modules={"7"},
        grades={"3": "85.0"},
    )
    st.save(s, str(p))
    loaded = st.load(str(p))
    assert loaded == s
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert sorted(raw["discussions"]) == ["5", "6"]  # sets serialised as lists


def test_save_overwrites_atomically(tmp_path):
    p = tmp_path / "state.json"
    st.save(st.State(courses={"1": "A"}), str(p))
    st.save(st.State(courses={"2": "B"}), str(p))
    assert st.load(str(p)).courses == {"2": "B"}
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_state.py -q`
Expected: FAIL — module `unitracker.state` not found.

- [ ] **Step 3: Implement state.py**

`unitracker/state.py`:
```python
"""Persisted memory of what the checker has already seen."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class EventState:
    due: int
    reminded_3d: bool = False
    reminded_24h: bool = False


@dataclass
class State:
    version: int = 1
    initialized: bool = False
    failing: bool = False
    courses: dict[str, str] = field(default_factory=dict)
    events: dict[str, EventState] = field(default_factory=dict)
    discussions: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)
    grades: dict[str, str] = field(default_factory=dict)


def load(path: str) -> State:
    if not os.path.exists(path):
        return State()
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return State(
        version=raw.get("version", 1),
        initialized=raw.get("initialized", False),
        failing=raw.get("failing", False),
        courses=dict(raw.get("courses", {})),
        events={k: EventState(**v) for k, v in raw.get("events", {}).items()},
        discussions=set(raw.get("discussions", [])),
        modules=set(raw.get("modules", [])),
        grades=dict(raw.get("grades", {})),
    )


def save(state: State, path: str) -> None:
    raw = asdict(state)
    raw["discussions"] = sorted(state.discussions)
    raw["modules"] = sorted(state.modules)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add unitracker/state.py tests/test_state.py
git commit -m "feat: JSON state persistence"
```

---

### Task 3: Moodle API client

**Files:**
- Create: `unitracker/moodle.py`
- Test: `tests/test_moodle.py`

**Interfaces:**
- Produces:
  - `moodle.MoodleError(Exception)`, `moodle.MoodleAuthError(MoodleError)`, `moodle.MoodleApiError(MoodleError)` with `.errorcode: str`.
  - `moodle.MoodleClient(base_url: str, session=None, timeout: int = 30)` where `session` is anything with `.post(url, data=..., timeout=...)` returning an object with `.json()` and `.raise_for_status()` (i.e. `requests.Session`).
  - `.login(username, password) -> None` (sets `.token`)
  - `.call(wsfunction: str, **params) -> Any` — POSTs to `/webservice/rest/server.php`, flattens list params Moodle-style (`courseids[0]=1`), raises `MoodleApiError` on `{"exception": ...}` responses. One retry on `requests.ConnectionError`.
  - Typed helpers: `site_info() -> dict`, `courses(userid: int) -> list[dict]`, `upcoming_events(timesortfrom: int, limitnum: int = 50) -> list[dict]`, `news_forums(course_ids: list[int]) -> list[dict]`, `discussions(forum_id: int) -> list[dict]`, `course_contents(course_id: int) -> list[dict]`, `grade_items(course_id: int, userid: int) -> list[dict]`.

Moodle REST facts the implementer needs:
- Token: `POST {base}/login/token.php` with `username, password, service=moodle_mobile_app`. Success → `{"token": "...", "privatetoken": "..."}`; failure → `{"error": "Invalid login...", "errorcode": "invalidlogin"}` with HTTP 200.
- WS call: `POST {base}/webservice/rest/server.php` with `wstoken, wsfunction, moodlewsrestformat=json` + params. Errors → `{"exception": "...", "errorcode": "...", "message": "..."}` with HTTP 200.
- Arrays must be sent as `name[0]=v0&name[1]=v1`.
- `core_calendar_get_action_events_by_timesort` returns `{"events": [...], "firstid", "lastid"}`.
- `mod_forum_get_forum_discussions` returns `{"discussions": [...], "warnings": []}`.
- `gradereport_user_get_grade_items` returns `{"usergrades": [{"gradeitems": [...]}], "warnings": []}`.
- `core_enrol_get_users_courses`, `mod_forum_get_forums_by_courses`, `core_course_get_contents` return bare lists.

- [ ] **Step 1: Write the failing tests**

`tests/test_moodle.py`:
```python
import pytest
import requests
from unitracker.moodle import MoodleApiError, MoodleAuthError, MoodleClient


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class FakeSession:
    """Records POSTs; answers from a queue of payloads (or raises if given an Exception)."""

    def __init__(self, *payloads):
        self.queue = list(payloads)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data or {})))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResp(item)


BASE = "https://lms.example.edu"


def test_login_success_sets_token():
    s = FakeSession({"token": "abc", "privatetoken": "x"})
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    assert c.token == "abc"
    url, data = s.calls[0]
    assert url == f"{BASE}/login/token.php"
    assert data == {"username": "u", "password": "p", "service": "moodle_mobile_app"}


def test_login_failure_raises_auth_error():
    s = FakeSession({"error": "Invalid login, please try again", "errorcode": "invalidlogin"})
    c = MoodleClient(BASE, session=s)
    with pytest.raises(MoodleAuthError, match="Invalid login"):
        c.login("u", "p")


def test_call_flattens_lists_and_adds_token_fields():
    s = FakeSession({"token": "abc"}, [{"id": 1}])
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    out = c.call("mod_forum_get_forums_by_courses", courseids=[10, 20])
    assert out == [{"id": 1}]
    url, data = s.calls[1]
    assert url == f"{BASE}/webservice/rest/server.php"
    assert data == {
        "wstoken": "abc",
        "wsfunction": "mod_forum_get_forums_by_courses",
        "moodlewsrestformat": "json",
        "courseids[0]": 10,
        "courseids[1]": 20,
    }


def test_call_raises_api_error_on_exception_payload():
    s = FakeSession({"token": "abc"}, {"exception": "moodle_exception", "errorcode": "nopermissions", "message": "Sorry"})
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    with pytest.raises(MoodleApiError, match="Sorry") as ei:
        c.call("core_course_get_contents", courseid=1)
    assert ei.value.errorcode == "nopermissions"


def test_call_retries_once_on_connection_error():
    s = FakeSession({"token": "abc"}, requests.ConnectionError("boom"), {"ok": True})
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    assert c.call("x") == {"ok": True}
    assert len(s.calls) == 3


def test_call_without_login_raises():
    c = MoodleClient(BASE, session=FakeSession())
    with pytest.raises(MoodleAuthError):
        c.call("x")


def test_typed_helpers_unwrap_envelopes():
    s = FakeSession(
        {"token": "abc"},
        {"events": [{"id": 5}], "firstid": 5, "lastid": 5},
        {"discussions": [{"id": 7}], "warnings": []},
        {"usergrades": [{"gradeitems": [{"id": 3}]}], "warnings": []},
        {"usergrades": [], "warnings": []},
    )
    c = MoodleClient(BASE, session=s)
    c.login("u", "p")
    assert c.upcoming_events(timesortfrom=100) == [{"id": 5}]
    assert s.calls[1][1]["timesortfrom"] == 100 and s.calls[1][1]["limitnum"] == 50
    assert c.discussions(9) == [{"id": 7}]
    assert s.calls[2][1]["forumid"] == 9
    assert c.grade_items(1, 2) == [{"id": 3}]
    assert c.grade_items(1, 2) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_moodle.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement moodle.py**

`unitracker/moodle.py`:
```python
"""Thin client for Moodle's mobile web-service (REST/JSON) API."""
from __future__ import annotations

from typing import Any

import requests

SERVICE = "moodle_mobile_app"


class MoodleError(Exception):
    pass


class MoodleAuthError(MoodleError):
    pass


class MoodleApiError(MoodleError):
    def __init__(self, errorcode: str, message: str):
        self.errorcode = errorcode
        super().__init__(f"{errorcode}: {message}")


def _flatten(params: dict[str, Any]) -> dict[str, Any]:
    """Moodle REST expects arrays as name[0]=..., name[1]=... ."""
    flat: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                flat[f"{key}[{i}]"] = item
        else:
            flat[key] = value
    return flat


class MoodleClient:
    def __init__(self, base_url: str, session=None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.token: str | None = None

    def _post(self, url: str, data: dict[str, Any]) -> Any:
        try:
            resp = self.session.post(url, data=data, timeout=self.timeout)
        except requests.ConnectionError:
            resp = self.session.post(url, data=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def login(self, username: str, password: str) -> None:
        payload = self._post(
            f"{self.base_url}/login/token.php",
            {"username": username, "password": password, "service": SERVICE},
        )
        if not isinstance(payload, dict) or "token" not in payload:
            msg = payload.get("error", "no token in response") if isinstance(payload, dict) else str(payload)
            raise MoodleAuthError(msg)
        self.token = payload["token"]

    def call(self, wsfunction: str, **params: Any) -> Any:
        if not self.token:
            raise MoodleAuthError("call() before login()")
        data = {"wstoken": self.token, "wsfunction": wsfunction, "moodlewsrestformat": "json"}
        data.update(_flatten(params))
        payload = self._post(f"{self.base_url}/webservice/rest/server.php", data)
        if isinstance(payload, dict) and "exception" in payload:
            raise MoodleApiError(payload.get("errorcode", "unknown"), payload.get("message", ""))
        return payload

    # --- typed helpers -------------------------------------------------

    def site_info(self) -> dict:
        return self.call("core_webservice_get_site_info")

    def courses(self, userid: int) -> list[dict]:
        return self.call("core_enrol_get_users_courses", userid=userid)

    def upcoming_events(self, timesortfrom: int, limitnum: int = 50) -> list[dict]:
        return self.call(
            "core_calendar_get_action_events_by_timesort",
            timesortfrom=timesortfrom,
            limitnum=limitnum,
        ).get("events", [])

    def news_forums(self, course_ids: list[int]) -> list[dict]:
        if not course_ids:
            return []
        forums = self.call("mod_forum_get_forums_by_courses", courseids=course_ids)
        return [f for f in forums if f.get("type") == "news"]

    def discussions(self, forum_id: int) -> list[dict]:
        return self.call("mod_forum_get_forum_discussions", forumid=forum_id).get("discussions", [])

    def course_contents(self, course_id: int) -> list[dict]:
        return self.call("core_course_get_contents", courseid=course_id)

    def grade_items(self, course_id: int, userid: int) -> list[dict]:
        payload = self.call("gradereport_user_get_grade_items", courseid=course_id, userid=userid)
        usergrades = payload.get("usergrades", [])
        return usergrades[0].get("gradeitems", []) if usergrades else []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_moodle.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add unitracker/moodle.py tests/test_moodle.py
git commit -m "feat: Moodle web-service client"
```

---

### Task 4: Snapshot dataclasses + builder

**Files:**
- Create: `unitracker/snapshot.py`
- Test: `tests/fixtures.py`, `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `MoodleClient` helper methods from Task 3, `MoodleError`.
- Produces (all `@dataclass(frozen=True)`):
  - `Course(id: int, shortname: str, fullname: str)`
  - `Event(id: int, name: str, course_shortname: str, due: int, url: str)`
  - `Discussion(id: int, course_shortname: str, subject: str, message_html: str, url: str)`
  - `Module(id: int, course_shortname: str, name: str, modname: str, url: str)`
  - `Grade(item_id: int, course_shortname: str, itemname: str, graderaw: float | None, gradeformatted: str, grademax: float | None)`
  - `Snapshot(courses: list[Course], events: list[Event], discussions: list[Discussion], modules: list[Module], grades: list[Grade], errors: list[str])` (mutable dataclass, lists default empty)
  - `build_snapshot(client: MoodleClient, userid: int, now: int) -> Snapshot`

Rules:
- Events: `due = event["timesort"]`; `course_shortname = event["course"]["shortname"]` if present else `""`; `url = event["url"]`.
- Discussions: id is `d["discussion"]` (the discussion id, not the post id); url is `{base_url}/mod/forum/discuss.php?d={id}`.
- Modules: flatten `sections[].modules[]`; skip modules with `uservisible == False`; `url = m.get("url") or ""`.
- Grades: skip items whose `itemtype` is `"course"` or `"category"`; `itemname` may be `None` → `""`.
- A `MoodleError` raised while processing a course is appended to `errors` as `f"{shortname}: {exc}"` and that course's remaining fetches are skipped; other courses continue. A `MoodleError` from `courses()` or `upcoming_events()` propagates (nothing useful can be built).

- [ ] **Step 1: Write fixtures**

`tests/fixtures.py`:
```python
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
```

- [ ] **Step 2: Write the failing tests**

`tests/test_snapshot.py`:
```python
import pytest
from tests import fixtures as fx
from unitracker.moodle import MoodleApiError
from unitracker.snapshot import Course, Discussion, Event, Grade, Module, build_snapshot


class FakeClient:
    base_url = "https://lms"

    def __init__(self, *, fail_course_contents_for=None):
        self.fail_for = fail_course_contents_for

    def courses(self, userid):
        return fx.COURSES

    def upcoming_events(self, timesortfrom, limitnum=50):
        return fx.EVENTS

    def news_forums(self, course_ids):
        return [f for f in fx.FORUMS if f["type"] == "news" and f["course"] in course_ids]

    def discussions(self, forum_id):
        return {301: fx.DISCUSSIONS_301, 303: fx.DISCUSSIONS_303}[forum_id]

    def course_contents(self, course_id):
        if course_id == self.fail_for:
            raise MoodleApiError("nopermissions", "Sorry")
        return {101: fx.CONTENTS_101, 102: fx.CONTENTS_102}[course_id]

    def grade_items(self, course_id, userid):
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
    assert snap.errors == []


def test_course_error_is_captured_and_others_continue():
    snap = build_snapshot(FakeClient(fail_course_contents_for=101), userid=1, now=0)
    assert snap.errors == ["TM112: nopermissions: Sorry"]
    assert [c.id for c in snap.courses] == [101, 102]
    assert snap.discussions[0].id == 701          # forums fetched before contents still present
    assert all(m.course_shortname == "M140" or m.id == 0 for m in snap.modules) or snap.modules == []
    assert [g.item_id for g in snap.grades] == []  # 101's grades skipped after its error; 102 has none


def test_no_courses_is_fine():
    class Empty(FakeClient):
        def courses(self, userid):
            return []

        def upcoming_events(self, timesortfrom, limitnum=50):
            return []

    snap = build_snapshot(Empty(), userid=1, now=0)
    assert snap.courses == [] and snap.events == [] and snap.errors == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot.py -q`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement snapshot.py**

`unitracker/snapshot.py`:
```python
"""Fetch everything we care about from Moodle into plain dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field

from .moodle import MoodleClient, MoodleError


@dataclass(frozen=True)
class Course:
    id: int
    shortname: str
    fullname: str


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    course_shortname: str
    due: int
    url: str


@dataclass(frozen=True)
class Discussion:
    id: int
    course_shortname: str
    subject: str
    message_html: str
    url: str


@dataclass(frozen=True)
class Module:
    id: int
    course_shortname: str
    name: str
    modname: str
    url: str


@dataclass(frozen=True)
class Grade:
    item_id: int
    course_shortname: str
    itemname: str
    graderaw: float | None
    gradeformatted: str
    grademax: float | None


@dataclass
class Snapshot:
    courses: list[Course] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    discussions: list[Discussion] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    grades: list[Grade] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build_snapshot(client: MoodleClient, userid: int, now: int) -> Snapshot:
    snap = Snapshot()

    snap.courses = [
        Course(int(c["id"]), c.get("shortname", ""), c.get("fullname", ""))
        for c in client.courses(userid)
    ]
    names = {c.id: c.shortname for c in snap.courses}

    snap.events = [
        Event(
            int(e["id"]),
            e.get("name", ""),
            (e.get("course") or {}).get("shortname", ""),
            int(e["timesort"]),
            e.get("url", ""),
        )
        for e in client.upcoming_events(timesortfrom=now)
    ]

    # Announcements: one forum-list call for all courses, then per-forum discussions.
    forums_by_course: dict[int, list[dict]] = {}
    if snap.courses:
        try:
            for f in client.news_forums(list(names)):
                forums_by_course.setdefault(int(f["course"]), []).append(f)
        except MoodleError as exc:
            snap.errors.append(f"forums: {exc}")

    for course in snap.courses:
        try:
            for forum in forums_by_course.get(course.id, []):
                for d in client.discussions(int(forum["id"])):
                    did = int(d["discussion"])
                    snap.discussions.append(
                        Discussion(
                            did,
                            course.shortname,
                            d.get("subject", ""),
                            d.get("message", "") or "",
                            f"{client.base_url}/mod/forum/discuss.php?d={did}",
                        )
                    )
            for section in client.course_contents(course.id):
                for m in section.get("modules", []):
                    if m.get("uservisible") is False:
                        continue
                    snap.modules.append(
                        Module(int(m["id"]), course.shortname, m.get("name", ""), m.get("modname", ""), m.get("url") or "")
                    )
            for g in client.grade_items(course.id, userid):
                if g.get("itemtype") in ("course", "category"):
                    continue
                snap.grades.append(
                    Grade(
                        int(g["id"]),
                        course.shortname,
                        g.get("itemname") or "",
                        g.get("graderaw"),
                        str(g.get("gradeformatted") or ""),
                        g.get("grademax"),
                    )
                )
        except MoodleError as exc:
            snap.errors.append(f"{course.shortname}: {exc}")

    return snap
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_snapshot.py -q`
Expected: 3 passed. (If `test_course_error_is_captured_and_others_continue` fails on the grades assertion, check that the `except` wraps the whole per-course block so course 101's grades are skipped after its contents error.)

- [ ] **Step 6: Commit**

```bash
git add unitracker/snapshot.py tests/fixtures.py tests/test_snapshot.py
git commit -m "feat: snapshot builder over Moodle API"
```

---

### Task 5: Checker (pure diff logic)

**Files:**
- Create: `unitracker/checker.py`
- Test: `tests/test_checker.py`

**Interfaces:**
- Consumes: `snapshot.Snapshot` and friends (Task 4), `state.State`/`EventState` (Task 2).
- Produces:
  - `checker.Alert` dataclass: `kind: str` (one of `"live" | "new_course" | "new_deadline" | "reminder" | "announcement" | "new_content" | "grade" | "course_error"`), `course: str = ""`, `title: str = ""`, `body: str = ""`, `url: str = ""`, `due: int | None = None`, `remaining: int | None = None` (seconds until due, for reminders), `items: list[tuple[str, str]]` (name, modname pairs for `new_content`), `count: int = 0` (courses tracked, for `live`).
  - `checker.check(snapshot: Snapshot, state: State, now: int) -> tuple[list[Alert], State]` — does not mutate `state`; returns a new one.
  - Constants `H72 = 72 * 3600`, `H24 = 24 * 3600`, `PRUNE_AFTER = 30 * 86400`.

Behaviour (from spec):
- `first = not state.initialized`. On first run: seed all collections, emit only `Alert(kind="live", count=len(courses))` plus any `course_error` alerts. Set `initialized=True`.
- New course id → `new_course(course=shortname, title=fullname)`.
- Event not in state → `new_deadline(course, title=name, url, due)`; store `EventState(due)`; pre-mark tiers: `remaining <= 0` → both; `remaining <= H72` → `reminded_3d`; `remaining <= H24` → `reminded_24h` (and 3d).
- Event known → update `due`; if `0 < remaining <= H24 and not reminded_24h` → `reminder(..., remaining)`, set both flags; elif `0 < remaining <= H72 and not reminded_3d` → `reminder`, set `reminded_3d`.
- Events in state whose `due < now - PRUNE_AFTER` are dropped.
- Discussion not in state → `announcement(course, title=subject, body=message_html, url)`.
- Modules not in state → grouped by course, one `new_content(course, items=[(name, modname), ...])` per course, courses in snapshot order.
- Grade: skip if `graderaw is None`. `key = str(item_id)`, `val = str(graderaw)`. If key absent or differs → `grade(course, title=itemname, body=gradeformatted)`; store.
- Each `snapshot.errors` entry → `course_error(body=msg)` (also on first run).
- Alert order in the returned list: live, course_error…, new_course…, new_deadline…, reminder…, announcement…, new_content…, grade….
- `failing` is left unchanged by `check` (main handles it).

- [ ] **Step 1: Write the failing tests**

`tests/test_checker.py`:
```python
import copy
from unitracker.checker import H24, H72, PRUNE_AFTER, Alert, check
from unitracker.snapshot import Course, Discussion, Event, Grade, Module, Snapshot
from unitracker.state import EventState, State

NOW = 1_759_500_000


def kinds(alerts):
    return [a.kind for a in alerts]


def base_snapshot():
    return Snapshot(
        courses=[Course(101, "TM112", "Intro to Computing")],
        events=[Event(501, "TMA01 is due", "TM112", NOW + 10 * 86400, "https://lms/a")],
        discussions=[Discussion(701, "TM112", "Welcome", "<p>Hi</p>", "https://lms/d")],
        modules=[Module(9002, "TM112", "Week 1 slides", "resource", "https://lms/m")],
        grades=[Grade(401, "TM112", "TMA01", 85.0, "85.00", 100.0)],
    )


def seeded_state():
    _, s = check(base_snapshot(), State(), NOW)
    return s


def test_first_run_seeds_silently():
    alerts, s = check(base_snapshot(), State(), NOW)
    assert alerts == [Alert(kind="live", count=1)]
    assert s.initialized is True
    assert s.courses == {"101": "TM112"}
    assert s.events == {"501": EventState(due=NOW + 10 * 86400)}
    assert s.discussions == {"701"} and s.modules == {"9002"} and s.grades == {"401": "85.0"}


def test_first_run_with_zero_courses():
    alerts, s = check(Snapshot(), State(), NOW)
    assert alerts == [Alert(kind="live", count=0)] and s.initialized


def test_unchanged_snapshot_yields_nothing():
    s = seeded_state()
    alerts, s2 = check(base_snapshot(), s, NOW + 3600)
    assert alerts == [] and s2 == s


def test_check_does_not_mutate_input_state():
    s = seeded_state()
    before = copy.deepcopy(s)
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Stats"))
    check(snap, s, NOW)
    assert s == before


def test_new_course():
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Introducing Statistics"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="new_course", course="M140", title="Introducing Statistics")]
    assert s.courses["102"] == "M140"


def test_new_deadline_far_away():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 5 * 86400, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="new_deadline", course="TM112", title="Quiz 1 closes", url="https://lms/q", due=NOW + 5 * 86400)]
    assert s.events["502"] == EventState(due=NOW + 5 * 86400, reminded_3d=False, reminded_24h=False)


def test_new_deadline_within_24h_premarks_both_tiers():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 3600, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert kinds(alerts) == ["new_deadline"]
    assert s.events["502"] == EventState(due=NOW + 3600, reminded_3d=True, reminded_24h=True)


def test_new_deadline_within_72h_premarks_3d_only():
    snap = base_snapshot()
    snap.events.append(Event(502, "Quiz 1 closes", "TM112", NOW + 48 * 3600, "https://lms/q"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert kinds(alerts) == ["new_deadline"]
    assert s.events["502"] == EventState(due=NOW + 48 * 3600, reminded_3d=True, reminded_24h=False)


def test_reminder_3d_fires_once():
    s = seeded_state()  # event 501 due NOW + 10d
    t = NOW + 10 * 86400 - 60 * 3600  # 60h before due
    alerts, s = check(base_snapshot(), s, t)
    assert alerts == [Alert(kind="reminder", course="TM112", title="TMA01 is due", url="https://lms/a", due=NOW + 10 * 86400, remaining=60 * 3600)]
    assert s.events["501"].reminded_3d is True and s.events["501"].reminded_24h is False
    alerts, s = check(base_snapshot(), s, t + 3600)
    assert alerts == []


def test_reminder_24h_fires_once_and_sets_both():
    s = seeded_state()
    due = NOW + 10 * 86400
    alerts, s = check(base_snapshot(), s, due - 20 * 3600)
    assert kinds(alerts) == ["reminder"] and alerts[0].remaining == 20 * 3600
    assert s.events["501"] == EventState(due=due, reminded_3d=True, reminded_24h=True)
    alerts, _ = check(base_snapshot(), s, due - 3600)
    assert alerts == []


def test_both_tiers_can_fire_in_sequence():
    s = seeded_state()
    due = NOW + 10 * 86400
    a1, s = check(base_snapshot(), s, due - 70 * 3600)
    a2, s = check(base_snapshot(), s, due - 20 * 3600)
    assert kinds(a1) == ["reminder"] and kinds(a2) == ["reminder"]


def test_no_reminder_when_past_due():
    s = seeded_state()
    due = NOW + 10 * 86400
    alerts, s = check(base_snapshot(), s, due + 10)
    assert alerts == []
    assert s.events["501"].reminded_24h is False  # untouched, simply never fires


def test_due_date_change_is_tracked():
    s = seeded_state()
    snap = base_snapshot()
    snap.events[0] = Event(501, "TMA01 is due", "TM112", NOW + 20 * 86400, "https://lms/a")
    _, s = check(snap, s, NOW)
    assert s.events["501"].due == NOW + 20 * 86400


def test_old_events_are_pruned():
    s = seeded_state()
    s.events["1"] = EventState(due=NOW - PRUNE_AFTER - 1)
    s.events["2"] = EventState(due=NOW - PRUNE_AFTER + 100)
    _, s = check(base_snapshot(), s, NOW)
    assert "1" not in s.events and "2" in s.events


def test_new_announcement():
    snap = base_snapshot()
    snap.discussions.append(Discussion(702, "TM112", "Room change", "<p>Now in B12</p>", "https://lms/d2"))
    alerts, s = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="announcement", course="TM112", title="Room change", body="<p>Now in B12</p>", url="https://lms/d2")]
    assert "702" in s.discussions


def test_new_content_grouped_per_course():
    snap = base_snapshot()
    snap.courses.append(Course(102, "M140", "Stats"))
    snap.modules += [
        Module(9005, "TM112", "Week 2 slides", "resource", ""),
        Module(9006, "M140", "Quiz 1", "quiz", ""),
        Module(9007, "TM112", "TMA02", "assign", ""),
    ]
    s = seeded_state()
    s.courses["102"] = "M140"
    alerts, s = check(snap, s, NOW)
    assert alerts == [
        Alert(kind="new_content", course="TM112", items=[("Week 2 slides", "resource"), ("TMA02", "assign")]),
        Alert(kind="new_content", course="M140", items=[("Quiz 1", "quiz")]),
    ]
    assert {"9005", "9006", "9007"} <= s.modules


def test_grade_posted_and_changed():
    snap = base_snapshot()
    snap.grades.append(Grade(402, "TM112", "Quiz 1", None, "-", 10.0))  # ungraded: ignored
    s = seeded_state()
    alerts, s = check(snap, s, NOW)
    assert alerts == []
    snap.grades[1] = Grade(402, "TM112", "Quiz 1", 9.0, "9.00", 10.0)
    alerts, s = check(snap, s, NOW)
    assert alerts == [Alert(kind="grade", course="TM112", title="Quiz 1", body="9.00")]
    snap.grades[0] = Grade(401, "TM112", "TMA01", 90.0, "90.00", 100.0)
    alerts, s = check(snap, s, NOW)
    assert alerts == [Alert(kind="grade", course="TM112", title="TMA01", body="90.00")]
    assert s.grades == {"401": "90.0", "402": "9.0"}


def test_course_errors_become_alerts_even_on_first_run():
    snap = base_snapshot()
    snap.errors = ["M140: nopermissions: Sorry"]
    alerts, _ = check(snap, State(), NOW)
    assert alerts == [Alert(kind="live", count=1), Alert(kind="course_error", body="M140: nopermissions: Sorry")]
    alerts, _ = check(snap, seeded_state(), NOW)
    assert alerts == [Alert(kind="course_error", body="M140: nopermissions: Sorry")]


def test_alert_ordering():
    snap = base_snapshot()
    snap.errors = ["x"]
    snap.courses.append(Course(102, "M140", "Stats"))
    snap.events.append(Event(502, "Quiz 1 closes", "M140", NOW + 5 * 86400, ""))
    snap.discussions.append(Discussion(702, "M140", "Hi", "", ""))
    snap.modules.append(Module(9006, "M140", "Quiz 1", "quiz", ""))
    snap.grades.append(Grade(402, "M140", "Quiz 1", 9.0, "9.00", 10.0))
    s = seeded_state()
    alerts, _ = check(snap, s, NOW + 10 * 86400 - 3600)  # also triggers 24h reminder for 501
    assert kinds(alerts) == ["course_error", "new_course", "new_deadline", "reminder", "announcement", "new_content", "grade"]


def test_failing_flag_untouched():
    s = seeded_state()
    s.failing = True
    _, s2 = check(base_snapshot(), s, NOW)
    assert s2.failing is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_checker.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement checker.py**

`unitracker/checker.py`:
```python
"""Pure diff: (snapshot, previous state, now) -> (alerts, new state)."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .snapshot import Snapshot
from .state import EventState, State

H72 = 72 * 3600
H24 = 24 * 3600
PRUNE_AFTER = 30 * 86400


@dataclass
class Alert:
    kind: str
    course: str = ""
    title: str = ""
    body: str = ""
    url: str = ""
    due: int | None = None
    remaining: int | None = None
    items: list[tuple[str, str]] = field(default_factory=list)
    count: int = 0


def check(snapshot: Snapshot, state: State, now: int) -> tuple[list[Alert], State]:
    s = copy.deepcopy(state)
    first = not s.initialized
    alerts: list[Alert] = []

    if first:
        alerts.append(Alert(kind="live", count=len(snapshot.courses)))
    alerts += [Alert(kind="course_error", body=msg) for msg in snapshot.errors]

    # Courses
    for c in snapshot.courses:
        key = str(c.id)
        if key not in s.courses and not first:
            alerts.append(Alert(kind="new_course", course=c.shortname, title=c.fullname))
        s.courses[key] = c.shortname

    # Deadlines + reminders
    new_deadlines: list[Alert] = []
    reminders: list[Alert] = []
    for e in snapshot.events:
        key = str(e.id)
        remaining = e.due - now
        if key not in s.events:
            es = EventState(due=e.due)
            if remaining <= H72:
                es.reminded_3d = True
            if remaining <= H24:
                es.reminded_24h = True
            s.events[key] = es
            if not first:
                new_deadlines.append(Alert(kind="new_deadline", course=e.course_shortname, title=e.name, url=e.url, due=e.due))
            continue
        es = s.events[key]
        es.due = e.due
        if 0 < remaining <= H24 and not es.reminded_24h:
            es.reminded_24h = True
            es.reminded_3d = True
            reminders.append(Alert(kind="reminder", course=e.course_shortname, title=e.name, url=e.url, due=e.due, remaining=remaining))
        elif 0 < remaining <= H72 and not es.reminded_3d:
            es.reminded_3d = True
            reminders.append(Alert(kind="reminder", course=e.course_shortname, title=e.name, url=e.url, due=e.due, remaining=remaining))
    for key in [k for k, es in s.events.items() if es.due < now - PRUNE_AFTER]:
        del s.events[key]
    alerts += new_deadlines + reminders

    # Announcements
    for d in snapshot.discussions:
        key = str(d.id)
        if key not in s.discussions and not first:
            alerts.append(Alert(kind="announcement", course=d.course_shortname, title=d.subject, body=d.message_html, url=d.url))
        s.discussions.add(key)

    # New content, grouped per course in snapshot order
    grouped: dict[str, list[tuple[str, str]]] = {}
    for m in snapshot.modules:
        key = str(m.id)
        if key not in s.modules and not first:
            grouped.setdefault(m.course_shortname, []).append((m.name, m.modname))
        s.modules.add(key)
    alerts += [Alert(kind="new_content", course=course, items=items) for course, items in grouped.items()]

    # Grades
    for g in snapshot.grades:
        if g.graderaw is None:
            continue
        key, val = str(g.item_id), str(g.graderaw)
        if s.grades.get(key) != val and not first:
            alerts.append(Alert(kind="grade", course=g.course_shortname, title=g.itemname, body=g.gradeformatted))
        s.grades[key] = val

    s.initialized = True
    return alerts, s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_checker.py -q`
Expected: 20 passed.

Note on `test_new_content_grouped_per_course`: `grouped` is a dict, so course order = first-seen order in `snapshot.modules` (TM112 then M140). That matches the test.

- [ ] **Step 5: Commit**

```bash
git add unitracker/checker.py tests/test_checker.py
git commit -m "feat: pure checker diff logic with reminders"
```

---

### Task 6: Formatting alerts to Telegram HTML

**Files:**
- Create: `unitracker/formatting.py`
- Test: `tests/test_formatting.py`

**Interfaces:**
- Consumes: `checker.Alert`.
- Produces:
  - `formatting.strip_html(s: str) -> str` — removes tags, unescapes entities, collapses whitespace.
  - `formatting.format_due(ts: int, tz_name: str) -> str` — e.g. `"Thu 2 Oct, 23:59"` (no leading zero on day).
  - `formatting.format_remaining(seconds: int) -> str` — `"in N hours"` if ≤ 24h (ceil, "1 hour" singular), else `"in N days"` (ceil).
  - `formatting.format_alert(alert: Alert, tz_name: str) -> str` — Telegram HTML, ≤ 4000 chars.

Message templates (all dynamic text passed through `html.escape`; `{link}` = `\n<a href="{url}">Open</a>` only when url non-empty):

| kind | text |
|---|---|
| live | `✅ Checker is live. Tracking {count} course(s).` |
| new_course | `🎓 Enrolled in <b>{title}</b> ({course})` |
| new_deadline | `📌 New deadline\n<b>{title}</b> ({course})\nDue <b>{format_due(due)}</b>{link}` |
| reminder | `⏰ Due {format_remaining(remaining)}\n<b>{title}</b> ({course})\nDue <b>{format_due(due)}</b>{link}` |
| announcement | `📢 <b>{course}</b>: {title}\n{strip_html(body)[:300]}{link}` (the body line omitted if empty; append `…` if truncated) |
| new_content | `📄 New in <b>{course}</b>:\n• {name} ({modname})` one bullet per item |
| grade | `📊 <b>{course}</b> — {title}: <b>{body}</b>` |
| course_error | `⚠️ Problem checking a course: {body}` |

- [ ] **Step 1: Write the failing tests**

`tests/test_formatting.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_formatting.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement formatting.py**

`unitracker/formatting.py`:
```python
"""Render Alerts as Telegram HTML."""
from __future__ import annotations

import html
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .checker import Alert

MAX_LEN = 4000
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s))).strip()


def format_due(ts: int, tz_name: str) -> str:
    dt = datetime.fromtimestamp(ts, ZoneInfo(tz_name))
    return f"{dt:%a} {dt.day} {dt:%b}, {dt:%H:%M}"


def format_remaining(seconds: int) -> str:
    if seconds <= 24 * 3600:
        n = max(1, math.ceil(seconds / 3600))
        return f"in {n} hour" + ("" if n == 1 else "s")
    n = math.ceil(seconds / 86400)
    return f"in {n} day" + ("" if n == 1 else "s")


def _link(url: str) -> str:
    return f'\n<a href="{html.escape(url, quote=True)}">Open</a>' if url else ""


def format_alert(a: Alert, tz_name: str) -> str:
    e = html.escape
    if a.kind == "live":
        text = f"✅ Checker is live. Tracking {a.count} course(s)."
    elif a.kind == "new_course":
        text = f"🎓 Enrolled in <b>{e(a.title)}</b> ({e(a.course)})"
    elif a.kind == "new_deadline":
        text = f"📌 New deadline\n<b>{e(a.title)}</b> ({e(a.course)})\nDue <b>{format_due(a.due, tz_name)}</b>{_link(a.url)}"
    elif a.kind == "reminder":
        text = f"⏰ Due {format_remaining(a.remaining)}\n<b>{e(a.title)}</b> ({e(a.course)})\nDue <b>{format_due(a.due, tz_name)}</b>{_link(a.url)}"
    elif a.kind == "announcement":
        body = strip_html(a.body)
        if len(body) > 300:
            body = body[:300] + "…"
        text = f"📢 <b>{e(a.course)}</b>: {e(a.title)}"
        if body:
            text += f"\n{e(body)}"
        text += _link(a.url)
    elif a.kind == "new_content":
        bullets = "\n".join(f"• {e(name)} ({e(modname)})" for name, modname in a.items)
        text = f"📄 New in <b>{e(a.course)}</b>:\n{bullets}"
    elif a.kind == "grade":
        text = f"📊 <b>{e(a.course)}</b> — {e(a.title)}: <b>{e(a.body)}</b>"
    elif a.kind == "course_error":
        text = f"⚠️ Problem checking a course: {e(a.body)}"
    else:
        text = e(f"{a.kind}: {a.title} {a.body}")
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 1] + "…"
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py -q`
Expected: 8 passed. If `test_format_due_in_cairo` fails with `ZoneInfoNotFoundError`, confirm `tzdata` is installed in the venv.

- [ ] **Step 5: Commit**

```bash
git add unitracker/formatting.py tests/test_formatting.py
git commit -m "feat: Telegram HTML formatting for alerts"
```

---

### Task 7: Telegram sender

**Files:**
- Create: `unitracker/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Produces: `telegram.TelegramError(Exception)`, `telegram.send_message(token: str, chat_id: str, text: str, session=None) -> None`. POSTs `https://api.telegram.org/bot{token}/sendMessage` with JSON `{"chat_id", "text", "parse_mode": "HTML", "disable_web_page_preview": true}`; raises `TelegramError` on non-2xx or `{"ok": false}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_telegram.py`:
```python
import pytest
from unitracker.telegram import TelegramError, send_message


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return self.resp


def test_send_ok():
    s = FakeSession(FakeResp(200, {"ok": True}))
    send_message("TOK", "42", "<b>hi</b>", session=s)
    url, body = s.calls[0]
    assert url == "https://api.telegram.org/botTOK/sendMessage"
    assert body == {"chat_id": "42", "text": "<b>hi</b>", "parse_mode": "HTML", "disable_web_page_preview": True}


def test_send_http_error():
    s = FakeSession(FakeResp(400, {"ok": False, "description": "Bad Request: chat not found"}))
    with pytest.raises(TelegramError, match="chat not found"):
        send_message("TOK", "42", "x", session=s)


def test_send_not_ok_payload():
    s = FakeSession(FakeResp(200, {"ok": False, "description": "nope"}))
    with pytest.raises(TelegramError, match="nope"):
        send_message("TOK", "42", "x", session=s)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement telegram.py**

`unitracker/telegram.py`:
```python
"""Send a message via the Telegram Bot API."""
from __future__ import annotations

import requests


class TelegramError(Exception):
    pass


def send_message(token: str, chat_id: str, text: str, session=None) -> None:
    session = session or requests.Session()
    resp = session.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 300 or not payload.get("ok"):
        raise TelegramError(f"HTTP {resp.status_code}: {payload.get('description', 'unknown error')}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add unitracker/telegram.py tests/test_telegram.py
git commit -m "feat: Telegram sender"
```

---

### Task 8: Main entry point with fail-safe handling

**Files:**
- Create: `unitracker/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `__main__.run(argv: list[str] | None = None, *, env=None, now: int | None = None, client_factory=None, sender=None) -> int`. `python -m unitracker [--dry-run]` calls `sys.exit(run())`.
  - `client_factory(base_url) -> MoodleClient`-like (default `MoodleClient`).
  - `sender(token, chat_id, text)` (default `telegram.send_message`).

Behaviour (spec "Data flow" + "Error handling"):
1. `settings = config.load(env)`; on `ConfigError`: print message to stderr; if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are present in env, best-effort send `⚠️ Checker misconfigured: missing X, Y`; return 2.
2. `state = state.load(settings.state_path)`; `now = now or int(time.time())`.
3. In `try`: client login → `site_info()["userid"]` → `build_snapshot` → `check`.
   `except Exception as exc`: print traceback to stderr; if `not state.failing`: best-effort send `⚠️ Checker failed: {type(exc).__name__}: {str(exc)[:200]}`; set `state.failing = True`; save state (unless dry-run); return 1.
4. `messages = [format_alert(a, tz) for a in alerts]`; if `state.failing`: prepend `"✅ Checker recovered."`; `new_state.failing = False`.
5. Dry-run: print each message separated by `---`, don't send, don't save; return 0.
6. Send each message; on `TelegramError`: print to stderr, return 1 without saving.
7. Save new state; print `"OK: N alert(s) sent"` to stdout; return 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py`:
```python
import json
from tests import fixtures as fx
from unitracker.__main__ import run
from unitracker.moodle import MoodleAuthError

ENV = {
    "MOODLE_URL": "https://lms",
    "MOODLE_USERNAME": "u",
    "MOODLE_PASSWORD": "p",
    "TELEGRAM_BOT_TOKEN": "T",
    "TELEGRAM_CHAT_ID": "C",
    "TZ_NAME": "UTC",
}
NOW = 1_759_500_000


class FakeClient:
    base_url = "https://lms"
    fail_login = False

    def __init__(self, base_url):
        pass

    def login(self, u, p):
        if FakeClient.fail_login:
            raise MoodleAuthError("Invalid login, please try again")

    def site_info(self):
        return fx.SITE_INFO

    def courses(self, userid):
        return fx.COURSES

    def upcoming_events(self, timesortfrom, limitnum=50):
        return []

    def news_forums(self, course_ids):
        return []

    def discussions(self, forum_id):
        return []

    def course_contents(self, course_id):
        return []

    def grade_items(self, course_id, userid):
        return []


class Sent(list):
    def __call__(self, token, chat_id, text):
        self.append((token, chat_id, text))


def env_with_state(tmp_path):
    return {**ENV, "STATE_PATH": str(tmp_path / "state.json")}


def test_config_error_returns_2_and_alerts(tmp_path, capsys):
    sent = Sent()
    env = {k: v for k, v in ENV.items() if k != "MOODLE_PASSWORD"}
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 2
    assert "MOODLE_PASSWORD" in capsys.readouterr().err
    assert sent and "misconfigured" in sent[0][2] and "MOODLE_PASSWORD" in sent[0][2]


def test_first_run_sends_live_and_saves_state(tmp_path, capsys):
    FakeClient.fail_login = False
    sent = Sent()
    env = env_with_state(tmp_path)
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 0
    assert [t for _, _, t in sent] == ["✅ Checker is live. Tracking 2 course(s)."]
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["initialized"] is True and raw["courses"] == {"101": "TM112", "102": "M140"}
    assert "OK: 1 alert(s) sent" in capsys.readouterr().out


def test_second_run_quiet(tmp_path):
    FakeClient.fail_login = False
    env = env_with_state(tmp_path)
    run([], env=env, now=NOW, client_factory=FakeClient, sender=Sent())
    sent = Sent()
    assert run([], env=env, now=NOW + 1, client_factory=FakeClient, sender=sent) == 0
    assert sent == []


def test_dry_run_prints_and_does_not_send_or_save(tmp_path, capsys):
    FakeClient.fail_login = False
    sent = Sent()
    env = env_with_state(tmp_path)
    assert run(["--dry-run"], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 0
    assert sent == []
    assert "Checker is live" in capsys.readouterr().out
    assert not (tmp_path / "state.json").exists()


def test_failure_alerts_once_then_recovers(tmp_path, capsys):
    env = env_with_state(tmp_path)
    FakeClient.fail_login = True
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 1
    assert len(sent) == 1 and sent[0][2].startswith("⚠️ Checker failed: MoodleAuthError: Invalid login")
    assert json.loads((tmp_path / "state.json").read_text())["failing"] is True
    assert "MoodleAuthError" in capsys.readouterr().err

    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 1
    assert sent == []  # suppressed while failing

    FakeClient.fail_login = False
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent) == 0
    assert [t for _, _, t in sent] == ["✅ Checker recovered.", "✅ Checker is live. Tracking 2 course(s)."]
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["failing"] is False and raw["initialized"] is True


def test_telegram_failure_does_not_save_state(tmp_path, capsys):
    FakeClient.fail_login = False
    from unitracker.telegram import TelegramError

    def bad_sender(token, chat_id, text):
        raise TelegramError("HTTP 400: chat not found")

    env = env_with_state(tmp_path)
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=bad_sender) == 1
    assert not (tmp_path / "state.json").exists()
    assert "chat not found" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -q`
Expected: FAIL — cannot import `run`.

- [ ] **Step 3: Implement __main__.py**

`unitracker/__main__.py`:
```python
"""Entry point: python -m unitracker [--dry-run]"""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from . import config, state as state_mod
from .checker import check
from .formatting import format_alert
from .moodle import MoodleClient
from .snapshot import build_snapshot
from .telegram import TelegramError, send_message


def _try_send(sender, token: str, chat_id: str, text: str) -> None:
    try:
        sender(token, chat_id, text)
    except Exception as exc:  # best effort only
        print(f"telegram send failed: {exc}", file=sys.stderr)


def run(argv=None, *, env=None, now=None, client_factory=None, sender=None) -> int:
    parser = argparse.ArgumentParser(prog="unitracker")
    parser.add_argument("--dry-run", action="store_true", help="print alerts instead of sending; don't save state")
    args = parser.parse_args(argv)
    client_factory = client_factory or MoodleClient
    sender = sender or send_message

    try:
        settings = config.load(env)
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        src = env if env is not None else __import__("os").environ
        tok, chat = src.get("TELEGRAM_BOT_TOKEN"), src.get("TELEGRAM_CHAT_ID")
        if tok and chat:
            _try_send(sender, tok, chat, "⚠️ Checker misconfigured: missing " + ", ".join(exc.missing))
        return 2

    state = state_mod.load(settings.state_path)
    now = now if now is not None else int(time.time())

    try:
        client = client_factory(settings.moodle_url)
        client.login(settings.moodle_username, settings.moodle_password)
        userid = int(client.site_info()["userid"])
        snapshot = build_snapshot(client, userid, now)
        alerts, new_state = check(snapshot, state, now)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        if not state.failing:
            _try_send(sender, settings.telegram_bot_token, settings.telegram_chat_id,
                      f"⚠️ Checker failed: {type(exc).__name__}: {str(exc)[:200]}")
        state.failing = True
        if not args.dry_run:
            state_mod.save(state, settings.state_path)
        return 1

    messages = [format_alert(a, settings.tz_name) for a in alerts]
    if state.failing:
        messages.insert(0, "✅ Checker recovered.")
    new_state.failing = False

    if args.dry_run:
        print("\n---\n".join(messages) if messages else "(no alerts)")
        return 0

    try:
        for text in messages:
            sender(settings.telegram_bot_token, settings.telegram_chat_id, text)
    except TelegramError as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)
        return 1

    state_mod.save(new_state, settings.state_path)
    print(f"OK: {len(messages)} alert(s) sent")
    return 0


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all passed (config 4, state 3, moodle 7, snapshot 3, checker 20, formatting 8, telegram 3, main 6 = 54).

- [ ] **Step 5: Commit**

```bash
git add unitracker/__main__.py tests/test_main.py
git commit -m "feat: CLI entry point with fail-safe alerts and dry-run"
```

---

### Task 9: Deployment files, README, live smoke test

**Files:**
- Create: `Dockerfile`, `railway.json`, `.github/workflows/check.yml`, `README.md`, `.env` (local only, gitignored)

- [ ] **Step 1: Dockerfile**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY unitracker ./unitracker
ENV PYTHONUNBUFFERED=1 STATE_PATH=/data/state.json
CMD ["python", "-m", "unitracker"]
```

- [ ] **Step 2: railway.json**

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "DOCKERFILE", "dockerfilePath": "Dockerfile" },
  "deploy": {
    "cronSchedule": "0 4,10,17 * * *",
    "restartPolicyType": "NEVER"
  }
}
```

- [ ] **Step 3: GitHub Actions fallback**

`.github/workflows/check.yml`:
```yaml
name: moodle-check
on:
  schedule:
    - cron: "0 4,10,17 * * *"
  workflow_dispatch:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r requirements.txt
      - name: Restore state
        uses: actions/cache/restore@v4
        with:
          path: state.json
          key: moodle-state-${{ github.run_id }}
          restore-keys: moodle-state-
      - run: python -m unitracker
        env:
          MOODLE_URL: ${{ secrets.MOODLE_URL }}
          MOODLE_USERNAME: ${{ secrets.MOODLE_USERNAME }}
          MOODLE_PASSWORD: ${{ secrets.MOODLE_PASSWORD }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - name: Save state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: state.json
          key: moodle-state-${{ github.run_id }}
```

- [ ] **Step 4: README.md**

```markdown
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
```

- [ ] **Step 5: Create local `.env` and run the live smoke test**

Create `.env` (gitignored) with the real `MOODLE_*` values from the session, and placeholder Telegram values (`TELEGRAM_BOT_TOKEN=placeholder`, `TELEGRAM_CHAT_ID=placeholder`) — dry-run never sends.

Run: `python -m unitracker --dry-run`
Expected stdout: `✅ Checker is live. Tracking 0 course(s).` and exit code 0. Confirm `state.json` was NOT created.

Then a deliberate failure check: temporarily set `MOODLE_PASSWORD=wrong` in `.env`, run `python -m unitracker --dry-run`; expected: traceback on stderr containing `MoodleAuthError`, stdout `telegram send failed:` line (placeholder token), exit 1, no `state.json`. Restore the password.

- [ ] **Step 6: Verify git ignores secrets and commit**

Run: `git status --porcelain` — `.env` and `state.json` must NOT appear.

```bash
git add Dockerfile railway.json .github/workflows/check.yml README.md
git commit -m "feat: Railway/GitHub Actions deployment and README"
```

---

## Self-review

**Spec coverage:**
- Alerts table (10 rows) → checker (Task 5) + formatting (Task 6) + main (Task 8: ⚠️/✅). ✔
- Reminder rules (past-due no reminder, once per tier, pre-marking) → Task 5 tests `test_new_deadline_within_*`, `test_reminder_*`, `test_no_reminder_when_past_due`. ✔
- Schedule → `railway.json`, workflow cron. ✔
- Architecture file list → matches File Structure (plus `tests/fixtures.py` as Python instead of JSON fixtures — same purpose). ✔
- State file → Task 2 (adds `initialized`, documented). ✔
- Config table → Task 1. ✔
- Error handling: missing config exit 2 + ⚠️ when Telegram vars present (Task 8), auth error → `MoodleAuthError` (Task 3), `exception` payload → `MoodleApiError` (Task 3), 30s timeout + one retry (Task 3), Telegram failure → exit 1, no save (Task 8), alerts sent before save (Task 8). ✔
- Testing list → Tasks 1–8; live smoke → Task 9. ✔
- Deployment README + GH Actions fallback → Task 9. ✔

**Placeholder scan:** none found.

**Type consistency:** `Alert` fields (`kind, course, title, body, url, due, remaining, items, count`) used identically in Tasks 5, 6, 8. `EventState(due, reminded_3d, reminded_24h)` consistent in Tasks 2, 5. `MoodleClient` helper names consistent between Task 3 and the `FakeClient`s in Tasks 4 and 8. `run()` keyword params consistent between Task 8 implementation and tests.
