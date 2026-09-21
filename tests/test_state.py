import json
from unitracker import state as st


def test_load_missing_file_gives_fresh_state(tmp_path):
    s = st.load(str(tmp_path / "nope.json"))
    assert s == st.State()
    assert s.initialized is False and s.failing is False
    assert s.courses == {} and s.events == {} and s.discussions == set()
    assert s.modules == set() and s.grades == {} and s.course_errors == {}


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
        course_errors={"M140/grades": "M140 grades: nopermissiontoviewgrades: Sorry"},
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


def test_load_pre_course_errors_state(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"version": 1, "initialized": true, "courses": {"1": "A"}}', encoding="utf-8")
    assert st.load(str(p)).course_errors == {}
