"""A mock Tellybox server for developing and testing integrations without a real Tellybox.

Contract only: subagent A implements it. `python -m pytellybox.mock --port 8099 --token tbx_dev` serves:
- `/api/info`, `/api/admin/state`, `/api/admin/events` (SSE with keepalive), the override routes, with the
  same auth rules as Tellybox (401 / 403, a read-only token via `read_tokens`);
- `/api/kid/profiles`, `/home`, `/shows/{id}`, `/play` (409 when a watcher can't start), `/pause`, `/resume`;
- `/img/...` placeholder JPEGs.
Overrides change the scripted state the way Tellybox would (extra time, unlimited, block, clear, stop) and
push a new event. Tests and scripts drive it through `MockTellybox`: `set_state(dict)`, `push()`,
`calls` (recorded requests), and `app` (an aiohttp `web.Application`).
"""
