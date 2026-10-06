"""Async client for Tellybox (https://github.com/sandermvanvliet/Tellybox)."""

from pytellybox.client import EXTRA_MINUTES_MAX, HISTORY_DAYS_MAX, TellyboxClient
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
    Image,
    Inbox,
    Info,
    Jobs,
    KidNowPlaying,
    KidProfile,
    KidProfileState,
    KidSession,
    KidSky,
    KidState,
    LastWatched,
    NowPlaying,
    Profile,
    ProfileUsage,
    Show,
    ShowRef,
    ServerEvent,
    Session,
    Tile,
    UsageDay,
    UsageHistory,
)

__all__ = [
    "EXTRA_MINUTES_MAX", "HISTORY_DAYS_MAX", "LAST_FIVE_S", "TV", "AdminState", "Day", "Disk", "Group", "Home", "Image", "Inbox", "Info", "Jobs",
    "KidNowPlaying", "KidProfile", "KidProfileState", "KidSession", "KidSky", "KidState", "LastWatched", "NowPlaying",
    "Profile", "ProfileUsage",
    "ServerEvent", "Session", "Show", "ShowRef", "TellyboxAuthError", "TellyboxClient", "TellyboxConnectionError", "TellyboxError",
    "TellyboxForbiddenError", "TellyboxNotFoundError", "TellyboxRequestError", "TellyboxTimeUpError",
    "TellyboxUnavailableError", "Tile", "UsageDay", "UsageHistory",
]
