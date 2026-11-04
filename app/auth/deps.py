"""`get_current_org`: the only way admin routes learn which organization they act for."""

from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import InvalidTokenError, decode_admin_token
from app.auth.repository import OrgAccount, get_org_account
from app.config import Settings, get_settings
from app.db.pool import get_db

_bearer = HTTPBearer(auto_error=False, description="Admin JWT from /auth/login")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Your session has expired or is invalid. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_org(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    conn: Annotated[asyncpg.Connection, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OrgAccount:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        claims = decode_admin_token(settings, credentials.credentials)
    except InvalidTokenError:
        raise _UNAUTHORIZED from None
    # Re-read from the DB so a deleted user/org loses access even with an unexpired token.
    account = await get_org_account(conn, user_id=claims.user_id, org_id=claims.org_id)
    if account is None:
        raise _UNAUTHORIZED
    return account


CurrentOrg = Annotated[OrgAccount, Depends(get_current_org)]
