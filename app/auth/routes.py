from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.jwt import create_admin_token
from app.auth.passwords import hash_password, verify_password
from app.auth.repository import EmailTakenError, create_org_with_user, get_user_by_email
from app.auth.schemas import (
    LoginRequest,
    LoginResponse,
    OrgOut,
    RegisterRequest,
    RegisterResponse,
)
from app.config import Settings, get_settings
from app.db.pool import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

DB = Annotated[asyncpg.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Invalid input"}, 409: {"description": "Email exists"}},
)
async def register(body: RegisterRequest, conn: DB, settings: AppSettings) -> RegisterResponse:
    password_hash = await hash_password(body.password)
    try:
        org_id, user_id = await create_org_with_user(
            conn, org_name=body.org_name, email=body.email, password_hash=password_hash
        )
    except EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email already has a workspace. Log in instead.",
        ) from None
    token = create_admin_token(settings, user_id=user_id, org_id=org_id)
    return RegisterResponse(token=token, org=OrgOut(id=org_id, name=body.org_name))


@router.post("/login", responses={401: {"description": "Invalid credentials"}})
async def login(body: LoginRequest, conn: DB, settings: AppSettings) -> LoginResponse:
    user = await get_user_by_email(conn, body.email)
    # Always verify (against a dummy hash if the user is unknown) so timing doesn't leak emails.
    ok = await verify_password(user.password_hash if user else None, body.password)
    if user is None or not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    return LoginResponse(
        token=create_admin_token(settings, user_id=user.user_id, org_id=user.org_id)
    )
