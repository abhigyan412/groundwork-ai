# 0007: Keep an encrypted copy of the assistant token

**Status:** Accepted (default chosen at the start of task 01; revisit if the reviewer prefers show-once)

## Context
`docs/security.md` and `CLAUDE.md` said to store only the SHA-256 hash of the assistant token and show the plain token once. But the Assistant page (`docs/frontend.md` §6.5) shows the link, an Open button, the embed code and a live preview iframe on every visit, and `GET /api/admin/assistant` returns `url` and `embed_code`. All of those need the full token. A hash alone can't produce them.

Options considered:
1. Show once. If the owner loses the link, they reset it. This breaks the live preview after a reload, and resetting cuts off every existing embed.
2. Store the plain token. Rejected: a database leak would expose every org's working token.
3. Store the hash for lookup **and** a Fernet-encrypted copy for re-display, keyed by `ASSISTANT_TOKEN_KEY` from `.env`.

## Decision
Option 3. Public routes look tokens up **only** by `token_hash`. `token_encrypted` is decrypted only inside `GET /api/admin/assistant`, which requires the org's JWT.

## Consequences
- The dashboard behaves like a normal SaaS product: the link and embed code are always available to the owner.
- A database dump alone doesn't reveal working tokens. An attacker needs both the database and `ASSISTANT_TOKEN_KEY`.
- Rotating `ASSISTANT_TOKEN_KEY` makes stored copies unreadable. Recovery means resetting the link (documented in the README).
- The CLAUDE.md rule now reads: "Look up assistant tokens only by hash; the plain token is never stored unencrypted."
- Production: keep the key in a KMS/secret manager instead of `.env`.
