"""A mock Tellybox server for developing and testing integrations without a real Tellybox.

`python -m pytellybox.mock --port 8099 --token tbx_dev [--read-token tbx_ro]` serves:
- `/api/info`, `/api/admin/state`, `/api/admin/events` (SSE with keepalive), the override routes, with the
  same auth rules as Tellybox (401 / 403, a read-only token via `read_tokens`);
- `/api/kid/profiles`, `/home`, `/shows/{id}`, `/state`, `/events` (SSE), `/play` (409 when a watcher can't start), `/pause`,
  `/resume`;
- `/img/...` placeholder images (`/img/profile/{id}.jpg` only for a profile with a `picture`, else 404) and
  `/static/avatars/{key}.svg`.
- `/api/admin/history` (`history` capability; `MockTellybox(history=False)` plays an older server: 404, no capability);
- per profile `picture`, `watch_in_app` and `ui_mode` (an 'old server' state simply omits them).
Overrides change the scripted state the way Tellybox would (extra time, unlimited, block, clear, stop) and
push a new event. Tests and scripts drive it through `MockTellybox`: `set_state(dict)`, `push()`,
`calls` (recorded requests), and `app` (an aiohttp `web.Application`).
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from datetime import date, timedelta
from collections.abc import Awaitable, Callable, Iterable
from importlib import resources
from typing import Any

from aiohttp import web

_LAST_FIVE_S = 300
_PLACEHOLDER_IMAGE = (  # a 1x1 GIF; the mock has no image library
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x80\x80\x80\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

_PLACEHOLDER_JPEG = bytes.fromhex(  # a valid 1x1 JPEG
    "ffd8ffe000104a46494600010100000100010000ffdb004300100b0c0e0c0a100e0d0e1211101318281a181616183123251d"
    "283a333d3c3933383740485c4e404457453738506d51575f626768673e4d71797064785c656763ffc0000b08000100010101"
    "1100ffc40014000100000000000000000000000000000001ffc40014100100000000000000000000000000000000ffda0008"
    "010100003f001fffd9"
)
_PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
    b'<circle cx="32" cy="32" r="30" fill="#ccc"/></svg>'
)

_EPISODES = {
    4: {"show_id": 2, "title": "Alongside", "duration_s": 660},
    5: {"show_id": 2, "title": "Lost Ball", "duration_s": 600},
    6: {"show_id": 3, "title": "Big Splash", "duration_s": 480},
}
_SHOWS = {2: "Harbour Pups", 3: "Bubble Bay"}

# Seeded history: day offsets back from today (0 = today); a missing offset counts as zeros.
_HISTORY_DAYS: dict[int, dict[str, dict[str, Any]]] = {
    1: {"0": {"used_s": 1200, "extra_s": 0}, "1": {"used_s": 2710, "extra_s": 900},
        "2": {"used_s": 1800, "extra_s": 0, "unlimited": True}, "4": {"used_s": 600, "extra_s": 0}},
    2: {"0": {"used_s": 0, "extra_s": 0, "blocked": True}, "1": {"used_s": 3600, "extra_s": 0},
        "3": {"used_s": 900, "extra_s": 300}},
}
_HISTORY_LAST_WATCHED: dict[int, dict[str, Any] | None] = {
    1: {"episode_id": 4, "title": "Alongside", "show": "Harbour Pups", "started_at": "2026-09-29T07:10:00+00:00",
        "ended_at": None, "target": "tv"},
    2: None,
}

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def default_state() -> dict[str, Any]:
    """A copy of the packaged example state (Mila watching, Noah out of time)."""
    return json.loads(resources.files("pytellybox").joinpath("admin_state.json").read_text(encoding="utf-8"))


def _json_error(status: int, detail: str) -> web.Response:
    return web.json_response({"detail": detail}, status=status)


class MockTellybox:
    """A scripted Tellybox. `tokens` may control; `read_tokens` may only read (403 on an override)."""

    def __init__(
        self, state: dict[str, Any] | None = None, *, token: str = "tbx_mock", read_tokens: Iterable[str] = (),
        keepalive_s: float = 15.0, history: bool = True,
    ) -> None:
        self.tokens: set[str] = {token}
        self.read_tokens: set[str] = set(read_tokens)
        self.keepalive_s = keepalive_s
        self.history_enabled = history  # False behaves like an older Tellybox: no capability, 404
        self.history_days: dict[int, dict[str, dict[str, Any]]] = copy.deepcopy(_HISTORY_DAYS)  # profile -> date -> row
        self.history_last_watched: dict[int, dict[str, Any] | None] = copy.deepcopy(_HISTORY_LAST_WATCHED)
        self.calls: list[dict[str, Any]] = []
        self._state: dict[str, Any] = copy.deepcopy(state) if state is not None else default_state()
        self._subscribers: set[asyncio.Queue[str | None]] = set()
        self._kid_subscribers: set[asyncio.Queue[str | None]] = set()
        self._runner: web.AppRunner | None = None
        self.app = web.Application(middlewares=[self._record, self._auth])
        self.app.on_shutdown.append(self._close_streams)
        self.app.add_routes([
            web.get("/api/info", self._info),
            web.get("/api/admin/state", self._get_state),
            web.get("/api/admin/events", self._events),
            web.get("/api/admin/history", self._history),
            web.post("/api/admin/overrides/extra", self._extra),
            web.post("/api/admin/overrides/unlimited", self._unlimited),
            web.post("/api/admin/overrides/block", self._block),
            web.post("/api/admin/overrides/stop", self._stop),
            web.delete("/api/admin/overrides/today", self._clear),
            web.get("/api/kid/profiles", self._kid_profiles),
            web.get("/api/kid/home", self._kid_home),
            web.get("/api/kid/shows/{show_id}", self._kid_show),
            web.get("/api/kid/state", self._kid_state),
            web.get("/api/kid/events", self._kid_events),
            web.post("/api/kid/play", self._kid_play),
            web.post("/api/kid/pause", self._kid_pause),
            web.post("/api/kid/resume", self._kid_resume),
            web.get("/img/{kind}/{item}.jpg", self._image),
            web.get("/static/avatars/{key}.svg", self._avatar),
        ])

    # ------------------------------------------------------------------ driving the mock

    @property
    def state(self) -> dict[str, Any]:
        """The current AdminState payload (mutable; call `push()` after changing it)."""
        return self._state

    def set_state(self, state: dict[str, Any]) -> None:
        """Replace the state and push it to the event streams."""
        self._state = copy.deepcopy(state)
        self.push()

    def push(self) -> None:
        """Send the current state to every open event stream."""
        payload = json.dumps(self._state)
        for queue in self._subscribers:
            queue.put_nowait(payload)
        kid_payload = json.dumps(self._kid_state_dict())
        for queue in self._kid_subscribers:
            queue.put_nowait(kid_payload)

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        """Listen on host:port (0 = any free port) and return the base URL."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        actual = self._runner.addresses[0][1]
        return f"http://{host}:{actual}"

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------ middleware

    @web.middleware
    async def _record(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        entry: dict[str, Any] = {"method": request.method, "path": request.path, "query": dict(request.query),
                                 "json": None}
        entry["json"] = await self._json(request)
        self.calls.append(entry)
        return await handler(request)

    @web.middleware
    async def _auth(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        if request.path.startswith("/api/admin/"):
            header = request.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            if token not in self.tokens | self.read_tokens:
                resp = _json_error(401, "unauthorized")
                resp.headers["WWW-Authenticate"] = "Bearer"
                return resp
            if request.method != "GET" and token not in self.tokens:
                return _json_error(403, "forbidden")
        return await handler(request)

    # ------------------------------------------------------------------ admin API

    async def _info(self, request: web.Request) -> web.Response:
        s = self._state
        return web.json_response({"instance_id": s["instance_id"], "version": s["version"], "api": 1,
                                  "capabilities": self._capabilities()})

    def _capabilities(self) -> list[str]:
        caps = ["state", "events", "overrides", "profiles", "inbox"]
        return [*caps, "history"] if self.history_enabled else caps

    async def _history(self, request: web.Request) -> web.Response:
        if not self.history_enabled:
            return _json_error(404, "not_found")
        raw_days = request.query.get("days", "7")
        try:
            days = int(raw_days)
        except ValueError:
            days = 0
        if not 1 <= days <= 21:
            return _json_error(422, "days must be an integer from 1 to 21")
        profiles = self._state["profiles"]
        raw_ids = request.query.get("profile_ids")
        if raw_ids:
            try:
                ids = [int(i) for i in raw_ids.split(",")]
            except ValueError:
                return _json_error(422, "bad profile_ids")
            if not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids):
                return _json_error(422, "profile_ids must be 1-20 distinct ids")
            if any(i not in [p["id"] for p in profiles] for i in ids):
                return _json_error(422, "unknown profile id")
            profiles = [p for p in profiles if p["id"] in ids]
        today = date.fromisoformat(self._state["day"]["date"])
        out = []
        for p in profiles:
            rows = self.history_days.get(p["id"], {})
            entries = []
            for back in range(days):
                row = rows.get(str(back), {})
                entries.append({
                    "date": (today - timedelta(days=back)).isoformat(), "used_s": row.get("used_s", 0),
                    "extra_s": row.get("extra_s", 0), "unlimited": row.get("unlimited", False),
                    "blocked": row.get("blocked", False)})
            out.append({"id": p["id"], "name": p["name"], "days": entries,
                        "last_watched": self.history_last_watched.get(p["id"])})
        return web.json_response({"today": today.isoformat(), "days": days, "profiles": out})

    async def _get_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._state)

    async def _events(self, request: web.Request) -> web.StreamResponse:
        return await self._stream(request, self._subscribers, lambda: self._state)

    async def _kid_events(self, request: web.Request) -> web.StreamResponse:
        return await self._stream(request, self._kid_subscribers, self._kid_state_dict)

    async def _stream(self, request: web.Request, subscribers: set[asyncio.Queue[str | None]],
                      current: Callable[[], dict[str, Any]]) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(request)
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        queue.put_nowait(json.dumps(current()))
        subscribers.add(queue)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), self.keepalive_s)
                except TimeoutError:
                    await resp.write(b": keepalive\n\n")
                    continue
                if payload is None:
                    break
                await resp.write(f"data: {payload}\n\n".encode())
        except ConnectionResetError:
            pass
        finally:
            subscribers.discard(queue)
        return resp

    async def _close_streams(self, app: web.Application) -> None:
        for queue in [*self._subscribers, *self._kid_subscribers]:
            queue.put_nowait(None)

    async def _ids(self, request: web.Request, body: Any) -> list[int] | web.Response:
        """The profiles an override applies to, or a 422 response."""
        if not isinstance(body, dict):
            return _json_error(422, "body must be a JSON object")
        ids = body.get("profile_ids")
        everyone = [p["id"] for p in self._state["profiles"]]
        if ids is None:
            return everyone
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids)
                or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
            return _json_error(422, "profile_ids must be 1-20 distinct ids")
        if any(i not in everyone for i in ids):
            return _json_error(422, "unknown profile id")
        return ids

    @staticmethod
    async def _json(request: web.Request) -> Any:
        """The JSON body; None when absent or malformed (`read()` caches, so it can run twice)."""
        raw = await request.read()
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    async def _body(self, request: web.Request) -> Any:
        """The JSON body of an override or kid POST; an empty body counts as `{}`, junk as None."""
        raw = await request.read()
        return {} if not raw else await self._json(request)

    def _profiles(self, ids: list[int]) -> list[dict[str, Any]]:
        return [p for p in self._state["profiles"] if p["id"] in ids]

    def _refresh(self, watchers: list[int] | None = None) -> None:
        """Recompute each profile and the group the way the timer would."""
        state = self._state
        for p in state["profiles"]:
            if p["blocked"]:
                p["remaining_s"], p["can_start"], p["reason"] = 0, False, "blocked"
            elif p["unlimited"]:
                p["remaining_s"], p["can_start"], p["reason"] = None, True, None
            else:
                if p["allowance_s"] is None:  # an unlimited allowance (A-23)
                    p["remaining_s"], p["can_start"], p["reason"] = None, True, None
                else:
                    left = max(p["allowance_s"] + (p["extra_s"] or 0) - (p["used_s"] or 0), 0)
                    p["remaining_s"], p["can_start"] = left, left > 0
                    p["reason"] = None if left > 0 else "allowance"
            p["last_five"] = p["remaining_s"] is not None and 0 < p["remaining_s"] <= _LAST_FIVE_S
        if watchers is None:
            watchers = (state.get("now_playing") or {}).get("profile_ids", [])
        group = [p for p in state["profiles"] if p["id"] in watchers]
        if not group:
            return
        finite = [p["remaining_s"] for p in group if p["remaining_s"] is not None]
        remaining = min(finite) if finite else None
        blocked = any(p["blocked"] for p in group)
        out = any(p["can_start"] is False for p in group)
        g = state["group"]
        g["remaining_s"] = remaining
        g["time_up"] = out
        g["last_five"] = remaining is not None and 0 < remaining <= _LAST_FIVE_S
        g["reason"] = "blocked" if blocked else ("allowance" if out else None)
        g["action"] = "stop_now" if blocked else ("finish_then_stop" if out else "continue")

    def _stop_playback(self) -> None:
        self._state["now_playing"] = None
        self._state["sessions"] = []
        for p in self._state["profiles"]:
            p["watching"] = False

    async def _apply(self, request: web.Request, change: Callable[[list[dict[str, Any]], Any], None],
                     *, needs_ids: bool = True, body: Any = None) -> web.Response:
        if body is None:
            body = await self._body(request)
        ids: list[int] | web.Response = await self._ids(request, body) if needs_ids else []
        if isinstance(ids, web.Response):
            return ids
        watchers = list((self._state.get("now_playing") or {}).get("profile_ids", []))
        change(self._profiles(ids), body)
        self._refresh(watchers)
        self.push()
        return web.json_response(self._state)

    async def _extra(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        minutes = body.get("minutes") if isinstance(body, dict) else None
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 240:
            return _json_error(422, "minutes must be an integer from 1 to 240")

        def change(profiles: list[dict[str, Any]], _: Any) -> None:
            for p in profiles:
                p["extra_s"] = (p["extra_s"] or 0) + minutes * 60

        return await self._apply(request, change)

    async def _unlimited(self, request: web.Request) -> web.Response:
        def change(profiles: list[dict[str, Any]], _: Any) -> None:
            for p in profiles:
                p["unlimited"] = True

        return await self._apply(request, change)

    async def _block(self, request: web.Request) -> web.Response:
        def change(profiles: list[dict[str, Any]], _: Any) -> None:
            blocked = {p["id"] for p in profiles}
            for p in profiles:
                p["blocked"] = True
            playing = self._state.get("now_playing")
            if playing and blocked & set(playing["profile_ids"]):
                self._stop_playback()

        return await self._apply(request, change)

    async def _stop(self, request: web.Request) -> web.Response:
        return await self._apply(request, lambda _p, _b: self._stop_playback(), needs_ids=False)

    async def _clear(self, request: web.Request) -> web.Response:
        raw = request.query.get("profile_ids")
        body: dict[str, Any] = {}
        if raw:
            try:
                body["profile_ids"] = [int(i) for i in raw.split(",")]
            except ValueError:
                return _json_error(422, "bad profile_ids")

        def change(profiles: list[dict[str, Any]], _: Any) -> None:
            for p in profiles:
                p["unlimited"] = p["blocked"] = False

        return await self._apply(request, change, body=body)

    # ------------------------------------------------------------------ kid API

    def _group(self, request: web.Request) -> list[int] | web.Response:
        raw = request.query.get("profiles")
        everyone = [p["id"] for p in self._state["profiles"]]
        if raw is None:
            return everyone[:1]
        try:
            ids = [int(i) for i in raw.split(",")]
        except ValueError:
            return _json_error(400, "bad_profiles")
        if not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids) or any(i not in everyone for i in ids):
            return _json_error(400, "bad_profiles")
        return ids

    def _kid_state_dict(self) -> dict[str, Any]:
        s = self._state
        playing = s.get("now_playing")
        profiles = {}
        for p in s["profiles"]:
            allowance = (p["allowance_s"] or 0) + (p["extra_s"] or 0)
            fraction = None if p["remaining_s"] is None else round(p["remaining_s"] / allowance, 3) if allowance else 0
            profiles[str(p["id"])] = {"fraction_left": fraction, "last_five": p["last_five"],
                                      "unlimited": p["unlimited"], "time_up": p["can_start"] is False}
        return {
            "tv": "ok" if s["tv"]["reachable"] else "unreachable", "device_name": s["tv"]["device"],
            "now_playing": None if not playing else {
                "episode_id": playing["episode_id"], "show_id": playing["show_id"],
                "thumb": f"/img/episode/{playing['episode_id']}.jpg", "title": playing["title"],
                "state": playing["state"]},
            "watching": list(playing["profile_ids"]) if playing else [],
            "sky": {"fraction_left": None, "last_five": s["group"]["last_five"], "unlimited": False},
            "time_up": s["group"]["time_up"], "profiles": profiles, "day": s["day"]["date"],
            "sessions": [
                {k: x.get(k) for k in ("key", "target", "label", "device_id", "episode_id", "show_id", "profile_ids",
                                       "state")}
                for x in s.get("sessions", [])],
        }

    @staticmethod
    def _tile(episode_id: int) -> dict[str, Any]:
        e = _EPISODES[episode_id]
        return {"episode_id": episode_id, "show_id": e["show_id"], "thumb": f"/img/episode/{episode_id}.jpg",
                "title": e["title"], "progress": None, "finished": False}

    async def _kid_profiles(self, request: web.Request) -> web.Response:
        return web.json_response([
            {"profile_id": p["id"], "name": p["name"], "picture": p.get("picture"),
             "avatar": p["avatar"], "ui_mode": p.get("ui_mode", "icons"),
             "watch_in_app": p.get("watch_in_app", False), "time_up": p["can_start"] is False, "fraction_left": None, "last_five": p["last_five"],
             "unlimited": p["unlimited"]}
            for p in self._state["profiles"]])

    async def _kid_home(self, request: web.Request) -> web.Response:
        group = self._group(request)
        if isinstance(group, web.Response):
            return group
        return web.json_response({
            "continue": [{**self._tile(5), "kind": "next"}],
            "shows": [{"show_id": i, "artwork": f"/img/show/{i}.jpg", "title": t} for i, t in _SHOWS.items()]})

    async def _kid_show(self, request: web.Request) -> web.Response:
        group = self._group(request)
        if isinstance(group, web.Response):
            return group
        try:
            show_id = int(request.match_info["show_id"])
        except ValueError:
            return _json_error(404, "not_found")
        if show_id not in _SHOWS:
            return _json_error(404, "not_found")
        return web.json_response({
            "show_id": show_id, "artwork": f"/img/show/{show_id}.jpg", "title": _SHOWS[show_id],
            "episodes": [self._tile(i) for i, e in _EPISODES.items() if e["show_id"] == show_id]})

    async def _kid_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._kid_state_dict())

    async def _kid_play(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        if not isinstance(body, dict):
            return _json_error(400, "bad_request")
        ids, episode_id = body.get("profile_ids"), body.get("episode_id")
        everyone = [p["id"] for p in self._state["profiles"]]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 20 or len(set(ids)) != len(ids)
                or any(i not in everyone for i in ids)):
            return _json_error(400, "bad_profiles")
        if episode_id not in _EPISODES:
            return _json_error(404, "not_found")
        if not self._state["tv"]["reachable"]:
            return web.json_response(self._kid_state_dict(), status=503)
        if any(p["can_start"] is False for p in self._profiles(ids)):
            return web.json_response(self._kid_state_dict(), status=409)
        e = _EPISODES[episode_id]
        self._state["now_playing"] = {
            "episode_id": episode_id, "show_id": e["show_id"], "title": e["title"], "show": _SHOWS[e["show_id"]],
            "state": "playing", "position_s": 0, "duration_s": e["duration_s"], "profile_ids": ids}
        self._state["sessions"] = [{
            "key": "tv", "target": "tv", "label": self._state["tv"]["device"], "device_id": None,
            "episode_id": episode_id, "show_id": e["show_id"], "title": e["title"], "state": "playing",
            "position_s": 0, "duration_s": e["duration_s"], "profile_ids": ids}]
        for p in self._state["profiles"]:
            p["watching"] = p["id"] in ids
        self._refresh(ids)
        self.push()
        return web.json_response(self._kid_state_dict())

    async def _set_playback(self, state: str) -> web.Response:
        if not self._state["tv"]["reachable"]:
            return web.json_response(self._kid_state_dict(), status=503)
        if self._state.get("now_playing"):
            self._state["now_playing"]["state"] = state
            self.push()
        return web.json_response(self._kid_state_dict())

    async def _kid_pause(self, request: web.Request) -> web.Response:
        return await self._set_playback("paused")

    async def _kid_resume(self, request: web.Request) -> web.Response:
        return await self._set_playback("playing")

    async def _image(self, request: web.Request) -> web.Response:
        if request.match_info["kind"] == "profile":
            try:
                profile_id = int(request.match_info["item"])
            except ValueError:
                return _json_error(404, "not_found")
            if not any(p["id"] == profile_id and p.get("picture") for p in self._state["profiles"]):
                return _json_error(404, "not_found")
            return web.Response(body=_PLACEHOLDER_JPEG, content_type="image/jpeg")
        return web.Response(body=_PLACEHOLDER_IMAGE, content_type="image/gif")

    async def _avatar(self, request: web.Request) -> web.Response:
        return web.Response(body=_PLACEHOLDER_SVG, content_type="image/svg+xml")


async def _serve(host: str, port: int, mock: MockTellybox) -> None:
    url = await mock.start(host, port)
    print(f"Mock Tellybox listening on {url}")  # noqa: T201
    try:
        await asyncio.Event().wait()
    finally:
        await mock.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pytellybox.mock", description="Run a mock Tellybox server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--token", default="tbx_dev", help="token with the control scope")
    parser.add_argument("--read-token", action="append", default=[], help="token with the read scope only")
    parser.add_argument("--keepalive", type=float, default=15.0, help="seconds between SSE keepalives")
    args = parser.parse_args(argv)
    mock = MockTellybox(token=args.token, read_tokens=args.read_token, keepalive_s=args.keepalive)
    try:
        asyncio.run(_serve(args.host, args.port, mock))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
