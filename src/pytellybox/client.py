"""Async client for a Tellybox server: the admin API (token) and the kid API (browse and play)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import aiohttp

from pytellybox.errors import (
    TellyboxAuthError,
    TellyboxConnectionError,
    TellyboxError,
    TellyboxForbiddenError,
    TellyboxNotFoundError,
    TellyboxRequestError,
    TellyboxTimeUpError,
    TellyboxUnavailableError,
)
from pytellybox.models import AdminState, Home, Info, KidProfile, KidState, Show

DEFAULT_TIMEOUT_S = 10.0
EVENTS_READ_TIMEOUT_S = 45.0  # Tellybox sends a keepalive every 15 s
EXTRA_MINUTES_MAX = 240


class TellyboxClient:
    """One Tellybox server.

    `base_url` is the server's root, e.g. `https://tellybox.example` or `http://192.0.2.10:8080`; a trailing
    slash is ignored. `token` is an API token (`tbx_...`) created on Tellybox's Integrations page; it may be
    None for `info()` and the kid API only. The caller owns `session` (Home Assistant passes its shared one);
    the client never closes it. The token is sent only as `Authorization: Bearer` to `/api/admin/*` and is
    never logged or put in an exception message.

    Error mapping, for every call: connection problems and timeouts raise TellyboxConnectionError;
    401 TellyboxAuthError; 403 TellyboxForbiddenError; 404 TellyboxNotFoundError; 400/422
    TellyboxRequestError (with Tellybox's `detail`); 409 on play TellyboxTimeUpError; 503
    TellyboxUnavailableError; any other non-2xx TellyboxError.
    """

    def __init__(
        self, base_url: str, token: str | None, session: aiohttp.ClientSession, *, timeout: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._token = token
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    def __repr__(self) -> str:
        return f"TellyboxClient({self._base_url!r})"

    @property
    def base_url(self) -> str:
        """The normalised base URL, without a trailing slash."""
        return self._base_url

    def url(self, path: str) -> str:
        """Absolute URL for a server path such as `/img/episode/4.jpg` (images need no auth)."""
        return f"{self._base_url}/{path.lstrip('/')}"

    # ----------------------------------------------------------------------- plumbing

    def _headers(self, path: str) -> dict[str, str]:
        if self._token and path.startswith("/api/admin/"):
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _request(
        self, method: str, path: str, *, json_body: Any = None, params: dict[str, str] | None = None,
        conflict_is_time_up: bool = False,
    ) -> Any:
        """One JSON request; returns the decoded body (None when empty) or raises a TellyboxError."""
        try:
            async with self._session.request(
                method, self.url(path), headers=self._headers(path), json=json_body, params=params,
                timeout=self._timeout,
            ) as resp:
                if resp.status >= 400:
                    raise await _error_for(resp, conflict_is_time_up)
                raw = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TellyboxConnectionError(f"Cannot reach Tellybox: {type(err).__name__}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise TellyboxError("Tellybox sent a response that is not JSON") from None

    # ----------------------------------------------------------------------- admin API (docs/admin-api.md)

    async def info(self) -> Info:
        """`GET /api/info`, no token needed."""
        return Info.from_dict(await self._request("GET", "/api/info"))

    async def state(self) -> AdminState:
        """`GET /api/admin/state` (read scope)."""
        return AdminState.from_dict(await self._request("GET", "/api/admin/state"))

    async def events(self) -> AsyncIterator[AdminState]:
        """`GET /api/admin/events` (read scope): yields the current state at once, then one per change.

        Keepalive comments are skipped. The read timeout is EVENTS_READ_TIMEOUT_S. When the stream ends or
        breaks, the iterator raises TellyboxConnectionError; it never reconnects on its own (the caller
        decides the backoff). A 401 on connect raises TellyboxAuthError.
        """
        async for payload in self._stream("/api/admin/events"):
            yield _parse_event(payload, AdminState.from_dict)

    async def _stream(self, path: str) -> AsyncIterator[str]:
        """The `data:` payloads of one SSE stream; always ends by raising TellyboxConnectionError."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self._timeout.total, sock_read=EVENTS_READ_TIMEOUT_S)
        headers = {**self._headers(path), "Accept": "text/event-stream"}
        try:
            async with self._session.get(self.url(path), headers=headers, timeout=timeout) as resp:
                if resp.status >= 400:
                    raise await _error_for(resp, False)
                data: list[str] = []
                async for raw in resp.content:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data:
                            payload, data = "\n".join(data), []
                            yield payload
                    elif line.startswith(":"):
                        continue
                    elif line.startswith("data:"):
                        value = line[5:]
                        data.append(value[1:] if value.startswith(" ") else value)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TellyboxConnectionError(f"Event stream broke: {type(err).__name__}") from None
        raise TellyboxConnectionError("Event stream ended")

    async def _override(self, method: str, action: str, **kwargs: Any) -> AdminState:
        return AdminState.from_dict(await self._request(method, f"/api/admin/overrides/{action}", **kwargs))

    async def add_time(self, minutes: int, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/extra` (control). `minutes` 1..240; None = every kid."""
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= EXTRA_MINUTES_MAX:
            raise ValueError(f"minutes must be an integer from 1 to {EXTRA_MINUTES_MAX}")
        return await self._override("POST", "extra", json_body=_body(profile_ids, minutes=minutes))

    async def set_unlimited(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/unlimited` (control): unlimited today."""
        return await self._override("POST", "unlimited", json_body=_body(profile_ids))

    async def block(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/block` (control): blocked today, immediately."""
        return await self._override("POST", "block", json_body=_body(profile_ids))

    async def stop_now(self) -> AdminState:
        """`POST /api/admin/overrides/stop` (control)."""
        return await self._override("POST", "stop", json_body={})

    async def clear_today(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`DELETE /api/admin/overrides/today?profile_ids=1,3` (control): clears unlimited and block."""
        params = {"profile_ids": _csv(profile_ids)} if profile_ids is not None else None
        return await self._override("DELETE", "today", params=params)

    # ----------------------------------------------------------------------- kid API (docs/kid-api.md), no token

    async def kid_profiles(self) -> list[KidProfile]:
        """`GET /api/kid/profiles`."""
        return [KidProfile.from_dict(p) for p in await self._request("GET", "/api/kid/profiles")]

    async def home(self, profile_ids: Sequence[int] | None = None) -> Home:
        """`GET /api/kid/home?profiles=1,3`."""
        return Home.from_dict(await self._request("GET", "/api/kid/home", params=_profiles_param(profile_ids)))

    async def show(self, show_id: int, profile_ids: Sequence[int] | None = None) -> Show:
        """`GET /api/kid/shows/{id}?profiles=1,3`."""
        data = await self._request("GET", f"/api/kid/shows/{int(show_id)}", params=_profiles_param(profile_ids))
        return Show.from_dict(data)

    async def play(self, episode_id: int, profile_ids: Sequence[int]) -> None:
        """`POST /api/kid/play`. 409 raises TellyboxTimeUpError: Tellybox's timer always decides."""
        await self._request(
            "POST", "/api/kid/play", json_body={"episode_id": episode_id, "profile_ids": list(profile_ids)},
            conflict_is_time_up=True,
        )

    async def kid_state(self) -> KidState:
        """`GET /api/kid/state`: what the kid screen shows live (the sun, now playing, the TV, the sessions)."""
        return KidState.from_dict(await self._request("GET", "/api/kid/state"))

    async def kid_events(self) -> AsyncIterator[KidState]:
        """`GET /api/kid/events` (no token): yields the current kid state at once, then one per change.

        Same behaviour as `events()`: keepalives are skipped and the iterator ends by raising
        TellyboxConnectionError.
        """
        async for payload in self._stream("/api/kid/events"):
            yield _parse_event(payload, KidState.from_dict)

    async def pause(self) -> None:
        """`POST /api/kid/pause`."""
        await self._request("POST", "/api/kid/pause", json_body={})

    async def resume(self) -> None:
        """`POST /api/kid/resume`."""
        await self._request("POST", "/api/kid/resume", json_body={})


def _csv(ids: Sequence[int]) -> str:
    return ",".join(str(int(i)) for i in ids)


def _body(profile_ids: Sequence[int] | None, **fields: Any) -> dict[str, Any]:
    body = dict(fields)
    if profile_ids is not None:
        body["profile_ids"] = [int(i) for i in profile_ids]
    return body


def _profiles_param(profile_ids: Sequence[int] | None) -> dict[str, str] | None:
    return {"profiles": _csv(profile_ids)} if profile_ids is not None else None


def _parse_event[T](payload: str, parse: Callable[[dict[str, Any]], T]) -> T:
    try:
        return parse(json.loads(payload))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise TellyboxError("Tellybox sent an event that is not a state") from None


async def _error_for(resp: aiohttp.ClientResponse, conflict_is_time_up: bool) -> TellyboxError:
    """Map a non-2xx response to the matching error. Only Tellybox's `detail` ends up in the message."""
    status = resp.status
    detail = ""
    try:
        body = await resp.json(content_type=None)
    except (ValueError, aiohttp.ClientError):
        body = None
    if isinstance(body, dict) and body.get("detail") is not None:
        detail = str(body["detail"])
    text = detail or f"HTTP {status}"
    if status == 401:
        return TellyboxAuthError(text)
    if status == 403:
        return TellyboxForbiddenError(text)
    if status == 404:
        return TellyboxNotFoundError(text)
    if status in (400, 422):
        return TellyboxRequestError(text)
    if status == 409 and conflict_is_time_up:
        return TellyboxTimeUpError(text)
    if status == 503:
        return TellyboxUnavailableError(text)
    return TellyboxError(text)
