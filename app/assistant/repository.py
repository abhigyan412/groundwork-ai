"""SQL for assistants. Public lookups go only through the token hash."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from app.assistant.tokens import NewToken


@dataclass(frozen=True)
class AssistantRow:
    id: UUID
    token_encrypted: str
    token_prefix: str
    created_at: datetime


@dataclass(frozen=True)
class TokenOwner:
    org_id: UUID
    org_name: str
    assistant_id: UUID


async def get_active(conn: asyncpg.Connection, org_id: UUID) -> AssistantRow | None:
    r = await conn.fetchrow(
        "SELECT id, token_encrypted, token_prefix, created_at FROM assistants"
        " WHERE org_id = $1 AND revoked_at IS NULL",
        org_id,
    )
    return AssistantRow(**dict(r)) if r else None


async def insert(conn: asyncpg.Connection, org_id: UUID, token: NewToken) -> AssistantRow:
    r = await conn.fetchrow(
        """
        INSERT INTO assistants (org_id, token_hash, token_encrypted, token_prefix)
        VALUES ($1, $2, $3, $4)
        RETURNING id, token_encrypted, token_prefix, created_at
        """,
        org_id,
        token.token_hash,
        token.token_encrypted,
        token.token_prefix,
    )
    return AssistantRow(**dict(r))


async def revoke_active(conn: asyncpg.Connection, org_id: UUID) -> None:
    await conn.execute(
        "UPDATE assistants SET revoked_at = now() WHERE org_id = $1 AND revoked_at IS NULL", org_id
    )


async def lock_org(conn: asyncpg.Connection, org_id: UUID) -> None:
    """Serialize create/regenerate per org (inside a transaction)."""
    await conn.execute("SELECT 1 FROM organizations WHERE id = $1 FOR UPDATE", org_id)


async def owner_of(conn: asyncpg.Connection, token_hash: str) -> TokenOwner | None:
    """The org behind an active token, or None for unknown or revoked tokens."""
    r = await conn.fetchrow(
        """
        SELECT a.id AS assistant_id, o.id AS org_id, o.name AS org_name
        FROM assistants a JOIN organizations o ON o.id = a.org_id
        WHERE a.token_hash = $1 AND a.revoked_at IS NULL
        """,
        token_hash,
    )
    return TokenOwner(**dict(r)) if r else None
