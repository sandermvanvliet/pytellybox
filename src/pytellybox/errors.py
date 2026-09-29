"""Errors raised by the Tellybox client. Every error is a `TellyboxError`."""

from __future__ import annotations


class TellyboxError(Exception):
    """Base class for every client error."""


class TellyboxConnectionError(TellyboxError):
    """Tellybox can't be reached: connection refused, timeout, or an event stream that ended."""


class TellyboxAuthError(TellyboxError):
    """401: the token is missing, unknown or revoked. Home Assistant starts a reauth flow."""


class TellyboxForbiddenError(TellyboxError):
    """403: the token lacks the scope, e.g. an override with a read-only token."""


class TellyboxNotFoundError(TellyboxError):
    """404: no such episode or show (or it isn't visible to kids)."""


class TellyboxRequestError(TellyboxError):
    """400/422: Tellybox refused the request (bad minutes, unknown profile ids...). `str()` is its detail."""


class TellyboxTimeUpError(TellyboxError):
    """409 on play: someone in the group is out of time (PR-4). Playing is refused, never forced."""


class TellyboxUnavailableError(TellyboxError):
    """503: Tellybox is up, but its cast service or the TV isn't; nothing was applied."""
