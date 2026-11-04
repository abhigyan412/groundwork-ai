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
Response 200 (newest first):
```json
{ "documents": [{ "id", "filename", "page_count", "size_bytes", "status", "error", "pages_without_text": [2], "created_at" }],
  "limits": { "documents_used": 4, "documents_max": 10, "max_pages": 20, "max_mb": 10 } }
```

### POST /api/admin/documents
Multipart `file`. Response 202: `{ "id", "filename", "status": "processing" }`. Processing (extract → chunk → embed) runs in the background; poll the list until `status` is `ready` or `failed` (`error` says why, e.g. "No readable text found. Scanned PDFs aren't supported; upload a text-based PDF."). `filename` is the uploaded name with any directory parts removed.

| Error | Status | Message |
|---|---|---|
| Not a PDF / corrupt / empty | 400 | This file isn't a valid PDF. |
| Password-protected | 400 | This PDF is password-protected. Remove the password and upload it again. |
| > 10 MB | 413 | This PDF is 12.4 MB. The limit is 10 MB. |
| > 20 pages | 400 | This PDF has 24 pages. The limit is 20. |
| 10 documents already (failed ones don't count) | 409 | Document limit reached (10). Delete one to upload more. |
| No file | 400 | File is required. |

### PUT /api/admin/documents/{id}
Replace the file behind a document (the row menu's "Replace"). Multipart `file`, same validation and errors as upload. Keeps the document's slot, so it works at 10/10 (except when replacing a `failed` document at the limit → 409). The old chunks are dropped and the new file is processed. Response 202: `{ "id", "filename", "status": "processing" }`. 404 if not found or owned by another org.

### DELETE /api/admin/documents/{id}
Response 204: removes the row, its chunks and the stored file. Error 404 `"Document not found."` if not found, malformed id, **or owned by another org** (no difference revealed).

### GET /api/admin/assistant
Response 200: `{ "url": "https://host/a/<token>", "embed_code": "<iframe …>", "token_prefix", "created_at" }`
- The first call creates the org's assistant.
- The full link is shown on every call, decrypted from the stored encrypted copy (ADR 0007). Public routes look tokens up only by hash.
- Error 409 "This link can't be shown because the server's key changed. Reset the link to create a new one." if `ASSISTANT_TOKEN_KEY` changed since the link was created.

### POST /api/admin/assistant/regenerate
Response 200: `{ "token", "url", "embed_code", "token_prefix", "created_at" }`. The old token is revoked in the same transaction, so it stops working immediately.

### GET /api/admin/usage
Response 200: `{ "asked": int, "answered": int, "unanswered": int, "needs_info": int, "review": int }`. `asked` is the total; a question that got a 503 (LLM unavailable) is logged and counted as `review`.

### GET /api/admin/questions?limit=20
Response 200: `{ "questions": [{ "id", "question", "route", "outcome", "answer", "verdicts", "references", "timings_ms", "created_at" }] }`
Recent questions for the usage page, newest first, including the stored evidence trail (`verdicts` and `timings_ms` have the same shapes as in `/api/ask`). `limit` is 1–100 (400 otherwise).

## Public

The widget page itself is a React route (`/a/:token`) served by nginx; it calls the endpoints below.

### GET /api/public/assistant/{token}
Response 200: `{ "org_name": str, "suggested_questions": [str] }`. Suggested questions are built by code from the org's ready documents (up to 3: "What does the Hostel Policy document cover?"). No LLM call.
Errors: 401 invalid or revoked token (widget shows "This assistant link is no longer active").

### POST /api/ask
Request: `{ "token": str, "question": str }`. The token is checked first, so a dead link always gets 401. Any other field (e.g. `org_id`) is ignored. Whitespace in the question is normalized; at most 1000 characters. Every question is logged to `questions` with its route, outcome, answer, verdicts, references, timings and LLM token usage.

Response 200:
```json
{
  "answer": "You're not eligible yet ...",
  "outcome": "answered | unanswered | needs_info | review",
  "references": [{ "file": "Scholarship_Rules.pdf", "page": 4 }],
  "route": "decision",
  "verdicts": [{ "id": "d1", "kind": "fact", "label": "GPA at least 3.5", "rule": "Applicants must hold…",
                 "value": "TRUE", "confidence": 1.0, "user_value": 3.6, "missing_fact": null,
                 "source": { "file": "Scholarship_Rules.pdf", "page": 4, "excerpt": "Applicants must hold…" },
                 "reason": null }],
  "timings_ms": { "retrieve": 120, "classify": 8, "decompose": 2100, "grounding": 160,
                  "decisions": { "d1": 1, "d2": 1, "d3": 140 }, "compose": 900, "total": 3300 },
  "overall": "TRUE",
  "confidence": 1.0,
  "answer_source": "llm"
}
```

- `route`: the path actually taken (`null` when stopped at the gate). A policy question with no matching pattern, or a comparison the LLM couldn't structure, reports `decision`.
- `overall`: combined result on the decision, policy and comparison paths; `null` for direct and procedural answers.
- `confidence`: minimum confidence of the deciding verdicts (decision path only).
- `answer_source`: `llm`; `template` when `compose()` failed but verdicts existed (the answer is built by code from them); `none` for gate refusals.
- `verdicts[].kind`: `fact` | `nli` | `policy` | `choice` | `score`. Comparison verdicts carry `detail` (e.g. "32,000 INR per semester"); TRUE marks the chosen option.

| Error | Status | Message |
|---|---|---|
| Invalid / revoked token | 401 | This assistant link is invalid or has been reset |
| Empty question | 400 | Please enter a question |
| Question over 1000 characters | 400 | Questions can be up to 1000 characters. |
| More than 20 questions a minute for one assistant | 429 | Too many questions right now. Please wait a minute. |
| No relevant knowledge | 200 | `outcome: unanswered` with explanation |
| LLM failure, verdicts exist | 200 | Template answer built from the verdicts (`answer_source: "template"`) |
| LLM failure, no verdicts | 503 | Couldn't generate an answer, please try again |
| Decision-model failure | 200 | Affected decision is UNKNOWN; `outcome: review` |
