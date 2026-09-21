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
