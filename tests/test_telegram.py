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
