# Changelog

Release notes for pytellybox. The workflow in `.github/workflows/publish.yml` publishes the section for a version as that release's notes (see `docs/RELEASING.md`).

## Unreleased

- Release process: tag-driven publish to PyPI and GitHub release, with the changelog section as notes.

## 0.1.0

- First release: `TellyboxClient` for the admin API (state, event stream, parent overrides) and the kid API (browse, play, pause, resume), typed models and errors, and `MockTellybox` for development and tests.
