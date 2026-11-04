# Architecture

## Components

```
 Embedded chat widget (iframe)          Org dashboard
   React route /a/:token              React app /app/*
            │                                 │
            └──────────── nginx (same origin) ┘
            │                                 │
            ▼                                 ▼
 ┌──────────────────────── FastAPI backend ────────────────────────┐
 │  Public API (assistant token)        Admin API (JWT)            │
 │            │                                 │                  │
 │            ▼                                 ▼                  │
 │  Ask pipeline                        Ingestion pipeline         │
 │  (router + decision engine)          (validate, extract,        │
 │                                       chunk, embed)             │
 └─────────────────────────────────────────────────────────────────┘
       │               │                          │
       ▼               ▼                          ▼
    LLM API     Postgres + pgvector         Private file store
                (all rows scoped by org_id)  (per-org folders)
```

Two credentials, two entry points, never mixed:

- **Admin flow:** login → JWT → manage documents, assistant token, usage.
- **Visitor flow:** `/a/:token` widget route → `POST /api/ask` with the assistant token.

nginx serves the React build and proxies `/api` and `/auth` to FastAPI, so the browser sees one origin and no CORS is needed. Frontend details: `docs/frontend.md`.

## Tech stack

| Layer | Choice | Status |
|---|---|---|
| Backend | Python + FastAPI | Confirmed |
| Database | Postgres 16 + pgvector, `tsvector` for keyword search; asyncpg with plain SQL | Confirmed |
| PDF extraction | PyMuPDF (page-level text) | Proposed |
| Embeddings | `BAAI/bge-small-en-v1.5` (local, 384-dim) | Confirmed (task 01 schema) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Proposed |
| NLI model (System 1) | `cross-encoder/nli-deberta-v3-small` | Proposed |
| Question classifier (System 1) | Logistic regression on embeddings | Proposed |
| LLM | Any provider behind `LLMClient` | Proposed |
| Frontend | React (Vite + TypeScript), Tailwind, shadcn/ui; see `frontend.md` | Confirmed |
| Deployment | Docker Compose: `db` (postgres), `api` (FastAPI), `web` (nginx serving React + proxying API) | Proposed |

## Ingestion flow [Proposed]

1. **Validate:** PDF magic bytes and parseable, ≤ 10 MB, ≤ 20 pages, org has < 10 documents.
2. **Store** privately at `storage/{org_id}/{document_id}.pdf`.
3. **Extract** text per page (PyMuPDF). Pages without text are flagged; OCR is out of scope.
4. **Chunk** within each page, ~400–500 tokens with small overlap; keep `document_id`, `filename`, `page`.
5. **Embed** and build `tsvector`.
6. **Mark** `ready`, or `failed` with the reason.

Steps 3–6 run as a FastAPI background task; the dashboard shows status.

## Ask flow

```
POST /api/ask {token, question}
  → validate token → org_id (server-side)
  → gather( classify(question), retrieve(question, org_id) )
  → groundedness gate ── fail → "not in knowledge base"
  → route by question type (see ai-design.md)
  → compose answer
  → { answer, outcome, references, route, verdicts, timings }
```

## Runtime notes

- Models load once in the FastAPI `lifespan` handler and live in `app.state`.
- CPU-bound inference runs in threads (`asyncio.to_thread`); torch releases the GIL, so parallel decisions are truly concurrent.
- The widget is a lazy-loaded React route at `/a/:token`, embedded via iframe; only this route may be framed.

## Project structure [Proposed]

```
app/
  main.py              # FastAPI app, lifespan model loading
  config.py            # settings + thresholds
  db/                  # models, schema.sql
  auth/                # register, login, JWT, token hashing
  admin/               # document, assistant, usage routes
  public/              # /api/public/assistant/{token}, /api/ask (the /a/:token page is a React route)
  ingestion/           # validate, extract, chunk, embed
  retrieval/           # hybrid search, RRF, rerank, gate
  engine/              # router, classifier, decompose, validate, executors, combine, compose
  llm/                 # LLMClient, provider impl, FakeLLMClient
frontend/              # React app: landing, dashboard, widget (see frontend.md)
demo/                  # external HTML pages
sample_data/           # PDFs + questions.json
scripts/               # train_classifier.py, seed_demo.py
tests/
docker-compose.yml
.env.example
README.md
```
