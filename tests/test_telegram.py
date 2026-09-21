import pytest
import requests
from unitracker.telegram import TelegramError, send_message


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class FakeSession:
    """Replays `resp` (a FakeResp or a list of them, one per call)."""

    def __init__(self, resp):
        self.resps = list(resp) if isinstance(resp, list) else [resp]
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return self.resps[min(len(self.calls) - 1, len(self.resps) - 1)]


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


class FakeSessionConnectionError:
    def post(self, url, json=None, timeout=None):
        raise requests.ConnectionError("Max retries exceeded with url: /botTOK/sendMessage")


def test_send_network_error_sanitizes_token():
    s = FakeSessionConnectionError()
    with pytest.raises(TelegramError) as excinfo:
        send_message("TOK", "42", "x", session=s)
    assert "TOK" not in str(excinfo.value)
    assert "<token>" in str(excinfo.value)


RATE_LIMITED = FakeResp(429, {"ok": False, "description": "Too Many Requests: retry after 7", "parameters": {"retry_after": 7}})
OK = FakeResp(200, {"ok": True})


def test_429_waits_retry_after_then_succeeds():
    s = FakeSession([RATE_LIMITED, OK])
    slept = []
    send_message("TOK", "42", "x", session=s, sleep=slept.append)
    assert slept == [7]
    assert len(s.calls) == 2


def test_429_gives_up_after_three_retries():
    s = FakeSession([RATE_LIMITED, RATE_LIMITED, RATE_LIMITED, RATE_LIMITED, OK])
    slept = []
    with pytest.raises(TelegramError, match="HTTP 429"):
        send_message("TOK", "42", "x", session=s, sleep=slept.append)
    assert slept == [7, 7, 7]
    assert len(s.calls) == 4


def test_429_without_retry_after_sleeps_one_second():
    s = FakeSession([FakeResp(429, {"ok": False, "description": "Too Many Requests"}), OK])
    slept = []
    send_message("TOK", "42", "x", session=s, sleep=slept.append)
    assert slept == [1]


def test_bad_html_falls_back_to_plain_text_once():
    bad = FakeResp(400, {"ok": False, "description": "Bad Request: can't parse entities: Unsupported start tag"})
    s = FakeSession([bad, OK])
    send_message("TOK", "42", "<x>", session=s, sleep=lambda _: None)
    assert len(s.calls) == 2
    assert s.calls[0][1]["parse_mode"] == "HTML"
    assert "parse_mode" not in s.calls[1][1]
    assert s.calls[1][1]["text"] == "<x>"


def test_bad_html_fallback_does_not_loop():
    bad = FakeResp(400, {"ok": False, "description": "Bad Request: can't parse entities: Unsupported start tag"})
    s = FakeSession([bad, bad])
    with pytest.raises(TelegramError, match="parse entities"):
        send_message("TOK", "42", "<x>", session=s, sleep=lambda _: None)
    assert len(s.calls) == 2
