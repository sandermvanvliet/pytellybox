"""Async client for a Tellybox server: the admin API (token) and the kid API (browse and play).

Contract only: subagent A implements the bodies (see docs/plan.md in ha-tellybox). Signatures and
behaviour described in the docstrings are fixed; the Home Assistant integration is written against them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import aiohttp

from pytellybox.models import AdminState, Home, Info, KidProfile, Show

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
        raise NotImplementedError

    @property
    def base_url(self) -> str:
        """The normalised base URL, without a trailing slash."""
        raise NotImplementedError

    def url(self, path: str) -> str:
        """Absolute URL for a server path such as `/img/episode/4.jpg` (images need no auth)."""
        raise NotImplementedError

    # ----------------------------------------------------------------------- admin API (docs/admin-api.md)

    async def info(self) -> Info:
        """`GET /api/info`, no token needed."""
        raise NotImplementedError

    async def state(self) -> AdminState:
        """`GET /api/admin/state` (read scope)."""
        raise NotImplementedError

    def events(self) -> AsyncIterator[AdminState]:
        """`GET /api/admin/events` (read scope): yields the current state at once, then one per change.

        Keepalive comments are skipped. The read timeout is EVENTS_READ_TIMEOUT_S. When the stream ends or
        breaks, the iterator raises TellyboxConnectionError; it never reconnects on its own (the caller
        decides the backoff). A 401 on connect raises TellyboxAuthError.
        """
        raise NotImplementedError

    async def add_time(self, minutes: int, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/extra` (control). `minutes` 1..240; None = every kid."""
        raise NotImplementedError

    async def set_unlimited(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/unlimited` (control): unlimited today."""
        raise NotImplementedError

    async def block(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`POST /api/admin/overrides/block` (control): blocked today, immediately."""
        raise NotImplementedError

    async def stop_now(self) -> AdminState:
        """`POST /api/admin/overrides/stop` (control)."""
        raise NotImplementedError

    async def clear_today(self, profile_ids: Sequence[int] | None = None) -> AdminState:
        """`DELETE /api/admin/overrides/today?profile_ids=1,3` (control): clears unlimited and block."""
        raise NotImplementedError

    # ----------------------------------------------------------------------- kid API (docs/kid-api.md), no token

    async def kid_profiles(self) -> list[KidProfile]:
        """`GET /api/kid/profiles`."""
        raise NotImplementedError

    async def home(self, profile_ids: Sequence[int] | None = None) -> Home:
        """`GET /api/kid/home?profiles=1,3`."""
        raise NotImplementedError

    async def show(self, show_id: int, profile_ids: Sequence[int] | None = None) -> Show:
        """`GET /api/kid/shows/{id}?profiles=1,3`."""
        raise NotImplementedError

    async def play(self, episode_id: int, profile_ids: Sequence[int]) -> None:
        """`POST /api/kid/play`. 409 raises TellyboxTimeUpError: Tellybox's timer always decides."""
        raise NotImplementedError

    async def pause(self) -> None:
        """`POST /api/kid/pause`."""
        raise NotImplementedError

    async def resume(self) -> None:
        """`POST /api/kid/resume`."""
        raise NotImplementedError
