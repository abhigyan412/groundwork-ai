"""Task 01: register -> login -> protected route, plus the failure modes around it."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.jwt import create_admin_token
from app.config import get_settings
from tests.conftest import Account, register


async def test_register_login_me_flow(client):
    r = await client.post(
        "/auth/register",
        json={
            "org_name": "  Riverside University ",
            "email": "Admin@Riverside.EDU",
            "password": "correct horse battery",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["org"]["name"] == "Riverside University"  # trimmed
    assert body["token"]

    r = await client.post(
        "/auth/login", json={"email": "admin@riverside.edu", "password": "correct horse battery"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["org"] == {"id": body["org"]["id"], "name": "Riverside University"}
    assert me["email"] == "admin@riverside.edu"  # stored lower-cased


async def test_register_token_works_immediately(client, org_a: Account):
    r = await client.get("/api/admin/me", headers=org_a.headers)
    assert r.status_code == 200
    assert r.json()["org"]["name"] == org_a.org_name


async def test_duplicate_email_is_409_case_insensitive(client, org_a: Account):
    r = await client.post(
        "/auth/register",
        json={"org_name": "Other", "email": org_a.email.upper(), "password": "another password"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "That email already has a workspace. Log in instead."


async def test_login_wrong_password_and_unknown_email_look_identical(client, org_a: Account):
    wrong = await client.post("/auth/login", json={"email": org_a.email, "password": "nope-nope"})
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@nowhere.com", "password": "nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Email or password is incorrect."}


async def test_password_is_hashed_not_stored(client, db, org_a: Account):
    stored = await db.fetchval("SELECT password_hash FROM users WHERE email = $1", org_a.email)
    assert stored != org_a.password
    assert stored.startswith("$argon2id$")


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"email": "a@example.com", "password": "longenough"}, "org_name", "Organization name is required."),
        ({"org_name": "  ", "email": "a@example.com", "password": "longenough"}, "org_name", "Organization name can't be empty."),
        ({"org_name": "X", "email": "not-an-email", "password": "longenough"}, "email", "Enter a valid email address."),
        ({"org_name": "X", "email": "a@example.com", "password": "short"}, "password", "Password must be at least 8 characters."),
    ],
)  # fmt: skip
async def test_register_invalid_input_is_400_with_friendly_message(client, payload, field, message):
    r = await client.post("/auth/register", json=payload)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"] == message
    assert body["errors"][0]["field"] == field


async def test_malformed_json_is_400(client):
    r = await client.post(
        "/auth/login", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Request body must be valid JSON."


# --- get_current_org ---------------------------------------------------------------------------


def _forge(claims: dict, secret: str | None = None) -> str:
    s = get_settings()
    return jwt.encode(claims, secret or s.jwt_secret.get_secret_value(), algorithm="HS256")


async def test_me_requires_token(client):
    r = await client.get("/api/admin/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "auth_header",
    [
        "Bearer not-a-jwt",
        "Basic dXNlcjpwYXNz",
        # An assistant token (opaque url-safe string) must never pass as an admin credential.
        "Bearer k3f9Qx7_v8M2nLpR4tYb1cZ6dWe0aHs5jUo9iKg3fTq",
    ],
)
async def test_me_rejects_non_jwt_credentials(client, auth_header):
    r = await client.get("/api/admin/me", headers={"Authorization": auth_header})
    assert r.status_code == 401


async def test_me_rejects_expired_token(client, org_a: Account):
    claims = jwt.decode(org_a.token, options={"verify_signature": False})
    past = datetime.now(UTC) - timedelta(hours=1)
    token = _forge({**claims, "iat": past - timedelta(hours=1), "exp": past})
    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_rejects_wrong_signature(client, org_a: Account):
    claims = jwt.decode(org_a.token, options={"verify_signature": False})
    token = _forge(claims, secret="x" * 48)
    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_rejects_wrong_token_type(client, org_a: Account):
    claims = jwt.decode(org_a.token, options={"verify_signature": False})
    token = _forge({**claims, "typ": "assistant"})
    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_rejects_alg_none(client, org_a: Account):
    claims = jwt.decode(org_a.token, options={"verify_signature": False})
    token = jwt.encode(claims, key=None, algorithm="none")
    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_cannot_be_repointed_to_another_org(client, org_a: Account, org_b: Account):
    """A validly signed token whose org_id doesn't match the user's org is rejected."""
    claims = jwt.decode(org_a.token, options={"verify_signature": False})
    token = _forge({**claims, "org_id": org_b.org_id})
    r = await client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_deleted_org_loses_access(client, db, org_a: Account):
    await db.execute("DELETE FROM organizations WHERE id = $1", org_a.org_id)
    r = await client.get("/api/admin/me", headers=org_a.headers)
    assert r.status_code == 401


async def test_each_org_sees_only_itself(client, org_a: Account, org_b: Account):
    a = (await client.get("/api/admin/me", headers=org_a.headers)).json()
    b = (await client.get("/api/admin/me", headers=org_b.headers)).json()
    assert a["org"]["id"] == org_a.org_id and a["org"]["name"] == "Riverside University"
    assert b["org"]["id"] == org_b.org_id and b["org"]["name"] == "Northwind Technologies"


async def test_org_id_in_request_is_ignored(client, org_a: Account, org_b: Account):
    """org_id only ever comes from the credential, never the query string."""
    r = await client.get(f"/api/admin/me?org_id={org_b.org_id}", headers=org_a.headers)
    assert r.status_code == 200
    assert r.json()["org"]["id"] == org_a.org_id


def test_created_token_has_expected_claims():
    from uuid import uuid4

    s = get_settings()
    uid, oid = uuid4(), uuid4()
    claims = jwt.decode(
        create_admin_token(s, user_id=uid, org_id=oid),
        s.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    assert claims["sub"] == str(uid) and claims["org_id"] == str(oid) and claims["typ"] == "admin"
    assert claims["exp"] - claims["iat"] == s.jwt_expire_minutes * 60


async def test_second_org_registration_is_independent(client, org_a: Account):
    other = await register(client, "Riverside University", "second@riverside.edu")
    assert other.org_id != org_a.org_id  # same name, separate tenant
