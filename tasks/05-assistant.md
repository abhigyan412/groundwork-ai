# Task 05: Assistant API

**Day 2** · Refs: `docs/api-contracts.md`, `docs/security.md`

## Goal
The backend side of the assistant: tokens, the ask endpoint, and the admin endpoints the dashboard needs. The UI is in `tasks/06-frontend.md`.

## Checklist

### Token
- [x] Token generation, SHA-256 hash storage, regeneration with revocation
- [x] `GET /api/admin/assistant` and `POST /api/admin/assistant/regenerate` (URL + embed code)
- [x] `GET /api/public/assistant/{token}` (org name, suggested questions)

### Ask
- [x] `POST /api/ask`: token → `org_id` → full pipeline → response per contract
- [x] Log each question with route, outcome, answer, verdicts, references

### Admin data for the dashboard
- [x] `GET /api/admin/me`
- [x] `GET /api/admin/usage`
- [x] `GET /api/admin/questions`

### Contract
- [x] OpenAPI schema is clean and complete (frontend generates types from it)

## Done when
Every endpoint in `docs/api-contracts.md` works via the OpenAPI docs page, and an ask request returns a full answer with verdicts, references and timings.

## Notes
- **Code:**
  - `app/assistant/` (tokens, repository), `app/admin/assistant.py`, `app/admin/usage.py`, `app/public/routes.py` (public info, `/api/ask`), `app/questions/repository.py`
  - `/api/admin/me` was done in task 01.
- **Tokens:** `token_urlsafe(32)`, looked up by SHA-256 hash. A Fernet copy is used for re-display (ADR 0007). Regenerating revokes the old token in the same transaction.
- **`/api/ask`:**
  - Checks the token first (401), then the question (400), then the per-assistant rate limit (429). Then it runs the pipeline and logs the question with its LLM token usage.
  - An LLM failure with no verdicts → 503, still logged as `review`.
  - The DB connection is released while the pipeline runs.
- **OpenAPI:** operationId = route name (`ask`, `get_assistant`, `list_documents`, …) for the frontend's generated types. 14 operations.
- **Tests:** 24 in `tests/test_assistant_api.py`; 270 pass in total.
- **Done-when check:** an HTTP smoke test against the real models (fake LLM, since the Gemini daily quota was spent) covered every endpoint in `docs/api-contracts.md`:
  - a policy question returned a FALSE verdict with references and timings
  - a revoked token gets 401, and an assistant token on admin routes gets 401
  - the cross-org ask was refused and the cross-org delete got 404
