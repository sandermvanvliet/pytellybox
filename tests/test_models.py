"""Models parse the payloads of docs/admin-api.md and docs/kid-api.md (contract)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pytellybox import AdminState, Home, Info, KidProfile, KidState

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


def test_admin_state_sessions_and_inbox():
    s = AdminState.from_dict(load("admin_state.json"))
    assert [x.key for x in s.sessions] == ["tv"]
    assert s.sessions[0].label == "TV" and s.sessions[0].profile_ids == (1,) and s.sessions[0].device_id is None
    assert s.inbox.pending == 4 and s.inbox.unhealthy == 0
    assert s.inbox.latest_received_at == datetime(2026, 9, 29, 11, 42, tzinfo=UTC)


def test_older_server_without_newer_fields():
    d = load("admin_state.json")
    for key in ("sessions", "inbox"):
        del d[key]
    for p in d["profiles"]:
        for key in ("allowance_source", "max_session_source", "visible_shows"):
            del p[key]
    s = AdminState.from_dict(d)
    assert s.sessions == () and s.inbox.pending == 0 and s.inbox.latest_received_at is None
    assert s.profile(1).visible_shows is None and s.profile(1).allowance_source == "custom"


def test_profile_sources_and_visible_shows():
    s = AdminState.from_dict(load("admin_state.json"))
    assert (s.profile(1).allowance_source, s.profile(1).max_session_source) == ("inherit", "custom")
    assert s.profile(1).visible_shows == 2


def test_unlimited_allowance_is_none():
    d = load("admin_state.json")
    d["profiles"][0].update(allowance_s=None, allowance_source="unlimited", visible_shows=0)
    p = AdminState.from_dict(d).profile(1)
    assert p.allowance_s is None and p.allowance_source == "unlimited" and p.visible_shows == 0


def test_kid_profile_new_fields_and_defaults():
    p = KidProfile.from_dict({"profile_id": 1, "name": "Mila", "ui_mode": "text", "watch_in_app": True,
                              "time_up": True, "fraction_left": 0.5, "last_five": True, "unlimited": False})
    assert p.ui_mode == "text" and p.watch_in_app and p.time_up and p.fraction_left == 0.5 and p.last_five
    old = KidProfile.from_dict({"profile_id": 1, "name": "Mila", "picture": None, "avatar": "fox"})
    assert old.ui_mode == "icons" and not old.watch_in_app and not old.time_up


def test_kid_state():
    s = KidState.from_dict({
        "tv": "ok", "device_name": "Living Room TV",
        "now_playing": {"episode_id": 4, "show_id": 2, "thumb": "/img/episode/4.jpg", "title": "Alongside",
                        "state": "playing"},
        "watching": [1], "sky": {"fraction_left": 0.62, "last_five": False, "unlimited": False}, "time_up": False,
        "profiles": {"1": {"fraction_left": 0.62, "last_five": False, "unlimited": False, "time_up": False},
                     "2": {"fraction_left": None, "last_five": False, "unlimited": True, "time_up": False}},
        "day": "2026-09-29",
        "sessions": [{"key": "device:abc", "target": "device", "label": "iPhone Safari", "device_id": "abc",
                      "episode_id": 4, "show_id": 2, "profile_ids": [1], "state": "paused"}],
    })
    assert s.tv == "ok" and s.device_name == "Living Room TV" and s.watching == (1,)
    assert s.now_playing.thumb == "/img/episode/4.jpg" and s.sky.fraction_left == 0.62
    assert s.profiles[2].unlimited and s.day == date(2026, 9, 29)
    assert s.sessions[0].target == "device" and s.sessions[0].label == "iPhone Safari"


def test_kid_state_nothing_playing():
    s = KidState.from_dict({"tv": "unreachable"})
    assert s.now_playing is None and s.watching == () and s.profiles == {} and s.sessions == () and s.day is None


def test_profile_picture_watch_in_app_and_ui_mode():
    s = AdminState.from_dict(load("admin_state.json"))
    assert (s.profile(1).picture, s.profile(1).watch_in_app, s.profile(1).ui_mode) == ("/img/profile/1.jpg", False, "icons")
    assert (s.profile(2).picture, s.profile(2).watch_in_app, s.profile(2).ui_mode) == (None, True, "text")


def test_older_server_without_picture_fields():
    d = load("admin_state.json")
    for p in d["profiles"]:
        for key in ("picture", "watch_in_app", "ui_mode"):
            del p[key]
    for p in AdminState.from_dict(d).profiles:
        assert p.picture is None and p.watch_in_app is None and p.ui_mode is None


def test_watch_in_app_is_coerced_to_bool_only_when_present():
    d = load("admin_state.json")
    d["profiles"][0]["watch_in_app"] = 1
    assert AdminState.from_dict(d).profile(1).watch_in_app is True


# --------------------------------------------------------------------------- history (HA-12)


def _history_payload(last_watched):
    return {"today": "2026-10-06", "days": 2, "profiles": [{
        "id": 1, "name": "Mila", "last_watched": last_watched,
        "days": [{"date": "2026-10-06", "used_s": 1200, "extra_s": 0, "unlimited": False, "blocked": False},
                 {"date": "2026-10-05", "used_s": 2710, "extra_s": 900, "unlimited": True, "blocked": True}]}]}


def test_usage_history_parses():
    from pytellybox import UsageHistory

    h = UsageHistory.from_dict(_history_payload({
        "episode_id": 4, "title": "Alongside", "show": "Harbour Pups",
        "started_at": "2026-10-06T07:10:00+00:00", "ended_at": None, "target": "tv"}))
    assert h.today == date(2026, 10, 6) and h.days == 2
    mila = h.profiles[0]
    assert (mila.id, mila.name) == (1, "Mila")
    assert mila.days[0].date == date(2026, 10, 6) and mila.days[0].used_s == 1200
    assert mila.days[1].extra_s == 900 and mila.days[1].unlimited and mila.days[1].blocked
    lw = mila.last_watched
    assert lw.episode_id == 4 and lw.title == "Alongside" and lw.show == "Harbour Pups"
    assert lw.started_at == datetime(2026, 10, 6, 7, 10, tzinfo=UTC) and lw.ended_at is None and lw.target == "tv"


def test_usage_history_tolerates_missing_last_watched_and_null_episode():
    from pytellybox import UsageHistory

    assert UsageHistory.from_dict(_history_payload(None)).profiles[0].last_watched is None
    payload = _history_payload(None)
    del payload["profiles"][0]["last_watched"]
    assert UsageHistory.from_dict(payload).profiles[0].last_watched is None
    lw = UsageHistory.from_dict(_history_payload({
        "episode_id": None, "title": None, "show": None, "started_at": "2026-10-05T17:00:00Z",
        "ended_at": "2026-10-05T17:20:00+00:00", "target": "device"})).profiles[0].last_watched
    assert lw.episode_id is None and lw.title is None and lw.show is None
    assert lw.started_at.tzinfo is not None and lw.ended_at == datetime(2026, 10, 5, 17, 20, tzinfo=UTC)


def test_info_supports():
    i = Info.from_dict({"instance_id": "abc", "version": "dev", "api": 1, "capabilities": ["state", "history"]})
    assert i.supports("history") and not i.supports("nope")
    assert not Info.from_dict({"instance_id": "a", "version": "d", "api": 1}).supports("history")
