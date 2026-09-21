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
NO_SLEEP = lambda s: None  # noqa: E731


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
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 2
    assert "MOODLE_PASSWORD" in capsys.readouterr().err
    assert sent and "misconfigured" in sent[0][2] and "MOODLE_PASSWORD" in sent[0][2]


def test_first_run_sends_live_and_saves_state(tmp_path, capsys):
    FakeClient.fail_login = False
    sent = Sent()
    env = env_with_state(tmp_path)
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 0
    assert [t for _, _, t in sent] == ["✅ Checker is live. Tracking 2 course(s)."]
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["initialized"] is True and raw["courses"] == {"101": "TM112", "102": "M140"}
    assert "OK: 1 alert(s) sent" in capsys.readouterr().out


def test_second_run_quiet(tmp_path):
    FakeClient.fail_login = False
    env = env_with_state(tmp_path)
    run([], env=env, now=NOW, client_factory=FakeClient, sender=Sent(), sleep=NO_SLEEP)
    sent = Sent()
    assert run([], env=env, now=NOW + 1, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 0
    assert sent == []


def test_dry_run_prints_and_does_not_send_or_save(tmp_path, capsys):
    FakeClient.fail_login = False
    sent = Sent()
    env = env_with_state(tmp_path)
    assert run(["--dry-run"], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 0
    assert sent == []
    assert "Checker is live" in capsys.readouterr().out
    assert not (tmp_path / "state.json").exists()


def test_failure_alerts_once_then_recovers(tmp_path, capsys):
    env = env_with_state(tmp_path)
    FakeClient.fail_login = True
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 1
    assert len(sent) == 1 and sent[0][2].startswith("⚠️ Checker failed: MoodleAuthError: Invalid login")
    assert json.loads((tmp_path / "state.json").read_text())["failing"] is True
    assert "MoodleAuthError" in capsys.readouterr().err

    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 1
    assert sent == []  # suppressed while failing

    FakeClient.fail_login = False
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 0
    assert [t for _, _, t in sent] == ["✅ Checker recovered.", "✅ Checker is live. Tracking 2 course(s)."]
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["failing"] is False and raw["initialized"] is True


def test_telegram_failure_does_not_save_state(tmp_path, capsys):
    FakeClient.fail_login = False
    from unitracker.telegram import TelegramError

    def bad_sender(token, chat_id, text):
        raise TelegramError("HTTP 400: chat not found")

    env = env_with_state(tmp_path)
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=bad_sender, sleep=NO_SLEEP) == 1
    assert not (tmp_path / "state.json").exists()
    assert "chat not found" in capsys.readouterr().err


def test_dry_run_failure_does_not_send(tmp_path, capsys):
    env = env_with_state(tmp_path)
    FakeClient.fail_login = True
    sent = Sent()
    try:
        assert run(["--dry-run"], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 1
        assert sent == []
        assert "[dry-run] would send: ⚠️ Checker failed" in capsys.readouterr().out
        assert not (tmp_path / "state.json").exists()
    finally:
        FakeClient.fail_login = False


def test_dry_run_config_error_does_not_send(tmp_path, capsys):
    sent = Sent()
    env = {k: v for k, v in ENV.items() if k != "MOODLE_PASSWORD"}
    assert run(["--dry-run"], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 2
    assert sent == []
    assert "misconfigured" in capsys.readouterr().out


def test_corrupt_state_file_alerts_and_sets_failing(tmp_path, capsys):
    FakeClient.fail_login = False
    env = env_with_state(tmp_path)
    (tmp_path / "state.json").write_text("{not json")
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=NO_SLEEP) == 1
    assert len(sent) == 1 and sent[0][2].startswith("⚠️ Checker failed: JSONDecodeError")
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["failing"] is True


def test_bad_timezone_alerts(tmp_path, capsys):
    # format_alert only touches the timezone for deadline/reminder alerts, and those
    # are only emitted once state is already initialized (see checker.check: `not first`).
    # So first establish state normally, then trigger a new deadline on a second run
    # with a bad TZ_NAME to exercise format_alert's ZoneInfo lookup inside the try block.
    FakeClient.fail_login = False
    env = env_with_state(tmp_path)
    run([], env=env, now=NOW, client_factory=FakeClient, sender=Sent(), sleep=NO_SLEEP)

    class ClientWithEvent(FakeClient):
        def upcoming_events(self, timesortfrom, limitnum=50):
            return fx.EVENTS

    bad_env = {**env, "TZ_NAME": "Mars/Olympus"}
    sent = Sent()
    assert run([], env=bad_env, now=NOW, client_factory=ClientWithEvent, sender=sent, sleep=NO_SLEEP) == 1
    assert len(sent) == 1 and sent[0][2].startswith("⚠️ Checker failed: ZoneInfoNotFoundError")


def test_sends_are_paced(tmp_path):
    FakeClient.fail_login = False
    env = env_with_state(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"initialized": True, "failing": True}))
    slept = []
    sent = Sent()
    assert run([], env=env, now=NOW, client_factory=FakeClient, sender=sent, sleep=slept.append) == 0
    # recovered + 2 new courses = 3 messages -> 2 pauses, none before the first
    assert len(sent) == 3 and slept == [1.0, 1.0]
