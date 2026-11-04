# CLAUDE.md

Guidance for AI coding assistants working in this repo.

## What this project is

A multi-tenant AI Knowledge & Decision Assistant (take-home assignment). Organizations upload PDFs; visitors ask questions through an embedded widget; answers are grounded in that organization's documents with page references. The graded core is the separation between the LLM and System 1 decision models.

## Read before writing code

1. `plan.md`: scope, execution order, open decisions
2. The task file you're working on in `tasks/`
3. The `docs/` files that task references
4. `docs/decisions/` before changing any design choice

## Non-negotiable rules

- **The LLM is only used in the decompose step (`decompose()`, `decompose_comparison()`, `extract_comparison_values()`) and `compose()`.** Never use it to classify, route, ground a rule, make a decision, compare, or combine results. Those belong to System 1 models or plain code.
- **`org_id` always comes from a validated credential** (JWT or assistant token), never from the request body or query string.
- **Every query on `documents`, `chunks` or `questions` filters by `org_id`.** No exceptions, including in scripts and tests.
- **Admin routes accept only the JWT. Public routes accept only the assistant token.**
- **Look up assistant tokens only by hash.** The plain token is never stored unencrypted; an encrypted copy exists only so the owner's dashboard can show the link again (ADR 0007).
- **PDFs are never publicly served.** Visitors see filename and page number only.
- **Only `/a/*` may be framed.** Every other route sends `frame-ancestors 'none'`.
- **The LLM must not invent or change verdicts.** `compose()` uses only the verdicts and chunks it is given.
- **No secrets in the repo.** Everything goes through `.env`; keep `.env.example` updated.

## Conventions

### Backend
- Python 3.11+, FastAPI, Pydantic v2, async route handlers, type hints everywhere.
- CPU-bound model inference runs via `asyncio.to_thread`; models load once in the FastAPI `lifespan` handler.
- All thresholds live in `app/config.py`, not inline.
- Errors returned to users are specific and friendly (see `docs/api-contracts.md`).
- Tests use pytest and `FakeLLMClient`; no real API calls in tests.
- Lint/format with ruff.

### Frontend (`frontend/`, see `docs/frontend.md`)
- Vite + React + TypeScript (strict), Tailwind, restyled shadcn/ui, TanStack Query, React Router, react-hook-form + zod.
- Use only the design tokens in `docs/frontend.md` §4; never Tailwind's default palette in components.
- Serif (IBM Plex Serif) is reserved for text that comes from the organization's documents.
- API types are generated from the backend's OpenAPI schema; don't hand-write response types.
- Every data view has loading, empty and error states.
- Copy follows `docs/frontend.md` §8: plain words, sentence case, specific errors.
- The widget route stays lazy-loaded and must not import dashboard code.

## Workflow

- Work one task file at a time; tick checkboxes as items are completed.
- Don't change a [Confirmed] decision without adding an ADR in `docs/decisions/`.
- If something in a doc is wrong or missing, update the doc in the same change.
- Run `pytest` before considering a task done.
