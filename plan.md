# Plan: AI Knowledge & Decision Assistant

Multi-tenant SaaS MVP: organizations upload PDFs, get an embeddable assistant, and visitors get grounded answers with page references. Multi-condition questions are decided by System 1 models, not by the LLM. The product should look and feel like a real commercial MVP.

This file is the execution blueprint: what we're building, in what order, and where the details live. The details themselves are in `docs/`, `tasks/` and `tests/`.

> Status markers used across all docs:
> **[Confirmed]** agreed during planning · **[Proposed]** recommended, not yet confirmed · **[Open]** still to decide

---

## Core principle

The LLM works only at the edges: it **decomposes** a question into structured decision specs, and it **composes** the final answer from verdicts and sources. Everything in between (classification, retrieval gating, Boolean/Choice/Score decisions, validation, combination) is done by System 1 models or plain application code.

Every answer shows its evidence: the frontend's signature element is the evidence trail under each answer.

---

## Document map

| File | Answers |
|---|---|
| `docs/requirements.md` | What must the product do? (from the assignment) |
| `docs/architecture.md` | How do the components fit together? |
| `docs/ai-design.md` | How do routing, decisions and answer generation work? |
| `docs/frontend.md` | What do the pages look like and how do they behave? |
| `docs/data-model.md` | What do we store, and how is it scoped by org? |
| `docs/api-contracts.md` | What does each endpoint accept and return? |
| `docs/security.md` | How are tenants isolated and credentials handled? |
| `docs/decisions/` | Why did we choose what we chose? (ADRs) |
| `tasks/01–07` | What to build, step by step, with checklists |
| `tests/evaluation.md` | How do we prove it works? |

---

## Execution order (~3 days) [Proposed]

| Order | Task file | When | Outcome |
|---|---|---|---|
| 1 | `tasks/01-foundation.md` | Day 1 | Repo, Docker, schema, auth |
| 2 | `tasks/02-knowledge-base.md` | Day 1 | Upload, limits, extraction, chunking, embeddings |
| 3 | `tasks/03-retrieval.md` | Day 1 | Hybrid search, rerank, groundedness gate |
| 4 | `tasks/04-decision-engine.md` | Day 2 (morning) | Classifier, router, decompose, validate, execute, combine |
| 5 | `tasks/05-assistant.md` | Day 2 (midday) | Tokens, `/api/ask`, admin endpoints for the dashboard |
| 6 | `tasks/06-frontend.md` | Day 2 (afternoon) – Day 3 (morning) | Landing, auth, dashboard, widget, evidence trail |
| 7 | `tasks/07-delivery.md` | Day 3 (afternoon) | Tests, test data, README, demo video |

The React frontend adds about half a day, which uses up the slack; the cut list matters more now.

**Cut first if time runs short:** landing page (go straight to sign up), usage side panel, live preview on the assistant page, rate limiting, NLI-based comparison (keep numeric comparison).

**Never cut:** the evidence trail, isolation tests, the multi-decision demo question.

---

## Open decisions

- [ ] Product name (working name: Groundwork)
- [ ] Answer composition: citation format and LLM guardrails
- [x] LLM provider: Anthropic Claude, `claude-opus-5-5` (Anthropic's recommended default; `LLM_MODEL` overrides). Embeddings: local `bge-small`, 384-dim
- [ ] Confirm the [Proposed] items in `docs/` before building

---

## Deliverables

- [ ] GitHub repo: backend, frontend, `.env.example`, schema, sample data, no secrets
- [ ] README (see `tasks/07-delivery.md`)
- [ ] Working end-to-end flow
- [ ] Demo video, 8–15 min
