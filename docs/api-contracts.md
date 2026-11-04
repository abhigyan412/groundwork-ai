# API Contracts [Proposed]

## Authentication

- **Admin routes:** `Authorization: Bearer <JWT>`. `org_id` comes from the JWT.
- **Public routes:** assistant token in the URL path or request body. `org_id` comes from the token lookup.

## Errors

All errors are JSON with a human-readable `detail`. Invalid input returns **400** (not FastAPI's default 422) with one entry per field, so forms can show messages inline:

```json
{ "detail": "Password must be at least 8 characters.",
  "errors": [{ "field": "password", "message": "Password must be at least 8 characters." }] }
```

Admin routes return 401 with `"Your session has expired or is invalid. Please log in again."` for a missing, expired or invalid JWT.

## Admin

### POST /auth/register
Request: `{ "org_name": str, "email": str, "password": str }`
Response 201: `{ "token": "<jwt>", "org": { "id", "name" } }`
Errors: 400 invalid input (org name 1–120 chars, valid email, password 8–128 chars), 409 email exists ("That email already has a workspace. Log in instead.").

### POST /auth/login
Request: `{ "email": str, "password": str }`
Response 200: `{ "token": "<jwt>" }`
Errors: 401 invalid credentials ("Email or password is incorrect.", identical for unknown email and wrong password).

### GET /api/admin/me
Response 200: `{ "org": { "id", "name" }, "email" }`. Used by the app shell.

### GET /health
Response 200: `{ "status": "ok", "db": "ok" }`; 503 with `db: "unavailable"` if Postgres is unreachable. No auth.

### GET /api/admin/documents
Response 200:
```json
{ "documents": [{ "id", "filename", "page_count", "size_bytes", "status", "error", "created_at" }],
  "limits": { "documents_used": 4, "documents_max": 10, "max_pages": 20, "max_mb": 10 } }
```

### POST /api/admin/documents
Multipart `file`. Response 202: `{ "id", "filename", "status": "processing" }`

| Error | Status | Message |
|---|---|---|
| Not a PDF / corrupt | 400 | File is not a valid PDF |
| > 10 MB | 413 | PDF exceeds the 10 MB limit |
| > 20 pages | 400 | PDF has N pages; the limit is 20 |
| 10 documents already | 409 | Document limit reached (10). Delete one to upload more. |

### DELETE /api/admin/documents/{id}
Response 204. Error 404 if not found **or owned by another org** (no difference revealed).

### GET /api/admin/assistant
Response 200: `{ "url": "https://host/a/<token-prefix>…", "embed_code": "<iframe …>", "created_at" }`
The full token is only returned on creation/regeneration.

### POST /api/admin/assistant/regenerate
Response 200: `{ "token", "url", "embed_code" }`. Old token revoked immediately.

### GET /api/admin/usage
Response 200: `{ "asked": int, "answered": int, "unanswered": int, "needs_info": int, "review": int }`

### GET /api/admin/questions?limit=20
Response 200: `{ "questions": [{ "id", "question", "route", "outcome", "answer", "verdicts", "references", "created_at" }] }`
Recent questions for the usage page, including the stored evidence trail.

## Public

The widget page itself is a React route (`/a/:token`) served by nginx; it calls the endpoints below.

### GET /api/public/assistant/{token}
Response 200: `{ "org_name": str, "suggested_questions": [str] }`
Errors: 401 invalid or revoked token (widget shows "This assistant link is no longer active").

### POST /api/ask
Request: `{ "token": str, "question": str }`

Response 200:
```json
{
  "answer": "You're not eligible yet ...",
  "outcome": "answered | unanswered | needs_info | review",
  "references": [{ "file": "Scholarship_Rules.pdf", "page": 4 }],
  "route": "decision",
  "verdicts": [{ "id": "d1", "value": "TRUE", "confidence": 1.0, "source": "Scholarship_Rules.pdf p4" }],
  "timings_ms": { "retrieve": 120, "classify": 8, "decisions": { "d1": 1, "d2": 1, "d3": 140 }, "compose": 900 }
}
```

| Error | Status | Message |
|---|---|---|
| Invalid / revoked token | 401 | This assistant link is invalid or has been reset |
| Empty question | 400 | Please enter a question |
| No relevant knowledge | 200 | `outcome: unanswered` with explanation |
| LLM failure | 200 / 503 | Verdicts still returned if available; "Couldn't generate an answer, please try again" |
| Decision-model failure | 200 | Affected decision is UNKNOWN; `outcome: review` |
