<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/sandermvanvliet/Tellybox/main/docs/images/brand/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/sandermvanvliet/Tellybox/main/docs/images/brand/logo.svg" alt="Tellybox" width="420">
  </picture>
  <br>pytellybox
</h1>

An async Python client for [Tellybox](https://github.com/sandermvanvliet/Tellybox), the self-hosted app that lets young kids pick parent-approved videos for the TV within a daily time allowance. It is the library behind the [Home Assistant integration](https://github.com/sandermvanvliet/ha-tellybox).

- **Admin API** (bearer token from Tellybox's *Integrations* page): live state (including the active sessions, the subscription inbox and how many shows each kid can see) and its event stream, and the parent overrides (extra time, unlimited today, block today, stop now, clear today) for everyone or for chosen kids.
- **Kid API** (no token): browse shows and episodes, play, pause and resume, and the live kid state with its event stream. A play is refused when someone is out of time, because Tellybox's timer always decides.

```python
import aiohttp
from pytellybox import TellyboxClient

async with aiohttp.ClientSession() as session:
    tellybox = TellyboxClient("https://tellybox.example", "tbx_…", session)
    state = await tellybox.state()
    for kid in state.profiles:
        print(kid.name, kid.remaining_s)
    await tellybox.add_time(15, profile_ids=[1])
    async for state in tellybox.events():  # the current state first, then one per change
        print(state.group.remaining_s)
```

For development without a Tellybox, run the mock server: `python -m pytellybox.mock --port 8099 --token tbx_dev` (add `--read-token tbx_ro` for a read-only token). Tests can use `MockTellybox` from `pytellybox.mock` with aiohttp's `TestServer`.

The API contract is Tellybox's [`docs/admin-api.md`](https://github.com/sandermvanvliet/Tellybox/blob/main/docs/admin-api.md) and [`docs/kid-api.md`](https://github.com/sandermvanvliet/Tellybox/blob/main/docs/kid-api.md). Tellybox is for the LAN and Tailscale only; use HTTPS behind your reverse proxy, and keep tokens out of logs.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Releases are published to PyPI by GitHub Actions when a `v*` tag is pushed (trusted publishing).

Licensed under Apache-2.0.
