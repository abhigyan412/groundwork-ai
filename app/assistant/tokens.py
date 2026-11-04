"""Assistant tokens (docs/security.md, ADR 0007).

- Generated with `secrets.token_urlsafe(32)`: random, and says nothing about the org.
- Looked up only by SHA-256 hash.
- A Fernet-encrypted copy lets the owner's dashboard show the link again; it is decrypted only
  behind the admin JWT. The plain token is never stored.
"""

import hashlib
import html
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

PREFIX_CHARS = 6


@dataclass(frozen=True)
class NewToken:
    token: str
    token_hash: str
    token_encrypted: str
    token_prefix: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(fernet_key: str) -> NewToken:
    token = secrets.token_urlsafe(32)
    return NewToken(
        token=token,
        token_hash=hash_token(token),
        token_encrypted=Fernet(fernet_key.encode()).encrypt(token.encode()).decode(),
        token_prefix=token[:PREFIX_CHARS],
    )


class TokenDecryptError(Exception):
    """The stored copy can't be decrypted (ASSISTANT_TOKEN_KEY changed): reset the link."""


def decrypt_token(fernet_key: str, token_encrypted: str) -> str:
    try:
        return Fernet(fernet_key.encode()).decrypt(token_encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptError from exc


def assistant_url(public_base_url: str, token: str) -> str:
    return f"{public_base_url}/a/{token}"


def embed_code(url: str, org_name: str, width: int, height: int) -> str:
    title = html.escape(f"{org_name} assistant", quote=True)
    return (
        f'<iframe src="{html.escape(url, quote=True)}" title="{title}" '
        f'width="{width}" height="{height}" style="border:0;max-width:100%" '
        f'loading="lazy"></iframe>'
    )
