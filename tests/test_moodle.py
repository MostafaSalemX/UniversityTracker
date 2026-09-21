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
