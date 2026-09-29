"""Async client for Tellybox (https://github.com/sandermvanvliet/Tellybox)."""

from pytellybox.client import EXTRA_MINUTES_MAX, TellyboxClient
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
from pytellybox.models import (
    LAST_FIVE_S,
    TV,
    AdminState,
    Day,
    Disk,
    Group,
    Home,
    Info,
    Jobs,
    KidProfile,
    NowPlaying,
    Profile,
    Show,
    ShowRef,
    Tile,
)

__all__ = [
    "EXTRA_MINUTES_MAX", "LAST_FIVE_S", "TV", "AdminState", "Day", "Disk", "Group", "Home", "Info", "Jobs",
    "KidProfile", "NowPlaying", "Profile", "Show", "ShowRef", "TellyboxAuthError", "TellyboxClient",
    "TellyboxConnectionError", "TellyboxError", "TellyboxForbiddenError", "TellyboxNotFoundError",
    "TellyboxRequestError", "TellyboxTimeUpError", "TellyboxUnavailableError", "Tile",
]
