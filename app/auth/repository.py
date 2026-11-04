"""SQL for organizations and users.

`users` is looked up by email at login, before any org is known; that's the one lookup that
can't be org-scoped. Everything after login is scoped by the org_id from the JWT.
"""

from dataclasses import dataclass
from uuid import UUID

import asyncpg


class EmailTakenError(Exception):
    pass


@dataclass(frozen=True)
class UserRecord:
    user_id: UUID
    org_id: UUID
    password_hash: str


@dataclass(frozen=True)
class OrgAccount:
    org_id: UUID
    org_name: str
    email: str


async def create_org_with_user(
    conn: asyncpg.Connection, *, org_name: str, email: str, password_hash: str
) -> tuple[UUID, UUID]:
    """Create the organization and its first user atomically. Returns (org_id, user_id)."""
    try:
        async with conn.transaction():
            org_id = await conn.fetchval(
                "INSERT INTO organizations (name) VALUES ($1) RETURNING id", org_name
            )
            user_id = await conn.fetchval(
                "INSERT INTO users (org_id, email, password_hash) VALUES ($1, $2, $3) RETURNING id",
                org_id,
                email,
                password_hash,
            )
    except asyncpg.UniqueViolationError as exc:
        raise EmailTakenError(email) from exc
    return org_id, user_id


async def get_user_by_email(conn: asyncpg.Connection, email: str) -> UserRecord | None:
    row = await conn.fetchrow(
        "SELECT id, org_id, password_hash FROM users WHERE lower(email) = lower($1)", email
    )
    if row is None:
        return None
    return UserRecord(user_id=row["id"], org_id=row["org_id"], password_hash=row["password_hash"])


async def get_org_account(
    conn: asyncpg.Connection, *, user_id: UUID, org_id: UUID
) -> OrgAccount | None:
    """Resolve a JWT's (user, org) pair. Both must match, so a token can't be re-pointed."""
    row = await conn.fetchrow(
        """
        SELECT o.id, o.name, u.email
        FROM users u
        JOIN organizations o ON o.id = u.org_id
        WHERE u.id = $1 AND u.org_id = $2
        """,
        user_id,
        org_id,
    )
    if row is None:
        return None
    return OrgAccount(org_id=row["id"], org_name=row["name"], email=row["email"])
