"""Thin client for Moodle's mobile web-service (REST/JSON) API."""
from __future__ import annotations

import re
import sys
from typing import Any

import requests

SERVICE = "moodle_mobile_app"
# Identify ourselves honestly: a bare "python-requests/x.y" is what bot filters
# in front of a Moodle site look for first.
USER_AGENT = "UniversityTracker/1.0 (+https://github.com/MostafaSalemX/UniversityTracker)"
DIAGNOSTIC_HEADERS = ("Server", "CF-Ray", "CF-Mitigated", "Retry-After", "Content-Type")


class MoodleError(Exception):
    pass


class MoodleAuthError(MoodleError):
    pass


class MoodleHttpError(MoodleError):
    """A non-2xx reply. Usually a proxy or WAF in front of Moodle, not Moodle."""

    def __init__(self, status: int, url: str, detail: str):
        self.status = status
        self.url = url
        self.detail = detail
        super().__init__(f"HTTP {status} for {url} ({detail})")


class MoodleApiError(MoodleError):
    def __init__(self, errorcode: str, message: str):
        self.errorcode = errorcode
        super().__init__(f"{errorcode}: {message}")


def _diagnose(resp, limit: int = 160) -> str:
    """Summarise a rejected reply: who answered, and what they said.

    `raise_for_status()` alone reports only the status code, which cannot tell a
    WAF block apart from Moodle refusing us.
    """
    bits = [f"{h.lower()}={resp.headers[h]}" for h in DIAGNOSTIC_HEADERS if resp.headers.get(h)]
    body = " ".join(re.sub(r"<[^>]+>", " ", resp.text or "").split())
    if body:
        bits.append(f"body={body[:limit]}")
    return "; ".join(bits) or "no headers or body"


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
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.timeout = timeout
        self.token: str | None = None

    def _post(self, url: str, data: dict[str, Any]) -> Any:
        try:
            resp = self.session.post(url, data=data, timeout=self.timeout)
        except requests.ConnectionError:
            resp = self.session.post(url, data=data, timeout=self.timeout)
        if resp.status_code >= 400:
            print(f"{url} -> {resp.status_code}; {_diagnose(resp, limit=600)}", file=sys.stderr)
            raise MoodleHttpError(resp.status_code, url, _diagnose(resp))
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
