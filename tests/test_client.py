"""The client against a scripted server: requests, error mapping and the SSE reader."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import pytellybox.client as client_module
from pytellybox import (
    TellyboxAuthError,
    TellyboxClient,
    TellyboxConnectionError,
    TellyboxError,
    TellyboxForbiddenError,
    TellyboxNotFoundError,
    TellyboxRequestError,
    TellyboxTimeUpError,
    TellyboxUnavailableError,
)

TOKEN = "tbx_secret_token_value"


class Script:
    """A catch-all server: answers with `respond(request)` and records what it saw."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.respond: Callable[[web.Request], web.StreamResponse] = lambda r: web.json_response({})

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.read()
        self.requests.append({
            "method": request.method, "path": request.path, "query": dict(request.query),
            "json": json.loads(body) if body else None, "auth": request.headers.get("Authorization"),
        })
        result = self.respond(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    @property
    def last(self) -> dict:
        return self.requests[-1]


@pytest.fixture
async def script() -> AsyncIterator[Script]:
    s = Script()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", s.handle)
    server = TestServer(app)
    await server.start_server()
    s.url = str(server.make_url("")).rstrip("/")  # type: ignore[attr-defined]
    yield s
    await server.close()


@pytest.fixture
def api(script: Script, session: aiohttp.ClientSession) -> TellyboxClient:
    return TellyboxClient(script.url + "/", TOKEN, session)  # type: ignore[attr-defined]


def reply(data, status: int = 200) -> Callable[[web.Request], web.Response]:
    return lambda r: web.json_response(data, status=status)


# --------------------------------------------------------------------------- basics


def test_url_helpers(session):
    c = TellyboxClient("https://tellybox.test/", None, session)
    assert c.base_url == "https://tellybox.test"
    assert c.url("/img/episode/4.jpg") == "https://tellybox.test/img/episode/4.jpg"
    assert c.url("img/show/2.jpg") == "https://tellybox.test/img/show/2.jpg"
    assert "tbx" not in repr(TellyboxClient("https://tellybox.test", TOKEN, session))


async def test_session_is_not_closed(api, script, session):
    script.respond = reply({"instance_id": "a", "version": "1", "api": 1, "capabilities": []})
    await api.info()
    assert not session.closed


async def test_info_sends_no_token(api, script):
    script.respond = reply({"instance_id": "abc", "version": "1.2", "api": 1, "capabilities": ["state"]})
    info = await api.info()
    assert (info.instance_id, info.capabilities) == ("abc", ("state",))
    assert script.last["path"] == "/api/info" and script.last["auth"] is None


async def test_state_sends_bearer(api, script, state_dict):
    script.respond = reply(state_dict)
    state = await api.state()
    assert [p.name for p in state.profiles] == ["Mila", "Noah"]
    assert script.last["auth"] == f"Bearer {TOKEN}"


async def test_kid_api_sends_no_token(api, script, state_dict):
    script.respond = reply([{"profile_id": 1, "name": "Mila", "picture": None, "avatar": "fox"}])
    profiles = await api.kid_profiles()
    assert profiles[0].name == "Mila"
    assert script.last["auth"] is None


# --------------------------------------------------------------------------- overrides


async def test_add_time_body(api, script, state_dict):
    script.respond = reply(state_dict)
    await api.add_time(15, profile_ids=[1, 3])
    assert (script.last["method"], script.last["path"]) == ("POST", "/api/admin/overrides/extra")
    assert script.last["json"] == {"minutes": 15, "profile_ids": [1, 3]}
    await api.add_time(30)
    assert script.last["json"] == {"minutes": 30}


@pytest.mark.parametrize("minutes", [0, -5, 241, 1000, 1.5, "15", True, None])
async def test_add_time_validates_before_sending(api, script, minutes):
    with pytest.raises(ValueError):
        await api.add_time(minutes)
    assert script.requests == []


@pytest.mark.parametrize("minutes", [1, 240])
async def test_add_time_bounds_are_allowed(api, script, state_dict, minutes):
    script.respond = reply(state_dict)
    await api.add_time(minutes)
    assert script.last["json"]["minutes"] == minutes


@pytest.mark.parametrize(("call", "path"), [("set_unlimited", "unlimited"), ("block", "block")])
async def test_profile_overrides(api, script, state_dict, call, path):
    script.respond = reply(state_dict)
    await getattr(api, call)([2])
    assert (script.last["method"], script.last["path"]) == ("POST", f"/api/admin/overrides/{path}")
    assert script.last["json"] == {"profile_ids": [2]}
    await getattr(api, call)()
    assert script.last["json"] == {}
    assert script.last["auth"] == f"Bearer {TOKEN}"


async def test_stop_now(api, script, state_dict):
    script.respond = reply(state_dict)
    state = await api.stop_now()
    assert state.instance_id == state_dict["instance_id"]
    assert (script.last["method"], script.last["path"], script.last["json"]) == (
        "POST", "/api/admin/overrides/stop", {})


async def test_clear_today_uses_query(api, script, state_dict):
    script.respond = reply(state_dict)
    await api.clear_today([1, 3])
    assert (script.last["method"], script.last["path"]) == ("DELETE", "/api/admin/overrides/today")
    assert script.last["query"] == {"profile_ids": "1,3"}
    await api.clear_today()
    assert script.last["query"] == {}


# --------------------------------------------------------------------------- kid API


async def test_home_and_show(api, script):
    script.respond = reply({
        "continue": [{"episode_id": 4, "show_id": 2, "thumb": "/img/episode/4.jpg", "title": "A", "progress": 0.4,
                      "finished": False, "kind": "resume"}],
        "shows": [{"show_id": 2, "artwork": "/img/show/2.jpg", "title": "Pups"}]})
    home = await api.home([1, 3])
    assert script.last["query"] == {"profiles": "1,3"}
    assert home.continue_watching[0].kind == "resume" and home.shows[0].title == "Pups"
    await api.home()
    assert script.last["query"] == {}

    script.respond = reply({"show_id": 2, "artwork": "/img/show/2.jpg", "title": "Pups", "episodes": []})
    show = await api.show(2, [1])
    assert (script.last["path"], script.last["query"]) == ("/api/kid/shows/2", {"profiles": "1"})
    assert show.title == "Pups"


async def test_play_pause_resume(api, script):
    script.respond = reply({"tv": "ok"})
    assert await api.play(4, [1, 3]) is None
    assert (script.last["path"], script.last["json"]) == ("/api/kid/play", {"episode_id": 4, "profile_ids": [1, 3]})
    await api.pause()
    assert script.last["path"] == "/api/kid/pause"
    await api.resume()
    assert script.last["path"] == "/api/kid/resume"
    assert script.last["auth"] is None


# --------------------------------------------------------------------------- errors


@pytest.mark.parametrize(("status", "exc"), [
    (401, TellyboxAuthError), (403, TellyboxForbiddenError), (404, TellyboxNotFoundError),
    (400, TellyboxRequestError), (422, TellyboxRequestError), (503, TellyboxUnavailableError),
    (500, TellyboxError), (409, TellyboxError),
])
async def test_error_mapping(api, script, status, exc):
    script.respond = reply({"detail": "because"}, status)
    with pytest.raises(exc) as err:
        await api.stop_now()
    assert type(err.value) is exc
    assert str(err.value) == "because"
    assert TOKEN not in str(err.value) and TOKEN not in repr(err.value)


async def test_409_on_play_is_time_up(api, script):
    script.respond = reply({"tv": "ok", "time_up": True}, 409)
    with pytest.raises(TellyboxTimeUpError):
        await api.play(4, [1])


async def test_422_carries_detail_even_when_structured(api, script):
    script.respond = reply({"detail": [{"msg": "minutes too big"}]}, 422)
    with pytest.raises(TellyboxRequestError, match="minutes too big"):
        await api.block([99])


async def test_error_without_json_body(api, script):
    script.respond = lambda r: web.Response(status=502, text="<html>bad gateway</html>")
    with pytest.raises(TellyboxError, match="HTTP 502"):
        await api.state()


async def test_non_json_success_is_an_error(api, script):
    script.respond = lambda r: web.Response(text="hello")
    with pytest.raises(TellyboxError):
        await api.state()


async def test_connection_refused(session):
    c = TellyboxClient("http://127.0.0.1:1", TOKEN, session)
    with pytest.raises(TellyboxConnectionError) as err:
        await c.state()
    assert TOKEN not in str(err.value)


async def test_timeout_is_a_connection_error(script, session):
    async def slow(request):
        await asyncio.sleep(1)
        return web.json_response({})

    script.respond = slow
    c = TellyboxClient(script.url, TOKEN, session, timeout=0.05)  # type: ignore[attr-defined]
    with pytest.raises(TellyboxConnectionError):
        await c.state()


async def test_token_never_logged(api, script, state_dict, caplog):
    caplog.set_level("DEBUG")
    script.respond = reply(state_dict)
    await api.state()
    script.respond = reply({"detail": "forbidden"}, 403)
    with pytest.raises(TellyboxForbiddenError):
        await api.block()
    assert TOKEN not in caplog.text


# --------------------------------------------------------------------------- SSE


def sse(chunks: list[bytes], *, hang: bool = False) -> Callable[[web.Request], web.StreamResponse]:
    async def handler(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        for chunk in chunks:
            await resp.write(chunk)
            await asyncio.sleep(0.01)
        if hang:
            await asyncio.sleep(5)
        return resp

    return handler


def event(state: dict) -> bytes:
    return f"data: {json.dumps(state)}\n\n".encode()


async def test_events_first_event_then_end(api, script, state_dict):
    later = {**state_dict, "version": "later"}
    script.respond = sse([event(state_dict), event(later)])
    got = []
    with pytest.raises(TellyboxConnectionError, match="ended"):
        async for state in api.events():
            got.append(state.version)
    assert got == [state_dict["version"], "later"]
    assert script.last["path"] == "/api/admin/events" and script.last["auth"] == f"Bearer {TOKEN}"


async def test_events_skip_keepalive_and_other_fields(api, script, state_dict):
    script.respond = sse([b": keepalive\n\n", b"event: state\nid: 7\n", event(state_dict), b": keepalive\n\n"])
    got = []
    with pytest.raises(TellyboxConnectionError):
        async for state in api.events():
            got.append(state)
    assert len(got) == 1


async def test_events_multiline_data_and_crlf(api, script, state_dict):
    text = json.dumps(state_dict, indent=1).split("\n")
    chunk = ("".join(f"data: {line}\r\n" for line in text) + "\r\n").encode()
    script.respond = sse([chunk, b"data:" + json.dumps(state_dict).encode() + b"\n\n"])
    got = []
    with pytest.raises(TellyboxConnectionError):
        async for state in api.events():
            got.append(state)
    assert len(got) == 2 and got[0].profiles[1].name == "Noah"


async def test_events_incomplete_event_is_dropped(api, script, state_dict):
    script.respond = sse([event(state_dict), b"data: {\"instance_id\":"])
    got = []
    with pytest.raises(TellyboxConnectionError):
        async for state in api.events():
            got.append(state)
    assert len(got) == 1


async def test_events_401_on_connect(api, script):
    script.respond = reply({"detail": "unauthorized"}, 401)
    with pytest.raises(TellyboxAuthError):
        async for _ in api.events():
            pass


async def test_events_403_on_connect(api, script):
    script.respond = reply({"detail": "forbidden"}, 403)
    with pytest.raises(TellyboxForbiddenError):
        async for _ in api.events():
            pass


async def test_events_bad_payload(api, script):
    script.respond = sse([b"data: not json\n\n"])
    with pytest.raises(TellyboxError) as err:
        async for _ in api.events():
            pass
    assert not isinstance(err.value, TellyboxConnectionError)


async def test_events_read_timeout_is_a_connection_error(api, script, state_dict, monkeypatch):
    monkeypatch.setattr(client_module, "EVENTS_READ_TIMEOUT_S", 0.1)
    script.respond = sse([event(state_dict)], hang=True)
    got = []
    with pytest.raises(TellyboxConnectionError):
        async for state in api.events():
            got.append(state)
    assert len(got) == 1


async def test_events_connection_refused(session):
    c = TellyboxClient("http://127.0.0.1:1", TOKEN, session)
    with pytest.raises(TellyboxConnectionError):
        async for _ in c.events():
            pass


async def test_kid_state(api, script):
    script.respond = reply({"tv": "ok", "device_name": "TV", "watching": [1], "time_up": False})
    state = await api.kid_state()
    assert state.tv == "ok" and state.device_name == "TV" and state.watching == (1,)
    assert script.last["path"] == "/api/kid/state" and script.last["auth"] is None


async def test_kid_events_stream_needs_no_token(api, script):
    script.respond = sse([event({"tv": "ok", "watching": []}), b": keepalive\n\n", event({"tv": "unreachable"})])
    got = []
    with pytest.raises(TellyboxConnectionError, match="ended"):
        async for state in api.kid_events():
            got.append(state.tv)
    assert got == ["ok", "unreachable"]
    assert script.last["path"] == "/api/kid/events" and script.last["auth"] is None


async def test_kid_events_bad_payload(api, script):
    script.respond = sse([b"data: [1, 2]\n\n"])
    with pytest.raises(TellyboxError, match="not a state"):
        async for _ in api.kid_events():
            pass


# --------------------------------------------------------------------------- image()


def image_reply(body: bytes, content_type: str = "image/jpeg", charset: str | None = None):
    def respond(request):
        return web.Response(body=body, content_type=content_type, charset=charset)

    return respond


@pytest.mark.parametrize(("path", "ctype"), [("/img/profile/1.jpg", "image/jpeg"),
                                             ("/static/avatars/fox.svg", "image/svg+xml")])
async def test_image_returns_bytes_and_bare_content_type(api, script, path, ctype):
    script.respond = image_reply(b"data", ctype, charset="utf-8" if ctype.endswith("xml") else None)
    image = await api.image(path)
    assert image == client_module.Image(b"data", ctype)
    assert script.last["path"] == path and script.last["auth"] is None  # no Authorization, though a token is set


@pytest.mark.parametrize("path", ["/api/admin/state", "img/profile/1.jpg", "/imgs/x.jpg", "/static/other/x.svg",
                                  "/img/../api/admin/state", "http://elsewhere.example/img/a.jpg", ""])
async def test_image_bad_path_raises_before_any_request(api, script, path):
    with pytest.raises(ValueError):
        await api.image(path)
    assert script.requests == []


async def test_image_404_is_not_found(api, script):
    script.respond = reply({"detail": "not_found"}, 404)
    with pytest.raises(TellyboxNotFoundError):
        await api.image("/img/profile/9.jpg")


async def test_image_exactly_at_the_cap_is_fine(api, script):
    script.respond = image_reply(b"x" * client_module.IMAGE_MAX_BYTES)
    assert len((await api.image("/img/profile/1.jpg")).content) == client_module.IMAGE_MAX_BYTES


async def test_image_oversize_is_an_error_and_not_fully_read(api, script):
    total = 64 * 1024 * 1024
    sent = 0

    async def endless(request):
        nonlocal sent
        resp = web.StreamResponse(headers={"Content-Type": "image/jpeg"})
        await resp.prepare(request)
        try:
            while sent < total:
                await resp.write(b"x" * 65536)
                sent += 65536
        except (ConnectionResetError, ConnectionError):
            pass
        return resp

    script.respond = endless
    with pytest.raises(TellyboxError, match="too large") as err:
        await api.image("/img/profile/1.jpg")
    assert TOKEN not in str(err.value)
    assert sent < total


async def test_image_timeout_is_a_connection_error(script, session):
    async def slow(request):
        await asyncio.sleep(1)
        return web.Response(body=b"x")

    script.respond = slow
    c = TellyboxClient(script.url, TOKEN, session, timeout=0.05)  # type: ignore[attr-defined]
    with pytest.raises(TellyboxConnectionError):
        await c.image("/img/profile/1.jpg")


async def test_image_connection_refused(session):
    c = TellyboxClient("http://127.0.0.1:1", TOKEN, session)
    with pytest.raises(TellyboxConnectionError) as err:
        await c.image("/img/profile/1.jpg")
    assert TOKEN not in str(err.value) and "127.0.0.1" not in str(err.value)
