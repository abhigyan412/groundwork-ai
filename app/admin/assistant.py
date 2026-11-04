"""Assistant link admin routes (JWT only). The link is shown again from the encrypted copy
(ADR 0007); public lookups use only the hash."""

from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.assistant import repository as repo
from app.assistant.tokens import (
    TokenDecryptError,
    assistant_url,
    decrypt_token,
    embed_code,
    new_token,
)
from app.auth.deps import CurrentOrg
from app.config import Settings, get_settings
from app.db.pool import get_db

router = APIRouter(prefix="/api/admin/assistant", tags=["assistant"])

DB = Annotated[asyncpg.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class AssistantLink(BaseModel):
    url: str
    embed_code: str
    token_prefix: str
    created_at: datetime


class RegeneratedAssistant(AssistantLink):
    token: str


def _link(settings: Settings, org_name: str, token: str, row: repo.AssistantRow) -> dict:
    url = assistant_url(settings.public_base_url, token)
    return {
        "url": url,
        "embed_code": embed_code(url, org_name, settings.embed_width, settings.embed_height),
        "token_prefix": row.token_prefix,
        "created_at": row.created_at,
    }


@router.get(
    "",
    name="get_assistant",
    responses={
        401: {"description": "Missing or invalid admin token"},
        409: {"description": "Stored link can't be decrypted; reset it"},
    },
)
async def get_assistant(account: CurrentOrg, conn: DB, settings: AppSettings) -> AssistantLink:
    """The org's assistant link and embed code. The first call creates the assistant."""
    key = settings.assistant_token_key.get_secret_value()
    async with conn.transaction():
        await repo.lock_org(conn, account.org_id)
        row = await repo.get_active(conn, account.org_id)
        if row is None:
            fresh = new_token(key)
            row = await repo.insert(conn, account.org_id, fresh)
            return AssistantLink(**_link(settings, account.org_name, fresh.token, row))
    try:
        token = decrypt_token(key, row.token_encrypted)
    except TokenDecryptError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This link can't be shown because the server's key changed. "
            "Reset the link to create a new one.",
        ) from None
    return AssistantLink(**_link(settings, account.org_name, token, row))


@router.post(
    "/regenerate",
    name="regenerate_assistant",
    responses={401: {"description": "Missing or invalid admin token"}},
)
async def regenerate_assistant(
    account: CurrentOrg, conn: DB, settings: AppSettings
) -> RegeneratedAssistant:
    """Revoke the current link immediately and create a new one."""
    fresh = new_token(settings.assistant_token_key.get_secret_value())
    async with conn.transaction():
        await repo.lock_org(conn, account.org_id)
        await repo.revoke_active(conn, account.org_id)
        row = await repo.insert(conn, account.org_id, fresh)
    return RegeneratedAssistant(
        token=fresh.token, **_link(settings, account.org_name, fresh.token, row)
    )
