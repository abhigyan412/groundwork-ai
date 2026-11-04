# Task 01: Foundation

**Day 1** · Refs: `docs/architecture.md`, `docs/data-model.md`, `docs/security.md`

## Goal
A running FastAPI app with Postgres, schema, and working register/login.

## Checklist
- [x] Repo layout per `docs/architecture.md`
- [x] `docker-compose.yml`: `pgvector/pgvector` Postgres + app
- [x] `.env.example` (DB URL, JWT secret, LLM provider/key, storage path)
- [x] `app/config.py` with settings and thresholds
- [x] `schema.sql` or migrations for all tables in `docs/data-model.md`
- [x] `POST /auth/register` creates org + user
- [x] `POST /auth/login` returns JWT
- [x] `get_current_org` dependency that resolves `org_id` from the JWT
- [x] Password hashing
- [x] Health check route

## Done when
Register → login → call a protected route that returns the org name.

## Notes
- Schema: `app/db/schema.sql`, applied idempotently on startup (no migration tool).
- Compose `db` is on host port 5433 to avoid a local Postgres on 5432. The `api` service is included; `web` arrives in task 06.
- `GET /api/admin/me` is the protected route for the done-when check.
- Tests: `tests/test_auth.py`, `tests/test_health.py` (26 tests) against the `groundwork_test` database.
