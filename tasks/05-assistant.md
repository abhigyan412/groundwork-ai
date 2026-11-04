# Task 05: Assistant API

**Day 2** · Refs: `docs/api-contracts.md`, `docs/security.md`

## Goal
The backend side of the assistant: tokens, the ask endpoint, and the admin endpoints the dashboard needs. The UI is in `tasks/06-frontend.md`.

## Checklist

### Token
- [ ] Token generation, SHA-256 hash storage, regeneration with revocation
- [ ] `GET /api/admin/assistant` and `POST /api/admin/assistant/regenerate` (URL + embed code)
- [ ] `GET /api/public/assistant/{token}` (org name, suggested questions)

### Ask
- [ ] `POST /api/ask`: token → `org_id` → full pipeline → response per contract
- [ ] Log each question with route, outcome, answer, verdicts, references

### Admin data for the dashboard
- [ ] `GET /api/admin/me`
- [ ] `GET /api/admin/usage`
- [ ] `GET /api/admin/questions`

### Contract
- [ ] OpenAPI schema is clean and complete (frontend generates types from it)

## Done when
Every endpoint in `docs/api-contracts.md` works via the OpenAPI docs page, and an ask request returns a full answer with verdicts, references and timings.
