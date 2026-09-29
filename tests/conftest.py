import json
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from pytellybox import TellyboxClient
from pytellybox.mock import MockTellybox

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "tbx_secret_token_value"
READ_TOKEN = "tbx_read_only_token"


@pytest.fixture
def state_dict() -> dict:
    return json.loads((FIXTURES / "admin_state.json").read_text())


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
async def mock() -> AsyncIterator[MockTellybox]:
    m = MockTellybox(token=TOKEN, read_tokens=[READ_TOKEN], keepalive_s=0.05)
    server = TestServer(m.app)
    await server.start_server()
    m.base_url = str(server.make_url("")).rstrip("/")  # type: ignore[attr-defined]
    yield m
    await server.close()


@pytest.fixture
def client(mock: MockTellybox, session: aiohttp.ClientSession) -> TellyboxClient:
    return TellyboxClient(mock.base_url, TOKEN, session)  # type: ignore[attr-defined]
