"""Test setup: a real Postgres (the compose `db` service), truncated before each test.

Set TEST_DATABASE_URL to override. The database name must end in `_test`; anything else is
refused so the tests can never wipe the dev database.
"""

import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlparse

import asyncpg
import pytest
from cryptography.fernet import Fernet

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://groundwork:groundwork@localhost:5433/groundwork_test"
)
if not urlparse(TEST_DATABASE_URL).path.rstrip("/").endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against non-test database: {TEST_DATABASE_URL}")

# Must be set before app.config.get_settings() is first called. Env vars beat .env values.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["ASSISTANT_TOKEN_KEY"] = Fernet.generate_key().decode()
os.environ["LLM_PROVIDER"] = "fake"
os.environ.setdefault("STORAGE_DIR", os.path.join(os.path.dirname(__file__), ".storage"))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with app.router.lifespan_context(app):  # applies schema, opens the pool
        async with app.state.db_pool.acquire() as conn:
            # Cascades to users, assistants, documents, chunks, questions.
            await conn.execute("TRUNCATE organizations CASCADE")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()


@dataclass
class Account:
    org_id: str
    org_name: str
    email: str
    password: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def register(client: httpx.AsyncClient, org_name: str, email: str) -> Account:
    password = "correct horse battery"
    r = await client.post(
        "/auth/register", json={"org_name": org_name, "email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return Account(body["org"]["id"], body["org"]["name"], email, password, body["token"])


@pytest.fixture
async def org_a(client: httpx.AsyncClient) -> Account:
    return await register(client, "Riverside University", "admin@riverside.edu")


@pytest.fixture
async def org_b(client: httpx.AsyncClient) -> Account:
    return await register(client, "Northwind Technologies", "hr@northwind.com")
