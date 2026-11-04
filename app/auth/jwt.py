"""Admin JWTs. Only these grant access to admin routes; assistant tokens never do."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.config import Settings

ADMIN_TOKEN_TYPE = "admin"  # noqa: S105 - a claim value, not a secret


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AdminClaims:
    user_id: UUID
    org_id: UUID


def create_admin_token(settings: Settings, *, user_id: UUID, org_id: UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "typ": ADMIN_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_admin_token(settings: Settings, token: str) -> AdminClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pinned: never trust the header's alg
            options={"require": ["sub", "org_id", "typ", "iat", "exp"]},
        )
        if payload["typ"] != ADMIN_TOKEN_TYPE:
            raise InvalidTokenError("wrong token type")
        return AdminClaims(user_id=UUID(payload["sub"]), org_id=UUID(payload["org_id"]))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
