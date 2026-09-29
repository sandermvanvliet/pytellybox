"""Models parse the payloads of docs/admin-api.md and docs/kid-api.md (contract)."""

import json
from datetime import date
from pathlib import Path

from pytellybox import AdminState, Home, Info

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_admin_state_parses_every_section():
    s = AdminState.from_dict(load("admin_state.json"))
    assert s.day.date == date(2026, 9, 29)
    assert s.tv.reachable and s.tv.device == "TV"
    assert s.now_playing.profile_ids == (1,) and s.now_playing.thumb_path == "/img/episode/4.jpg"
    assert [p.name for p in s.profiles] == ["Mila", "Noah"]
    assert s.profile(2).time_up and not s.profile(1).time_up
    assert s.jobs.held_ready == 3 and s.disk.media_bytes == 48213000000
    assert s.raw["api"] == 1


def test_cold_start_state_has_nulls():
    d = load("admin_state.json")
    d["day"] = {"date": None, "resets_at": None}
    d["now_playing"] = None
    d["profiles"][0].update(used_s=None, extra_s=None, remaining_s=None, can_start=None, reason=None)
    s = AdminState.from_dict(d)
    assert s.day.date is None and s.now_playing is None
    assert s.profile(1).can_start is None and not s.profile(1).time_up


def test_unknown_fields_are_ignored():
    d = load("admin_state.json")
    d["something_new"] = {"x": 1}
    d["profiles"][0]["future"] = True
    assert AdminState.from_dict(d).profile(1).name == "Mila"


def test_info_and_home():
    i = Info.from_dict({"instance_id": "abc", "version": "dev", "api": 1, "capabilities": ["state"]})
    assert i.capabilities == ("state",)
    h = Home.from_dict({"continue": [{"episode_id": 4, "show_id": 2, "thumb": "/img/episode/4.jpg", "title": "A",
                                      "progress": 0.4, "finished": False, "kind": "resume"}],
                        "shows": [{"show_id": 2, "artwork": "/img/show/2.jpg", "title": "Pups"}]})
    assert h.continue_watching[0].kind == "resume" and h.shows[0].title == "Pups"
