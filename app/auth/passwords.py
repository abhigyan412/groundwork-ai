"""Argon2id password hashing. Hashing is CPU-bound, so callers run it via asyncio.to_thread."""

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id, RFC 9106 low-memory profile

# Verified against when the email is unknown, so login takes the same time either way
# and response timing doesn't reveal which emails have accounts.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


def _hash(password: str) -> str:
    return _hasher.hash(password)


def _verify(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Return True only if `password_hash` is a real hash and matches. None = unknown user."""
    return await asyncio.to_thread(_verify, password_hash, password)
