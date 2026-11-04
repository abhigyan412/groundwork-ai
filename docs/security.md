# Security

## Access rules

- **Only the logged-in organization account can upload, replace or delete documents.** Visitors can only ask questions. Enforced on the server, not just in the UI. [Confirmed]
- Admin routes accept only the JWT; public routes accept only the assistant token. An assistant token can never reach admin routes.
- `org_id` is always taken from the validated credential, never from the request body or query string.
- Every query on tenant tables filters by `org_id`.

## Assistant token [Proposed]

- Generated with `secrets.token_urlsafe(32)`.
- Lookups use only the SHA-256 hash. A Fernet-encrypted copy (key `ASSISTANT_TOKEN_KEY`) lets the owner's dashboard show the link again; it's decrypted only behind the admin JWT (ADR 0007).
- Regeneration sets `revoked_at` on the old token; it stops working immediately.
- The token reveals nothing about the org, its users or its documents.

## Admin authentication [Proposed]

- Passwords hashed with Argon2id (`argon2-cffi`). Login verifies against a dummy hash for unknown emails, so timing doesn't reveal which emails have accounts.
- JWT (HS256, algorithm pinned on decode), signed with `JWT_SECRET` (≥ 32 chars) from `.env`. Claims: `sub` (user id), `org_id`, `typ: "admin"`, `iat`, `exp`. Expiry `JWT_EXPIRE_MINUTES`, default 480.
- `get_current_org` re-reads the user and org from the database on every request and requires the JWT's `org_id` to match the user's org, so deleted accounts lose access immediately and a token can't be re-pointed.

## Documents

- Stored at `storage/{org_id}/{document_id}.pdf`, outside any static or public path.
- No endpoint serves PDF files to visitors; references show filename and page only.
- Deleting a document removes the file and its chunks.

## Frontend and embedding

- Only the widget route `/a/*` can be framed (`frame-ancestors *`); all other routes send `frame-ancestors 'none'`, so the dashboard can't be embedded (clickjacking).
- nginx proxies the API, so the browser sees one origin; no CORS configuration is needed.
- JWT kept in `localStorage` for the MVP; on 401 the app clears it and redirects to login. Production: httpOnly, SameSite cookie.

## Other

- Basic per-token rate limit on `/api/ask` (optional).
- No secrets committed; `.env.example` lists required variables.
- Text from PDFs is treated as data in LLM prompts, never as instructions.

## Isolation tests

Listed in `tests/evaluation.md`. They must pass before submission.

## Production improvements

- Postgres row-level security as a second isolation layer.
- Multiple users per org with roles (owner, editor, viewer).
- Object storage with signed URLs.
