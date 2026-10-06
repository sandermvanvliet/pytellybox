"""The mock server, driven by the real client."""

import asyncio
import json

import aiohttp
import pytest

from pytellybox import (
    TellyboxAuthError,
    TellyboxClient,
    TellyboxForbiddenError,
    TellyboxNotFoundError,
    TellyboxRequestError,
    TellyboxTimeUpError,
)
from pytellybox.mock import MockTellybox, default_state, main
from tests.conftest import READ_TOKEN


async def next_event(stream, timeout=2.0):
    return await asyncio.wait_for(anext(stream), timeout)


def test_packaged_state_matches_the_fixture(state_dict):
    assert default_state() == state_dict


async def test_info_and_state(client, mock):
    info = await client.info()
    assert info.api == 1 and "overrides" in info.capabilities
    state = await client.state()
    assert state.profile(1).name == "Mila" and state.now_playing.show == "Harbour Pups"


async def test_events_first_state_then_updates_and_keepalive(client, mock):
    stream = client.events()
    first = await next_event(stream)
    assert first.group.remaining_s == 1790
    await asyncio.sleep(0.2)  # several keepalives (50 ms) pass without yielding anything
    task = asyncio.create_task(client.add_time(10, [1]))
    pushed = await next_event(stream)
    await task
    assert pushed.profile(1).extra_s == 900 + 600
    assert pushed.group.remaining_s == 1790 + 600
    await stream.aclose()


async def test_extra_time_raises_extra_and_remaining(client):
    state = await client.add_time(15, [2])
    noah = state.profile(2)
    assert (noah.extra_s, noah.remaining_s, noah.can_start, noah.reason) == (900, 900, True, None)
    assert state.profile(1).extra_s == 900  # untouched
    everyone = await client.add_time(5)
    assert everyone.profile(1).extra_s == 1200 and everyone.profile(2).extra_s == 1200


async def test_unlimited_and_clear(client):
    state = await client.set_unlimited([2])
    noah = state.profile(2)
    assert noah.unlimited and noah.remaining_s is None and noah.can_start
    state = await client.clear_today([2])
    noah = state.profile(2)
    assert not noah.unlimited and noah.remaining_s == 0 and noah.can_start is False and noah.reason == "allowance"


async def test_block_and_clear(client):
    state = await client.block([1])
    mila = state.profile(1)
    assert mila.blocked and mila.can_start is False and mila.reason == "blocked"
    assert state.now_playing is None  # a blocked watcher stops at once
    assert not mila.watching
    state = await client.clear_today()
    mila = state.profile(1)
    assert not mila.blocked and mila.can_start and mila.remaining_s == 1790


async def test_stop_now(client):
    state = await client.stop_now()
    assert state.now_playing is None and not any(p.watching for p in state.profiles)


async def test_override_validation(client):
    with pytest.raises(TellyboxRequestError):
        await client.block([99])
    with pytest.raises(TellyboxRequestError):
        await client.block([1, 1])
    with pytest.raises(TellyboxRequestError):
        await client.clear_today([99])


async def test_mock_rejects_bad_minutes_itself(mock, session):
    async with session.post(mock.base_url + "/api/admin/overrides/extra", json={"minutes": 999},
                            headers={"Authorization": "Bearer tbx_secret_token_value"}) as resp:
        assert resp.status == 422


async def test_auth_rules(mock, session):
    anonymous = TellyboxClient(mock.base_url, None, session)
    with pytest.raises(TellyboxAuthError):
        await anonymous.state()
    wrong = TellyboxClient(mock.base_url, "tbx_nope", session)
    with pytest.raises(TellyboxAuthError):
        await wrong.state()
    with pytest.raises(TellyboxAuthError):
        async for _ in wrong.events():
            pass
    assert (await anonymous.info()).api == 1  # no token needed


async def test_read_only_token(mock, session):
    reader = TellyboxClient(mock.base_url, READ_TOKEN, session)
    assert (await reader.state()).instance_id
    first = await next_event(reader.events())
    assert first.instance_id
    for call in (lambda: reader.add_time(5), reader.set_unlimited, reader.block, reader.stop_now,
                 reader.clear_today):
        with pytest.raises(TellyboxForbiddenError):
            await call()
    assert (await reader.state()).profile(1).extra_s == 900  # nothing changed


async def test_kid_browse(client):
    profiles = await client.kid_profiles()
    assert [p.name for p in profiles] == ["Mila", "Noah"] and profiles[0].avatar == "fox"
    home = await client.home([1])
    assert home.shows and home.continue_watching[0].kind == "next"
    show = await client.show(home.shows[0].show_id)
    assert show.title == "Harbour Pups" and [e.episode_id for e in show.episodes] == [4, 5]
    with pytest.raises(TellyboxNotFoundError):
        await client.show(999)
    with pytest.raises(TellyboxRequestError):
        await client.home([99])


async def test_images_need_no_token(client, session):
    async with session.get(client.url("/img/episode/4.jpg")) as resp:
        assert resp.status == 200 and (await resp.read())


async def test_play_pause_resume_and_time_up(client, mock):
    stream = client.events()
    await next_event(stream)
    await client.stop_now()
    await next_event(stream)
    await client.play(5, [1])
    playing = await next_event(stream)
    assert playing.now_playing.episode_id == 5 and playing.profile(1).watching
    await client.pause()
    assert (await next_event(stream)).now_playing.state == "paused"
    await client.resume()
    assert (await next_event(stream)).now_playing.state == "playing"
    with pytest.raises(TellyboxTimeUpError):  # Noah is out of time
        await client.play(5, [1, 2])
    await stream.aclose()


async def test_play_unknown_episode(client):
    with pytest.raises(TellyboxNotFoundError):
        await client.play(999, [1])


async def test_calls_are_recorded(client, mock):
    await client.add_time(5, [1])
    await client.clear_today([1])
    assert [(c["method"], c["path"]) for c in mock.calls] == [
        ("POST", "/api/admin/overrides/extra"), ("DELETE", "/api/admin/overrides/today")]
    assert mock.calls[0]["json"] == {"minutes": 5, "profile_ids": [1]}
    assert mock.calls[1]["query"] == {"profile_ids": "1"}


async def test_set_state_pushes(client, mock, state_dict):
    stream = client.events()
    await next_event(stream)
    state_dict["tv"] = {"connection": "unreachable", "reachable": False, "device": None}
    mock.set_state(state_dict)
    assert (await next_event(stream)).tv.reachable is False
    await stream.aclose()


async def test_start_and_stop(session):
    m = MockTellybox(token="tbx_x")
    url = await m.start()
    try:
        assert (await TellyboxClient(url, "tbx_x", session).state()).api == 1
    finally:
        await m.stop()
    assert json.loads(json.dumps(m.state))["api"] == 1


def test_cli_parses(monkeypatch):
    seen = {}

    async def fake_serve(host, port, mock):
        seen.update(host=host, port=port, tokens=mock.tokens, read=mock.read_tokens)

    monkeypatch.setattr("pytellybox.mock._serve", fake_serve)
    main(["--port", "8123", "--token", "tbx_a", "--read-token", "tbx_r"])
    assert seen == {"host": "127.0.0.1", "port": 8123, "tokens": {"tbx_a"}, "read": {"tbx_r"}}


async def test_info_lists_inbox_capability(client):
    assert "inbox" in (await client.info()).capabilities


async def test_kid_state_and_events_follow_playback(client, mock):
    state = await client.kid_state()
    assert state.tv == "ok" and state.device_name == "TV" and state.now_playing.episode_id == 4
    assert [s.key for s in state.sessions] == ["tv"]
    stream = client.kid_events()
    assert (await next_event(stream)).watching == (1,)
    await client.play(5, [1])
    after = await next_event(stream)
    assert after.now_playing.episode_id == 5 and after.sessions[0].episode_id == 5
    await client.stop_now()
    stopped = await next_event(stream)
    assert stopped.now_playing is None and stopped.sessions == ()
    await stream.aclose()


async def test_admin_sessions_follow_playback(client, mock):
    await client.play(6, [1])
    assert [(s.key, s.episode_id) for s in (await client.state()).sessions] == [("tv", 6)]
    await client.stop_now()
    assert (await client.state()).sessions == ()


async def test_unlimited_allowance_profile(client, mock):
    state = dict(mock.state)
    state["profiles"][1].update(allowance_s=None, allowance_source="unlimited")
    mock.set_state(state)
    await client.add_time(5, [2])  # recomputes the timer
    noah = (await client.state()).profile(2)
    assert noah.allowance_s is None and noah.remaining_s is None and noah.can_start
    assert noah.allowance_source == "unlimited"


async def test_kid_profiles_carry_ui_fields(client):
    profiles = await client.kid_profiles()
    assert profiles[0].ui_mode == "icons" and profiles[0].watch_in_app is False


async def test_state_and_events_carry_the_profile_fields(client):
    state = await client.state()
    assert (state.profile(1).picture, state.profile(1).watch_in_app, state.profile(1).ui_mode) == (
        "/img/profile/1.jpg", False, "icons")
    stream = client.events()
    first = await next_event(stream)
    await stream.aclose()
    assert first.profile(2).ui_mode == "text" and first.profile(2).watch_in_app is True and first.profile(2).picture is None


async def test_image_jpeg_for_a_profile_with_a_picture(client, mock):
    image = await client.image((await client.state()).profile(1).picture)
    assert image.content_type == "image/jpeg" and image.content.startswith(b"\xff\xd8") and image.content.endswith(b"\xff\xd9")
    assert "Authorization" not in mock.calls[-1] and mock.calls[-1]["path"] == "/img/profile/1.jpg"


async def test_image_profile_without_picture_or_unknown_is_not_found(client):
    for path in ("/img/profile/2.jpg", "/img/profile/99.jpg", "/img/profile/x.jpg"):
        with pytest.raises(TellyboxNotFoundError):
            await client.image(path)


async def test_image_avatar_svg_for_any_key(client):
    image = await client.image("/static/avatars/whatever.svg")
    assert image.content_type == "image/svg+xml" and image.content.startswith(b"<svg")


async def test_image_other_kinds_still_served(client):
    assert (await client.image("/img/episode/4.jpg")).content_type == "image/gif"


async def test_mock_serves_the_old_shape_and_kid_profiles_follow_the_state(mock, client):
    state = mock.state
    for p in state["profiles"]:
        for key in ("picture", "watch_in_app", "ui_mode"):
            del p[key]
    mock.push()
    p = (await client.state()).profile(1)
    assert (p.picture, p.watch_in_app, p.ui_mode) == (None, None, None)
    kid = (await client.kid_profiles())[0]
    assert kid.picture is None and kid.watch_in_app is False and kid.ui_mode == "icons"


# --------------------------------------------------------------------------- history (HA-12)


async def test_history_shape_through_the_client(client):
    assert (await client.info()).supports("history")
    h = await client.history()
    assert h.days == 7 and [p.name for p in h.profiles] == ["Mila", "Noah"]
    assert h.today.isoformat() == (await client.state()).day.date.isoformat()
    for p in h.profiles:
        assert len(p.days) == 7
        assert [d.date for d in p.days] == sorted((d.date for d in p.days), reverse=True)
        assert p.days[0].date == h.today
    mila, noah = h.profiles
    assert mila.days[0].used_s == 1200 and mila.days[1].extra_s == 900 and mila.days[3].used_s == 0
    assert mila.days[2].unlimited and noah.days[0].blocked
    assert mila.last_watched.title == "Alongside" and mila.last_watched.show == "Harbour Pups"
    assert noah.last_watched is None


async def test_history_days_and_profile_filter(client):
    h = await client.history(days=1, profile_ids=[2])
    assert [p.id for p in h.profiles] == [2] and len(h.profiles[0].days) == 1
    assert len((await client.history(days=21)).profiles[0].days) == 21


async def test_history_bad_query_is_422(mock, client, session):
    with pytest.raises(TellyboxRequestError):
        await client.history(profile_ids=[99])
    for query in ("days=0", "days=22", "days=x", "profile_ids=a", "profile_ids=1,1"):
        async with session.get(f"{mock.base_url}/api/admin/history?{query}",
                               headers={"Authorization": f"Bearer {READ_TOKEN}"}) as resp:
            assert resp.status == 422, query


async def test_history_needs_a_token_but_read_is_enough(mock, session):
    with pytest.raises(TellyboxAuthError):
        await TellyboxClient(mock.base_url, None, session).history()
    assert (await TellyboxClient(mock.base_url, READ_TOKEN, session).history()).profiles


async def test_history_old_server_option(session):
    from aiohttp.test_utils import TestServer

    old = MockTellybox(token="tbx_mock", history=False)
    server = TestServer(old.app)
    await server.start_server()
    try:
        c = TellyboxClient(str(server.make_url("")).rstrip("/"), "tbx_mock", session)
        assert not (await c.info()).supports("history")
        with pytest.raises(TellyboxNotFoundError):
            await c.history()
    finally:
        await server.close()
