"""Typed views of the Tellybox API payloads.

Admin types follow Tellybox's `docs/admin-api.md` (API version 1); kid types follow `docs/kid-api.md`.
Every `from_dict` tolerates unknown extra keys (newer servers) and keeps the original payload in `raw`
where it matters, so callers can reach fields this version doesn't model yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

LAST_FIVE_S = 300


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


# --------------------------------------------------------------------------- admin API


@dataclass(frozen=True)
class Info:
    """`GET /api/info` (HA-6), no auth needed."""

    instance_id: str
    version: str
    api: int
    capabilities: tuple[str, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Info:
        return cls(d["instance_id"], d["version"], int(d["api"]), tuple(d.get("capabilities", ())))


@dataclass(frozen=True)
class Day:
    date: date | None  # the timer day (WT-1); None before the first cast state
    resets_at: datetime | None  # the next daily reset

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Day:
        return cls(_date(d.get("date")), _dt(d.get("resets_at")))


@dataclass(frozen=True)
class TV:
    connection: str  # the cast state's connection, or "unreachable" when the cast service is down
    reachable: bool
    device: str | None  # the Chromecast's name

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TV:
        return cls(d["connection"], bool(d["reachable"]), d.get("device"))


@dataclass(frozen=True)
class NowPlaying:
    episode_id: int
    show_id: int
    title: str
    show: str | None
    state: str  # loading | playing | paused | buffering
    position_s: int | None
    duration_s: int | None
    profile_ids: tuple[int, ...]

    @property
    def thumb_path(self) -> str:
        """The episode thumbnail on the kid API (no auth): `/img/episode/{id}.jpg`."""
        return f"/img/episode/{self.episode_id}.jpg"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NowPlaying:
        return cls(
            int(d["episode_id"]), int(d["show_id"]), d.get("title") or "", d.get("show"), d["state"],
            d.get("position_s"), d.get("duration_s"), tuple(d.get("profile_ids") or ()),
        )


@dataclass(frozen=True)
class Group:
    """The current watchers, as the cast service's timer describes them."""

    remaining_s: int | None  # None = all unlimited (or unknown)
    time_up: bool
    last_five: bool
    action: str | None  # continue | finish_then_stop | stop_now
    reason: str | None  # allowance | session_max | blocked
    grace_ends_at: datetime | None
    session_started_at: datetime | None
    session_elapsed_s: int | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Group:
        return cls(
            d.get("remaining_s"), bool(d.get("time_up")), bool(d.get("last_five")), d.get("action"),
            d.get("reason"), _dt(d.get("grace_ends_at")), _dt(d.get("session_started_at")),
            d.get("session_elapsed_s"),
        )


@dataclass(frozen=True)
class Profile:
    """One kid. Timer fields are None on a cold start, before Tellybox has seen the cast state."""

    id: int
    name: str
    avatar: str | None
    allowance_s: int
    extra_s: int | None
    used_s: int | None
    remaining_s: int | None  # None = unlimited today (when `unlimited`) or unknown
    unlimited: bool
    blocked: bool
    mode: str  # ignore_pauses | wall_clock
    max_session_s: int | None
    session_elapsed_s: int | None
    can_start: bool | None
    reason: str | None
    watching: bool
    last_five: bool

    @property
    def time_up(self) -> bool:
        """This kid may not start a pick now (out of time, blocked or past the session max)."""
        return self.can_start is False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Profile:
        return cls(
            int(d["id"]), d["name"], d.get("avatar"), int(d["allowance_s"]), d.get("extra_s"), d.get("used_s"),
            d.get("remaining_s"), bool(d.get("unlimited")), bool(d.get("blocked")), d.get("mode", "ignore_pauses"),
            d.get("max_session_s"), d.get("session_elapsed_s"), d.get("can_start"), d.get("reason"),
            bool(d.get("watching")), bool(d.get("last_five")),
        )


@dataclass(frozen=True)
class Jobs:
    queued: int
    running: int
    failed: int
    held_ready: int  # downloads waiting for approval

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Jobs:
        return cls(int(d.get("queued", 0)), int(d.get("running", 0)), int(d.get("failed", 0)),
                   int(d.get("held_ready", 0)))


@dataclass(frozen=True)
class Disk:
    media_bytes: int
    free_bytes: int | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Disk:
        return cls(int(d.get("media_bytes", 0)), d.get("free_bytes"))


@dataclass(frozen=True)
class AdminState:
    """`GET /api/admin/state`, each `/api/admin/events` event and every override response (HA-2)."""

    instance_id: str
    version: str
    api: int
    day: Day
    tv: TV
    now_playing: NowPlaying | None
    group: Group
    profiles: tuple[Profile, ...]  # in the admin's order
    jobs: Jobs
    disk: Disk
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def profile(self, profile_id: int) -> Profile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AdminState:
        np = d.get("now_playing")
        return cls(
            d["instance_id"], d["version"], int(d.get("api", 1)), Day.from_dict(d.get("day") or {}),
            TV.from_dict(d["tv"]), NowPlaying.from_dict(np) if np else None, Group.from_dict(d.get("group") or {}),
            tuple(Profile.from_dict(p) for p in d.get("profiles", ())), Jobs.from_dict(d.get("jobs") or {}),
            Disk.from_dict(d.get("disk") or {}), d,
        )


# --------------------------------------------------------------------------- kid API (browse and play)


@dataclass(frozen=True)
class KidProfile:
    """`GET /api/kid/profiles` item."""

    profile_id: int
    name: str
    picture: str | None  # path of the uploaded photo, e.g. /img/profile/1.jpg
    avatar: str | None  # built-in avatar key: /static/avatars/{avatar}.svg

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KidProfile:
        return cls(int(d["profile_id"]), d["name"], d.get("picture"), d.get("avatar"))


@dataclass(frozen=True)
class Tile:
    episode_id: int
    show_id: int
    thumb: str  # path, e.g. /img/episode/4.jpg
    title: str
    progress: float | None
    finished: bool
    kind: str | None = None  # resume | next (continue watching only)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Tile:
        return cls(int(d["episode_id"]), int(d["show_id"]), d["thumb"], d.get("title") or "", d.get("progress"),
                   bool(d.get("finished")), d.get("kind"))


@dataclass(frozen=True)
class ShowRef:
    show_id: int
    artwork: str  # path, e.g. /img/show/2.jpg
    title: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShowRef:
        return cls(int(d["show_id"]), d["artwork"], d.get("title") or "")


@dataclass(frozen=True)
class Home:
    """`GET /api/kid/home`."""

    continue_watching: tuple[Tile, ...]
    shows: tuple[ShowRef, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Home:
        return cls(tuple(Tile.from_dict(t) for t in d.get("continue", ())),
                   tuple(ShowRef.from_dict(s) for s in d.get("shows", ())))


@dataclass(frozen=True)
class Show:
    """`GET /api/kid/shows/{id}`."""

    show_id: int
    artwork: str
    title: str
    episodes: tuple[Tile, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Show:
        return cls(int(d["show_id"]), d["artwork"], d.get("title") or "",
                   tuple(Tile.from_dict(t) for t in d.get("episodes", ())))
