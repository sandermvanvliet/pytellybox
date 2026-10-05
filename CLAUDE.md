# pytellybox

Async Python client for the [Tellybox](https://github.com/sandermvanvliet/Tellybox) admin and kid APIs, published to PyPI as `pytellybox`. It is the library behind the [Home Assistant integration](https://github.com/sandermvanvliet/ha-tellybox), which pins a release of it.

## Hard rules

- The client never becomes a way around the timer: Tellybox decides, and a play refused for lack of time stays refused.
- The API contract is Tellybox's `docs/admin-api.md` and `docs/kid-api.md`. Don't invent endpoints or fields.
- Keep the owner's hostnames, IPs, tokens and internal domains out of committed files, tests and fixtures. Keep tokens out of logs and error messages.

## Layout

- `src/pytellybox/`: `client.py` (`TellyboxClient`), `models.py`, `errors.py`, `mock.py` (`MockTellybox`, also runnable with `python -m pytellybox.mock`), typed (`py.typed`).
- `tests/`: pytest with `aioresponses` and the mock server; no real Tellybox needed.

## How to work

- Run tests with `.venv/bin/python -m pytest -q`. CI (`.github/workflows/ci.yml`) runs them on Python 3.13 and 3.14.
- Add tests with every change. Keep the mock in step with the client.
- Releases follow `docs/RELEASING.md`. Never tag, push a tag or publish a release without the owner's explicit go-ahead. Record user-visible changes under `## Unreleased` in `CHANGELOG.md` as you go.
- The version is in `pyproject.toml`; only the release PR changes it.
