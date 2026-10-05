# Releasing

How a release of pytellybox is made. It mirrors [Tellybox's own process](https://github.com/sandermvanvliet/tellybox/blob/main/docs/RELEASING.md) and the [integration's](https://github.com/sandermvanvliet/ha-tellybox/blob/main/docs/RELEASING.md): a release only happens when the owner pushes a `v*` tag. Never tag, push a tag or publish a release without the owner's explicit go-ahead.

## Versioning

[Semantic versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. While the major version is 0, a minor bump may contain breaking changes and a patch bump only fixes bugs. The version lives in `version` in `pyproject.toml`.

## Before you start

- `main` is green (the *CI* workflow passed).
- `CHANGELOG.md` describes everything since the last release under `## Unreleased`, including any change that needs a newer Tellybox or breaks callers.
- If the integration needs this release, bump the `pytellybox` pin in its `manifest.json` only after the release is on PyPI.

## Steps

1. On a branch, set the version in `pyproject.toml` to `X.Y.Z`, and rename `## Unreleased` in `CHANGELOG.md` to `## X.Y.Z` (add a fresh empty `## Unreleased` above it). Merge by pull request.
2. Update your checkout to the merge commit on `main`.
3. Tag that commit and push the tag:

   ```sh
   git checkout main && git pull
   git tag -a vX.Y.Z -m "pytellybox X.Y.Z"
   git push origin vX.Y.Z
   ```

The tag must be `v` plus the exact version in `pyproject.toml`.

## What CI does

Pushing a `v*` tag runs `.github/workflows/publish.yml`, which fails before publishing anything if a check fails:

1. The tag matches the version in `pyproject.toml`.
2. `CHANGELOG.md` has a non-empty `## X.Y.Z` section.
3. `pytest -q` passes.
4. The package is built and published to PyPI (trusted publishing, `pypi` environment).
5. The GitHub release is created (only if it doesn't exist yet), titled `X.Y.Z`, with that changelog section as its notes.

Don't rename `publish.yml`: the PyPI trusted publisher is registered for that filename.

## Check the result

- The workflow run for the tag is green in the Actions tab.
- `pip index versions pytellybox` (or <https://pypi.org/project/pytellybox/>) lists the new version.
- `gh release view vX.Y.Z` shows the release and the changelog notes.

## If a release is bad

PyPI versions can't be replaced. Never move or delete a tag that people may have pulled; fix the problem on `main` and release the next patch version, and yank the bad version on PyPI if it is harmful. If the workflow failed before the PyPI publish, delete the tag (and any release) so the version can be tagged again.
