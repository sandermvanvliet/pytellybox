# Changelog

Release notes for pytellybox. The workflow in `.github/workflows/publish.yml` publishes the section for a version as that release's notes (see `docs/RELEASING.md`).

## Unreleased

- Fix: a profile with an unlimited allowance (`allowance_s` null) no longer breaks parsing of the admin state; `Profile.allowance_s` is now `int | None`.
- Admin state: `AdminState.sessions` (`Session`) and `AdminState.inbox` (`Inbox`, HA-9), and per profile `allowance_source`, `max_session_source` and `visible_shows` (HA-10). Older servers without these fields still parse.
- Kid API: `kid_state()` and `kid_events()` with the `KidState` models, and `ui_mode`, `watch_in_app` and the time fields on `KidProfile`.
- `MockTellybox` serves the new fields, `/api/kid/events` and an `inbox` capability. The browser-only in-app player endpoints are deliberately not covered.

- Release process: tag-driven publish to PyPI and GitHub release, with the changelog section as notes.

## 0.1.0

- First release: `TellyboxClient` for the admin API (state, event stream, parent overrides) and the kid API (browse, play, pause, resume), typed models and errors, and `MockTellybox` for development and tests.
