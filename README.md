# Groundwork

**A multi-tenant AI knowledge and decision assistant.** Organizations upload their PDFs (policies, rules, handbooks), get an assistant link, and embed a chat widget on their own site. Visitors ask questions and get answers grounded only in *that* organization's documents, each with file and page references.

Groundwork goes further than retrieval-augmented chat. It also answers **decision questions** such as *"I'm in 2nd year, GPA 3.6, 80% attendance, no other scholarship. Am I eligible?"* It breaks them into individual checks, verifies each one against the document text, and combines the results with three-valued logic. The widget shows every check in a **"How this was answered"** panel.

> **Core principle: the LLM works only at the edges.** It turns the question into structured checks and writes the final sentence. Everything in between (classification, routing, the "is this in the documents?" gate, rule grounding, fact checks, comparisons and combining the results) is done by small local models ("System 1") and plain code. The LLM never produces a verdict.

---

## Contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start (Docker)](#quick-start-docker)
- [LLM providers](#llm-providers)
- [Local development and tests](#local-development-and-tests)
- [Architecture](#architecture)
- [Knowledge base pipeline](#knowledge-base-pipeline)
- [AI architecture](#ai-architecture)
- [Security and tenant isolation](#security-and-tenant-isolation)
- [API endpoints](#api-endpoints)
- [Sample data and evaluation](#sample-data-and-evaluation)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Production improvements](#production-improvements)
- [Design decisions](#design-decisions)

---

## Features

**For organizations (dashboard)**
- Register, log in, and manage an isolated knowledge base
- Upload, replace and delete PDFs (max 10 PDFs, 20 pages and 10 MB each, with clear validation errors)
- See per-document processing status (`processing`, `ready`, `failed` with the reason)
- Generate or regenerate the assistant link. Regenerating revokes the old link immediately
- Copy embed code (iframe or JavaScript chat button)
- Usage stats and a log of recent visitor questions with their outcomes

**For visitors (embedded widget)**
- No login. Open the link or use the widget on the org's site
- Suggested starter questions, built from the org's document headings
- Answers with `filename, page N` references. PDFs themselves are never exposed
- A "How this was answered" panel with the route taken, each check and its verdict, the rule as written in the document, and timings

**Question types handled**

| Type | Example | How it's answered |
|---|---|---|
| Direct | *What time is the hostel curfew?* | Grounded answer |
| Procedural | *How do I apply for the merit scholarship?* | Grounded answer, steps kept in order |
| Policy (yes/no) | *Can unused casual leave be carried forward?* | Pattern-built hypothesis, then NLI against the top chunks |
| Multi-condition decision | *I joined 8 months ago. Can I work from home 3 days a week?* | Decompose, validate and ground, parallel checks, three-valued combine |
| Comparison | *Which hostel block is cheaper, A or B?* | Values extracted per option, then compared by code |
| Not in knowledge base | *What's on the canteen menu?* | Stopped at the groundedness gate, no LLM call |

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, asyncpg (plain SQL) |
| Database | PostgreSQL 16 + pgvector (HNSW) + `tsvector` keyword search |
| PDF extraction | PyMuPDF |
| Embeddings | `BAAI/bge-small-en-v1.5` (local, 384-dim) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| NLI (System 1) | `cross-encoder/nli-deberta-v3-small` |
| Question classifier | Logistic regression on bge embeddings (scikit-learn) |
| LLM | Google Gemini (demo default) or Anthropic Claude, behind one `LLMClient` interface |
| Auth | Argon2id passwords, HS256 JWT; hashed and Fernet-encrypted assistant tokens |
| Frontend | React + Vite + TypeScript (strict), Tailwind, shadcn/ui, TanStack Query, React Router |
| Deployment | Docker Compose: `db` (Postgres), `api` (FastAPI), `web` (nginx serving React and proxying the API) |

---

## Quick start (Docker)

**Prerequisites:** Docker Desktop. Python 3.11+ only to generate secrets.

**Memory:** the full stack needs about **4 GB of free memory**. That covers Postgres plus the three local models the API loads at startup. On an 8 GB machine, close browsers and other heavy apps first. If startup fails with *"The paging file is too small"* (Windows) or the process is killed, it ran out of memory.

```bash
git clone <this-repo-url>
cd groundwork
cp .env.example .env
```

Fill in the required values in `.env`:

```bash
# JWT_SECRET (at least 32 chars)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# ASSISTANT_TOKEN_KEY (Fernet key)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# LLM_API_KEY: a free Gemini key from https://aistudio.google.com/apikey
# (or set LLM_PROVIDER=fake to run without any key)
```

Start everything:

```bash
docker compose up -d --build
curl localhost:8000/health
```

| Service | URL |
|---|---|
| Web app (dashboard and widget) | http://localhost:8080 |
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |
| Postgres | `localhost:5433` |

> The first start downloads about **700 MB of model weights** into a Docker volume, which can take several minutes. Later starts load from the cache in about 20 s.

**Try it:** register at http://localhost:8080, upload the PDFs from [`sample_data/riverside/`](sample_data/riverside) or [`sample_data/northwind/`](sample_data/northwind), wait for them to show as *ready*, then open the assistant link from the **Assistant** page.

**Embed demo:** the pages in [`demo/`](demo) embed the widget from a different origin:

```bash
python -m http.server 8090 -d demo
# http://localhost:8090/university.html?assistant=<assistant link from the Assistant page>
# company.html  -> iframe embed
# js-embed.html -> floating chat-button embed
```

### Environment variables

All configuration goes through `.env`. See [`.env.example`](.env.example) for the full, commented list.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` / `TEST_DATABASE_URL` | Postgres connection. The test DB name must end in `_test`, because the tests truncate it |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | Admin authentication |
| `ASSISTANT_TOKEN_KEY` | Fernet key for the encrypted copy of the assistant token |
| `PUBLIC_BASE_URL` | Base for assistant links (`{PUBLIC_BASE_URL}/a/{token}`) |
| `STORAGE_DIR` | Private PDF storage |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | LLM selection (see below) |
| `LLM_EFFORT_DECOMPOSE`, `LLM_EFFORT_COMPOSE` | Thinking depth per step |
| `MODEL_BACKEND`, `EMBEDDING_MODEL`, `RERANKER_MODEL`, `NLI_MODEL` | Local System 1 models |

---

## LLM providers

Set `LLM_PROVIDER` in `.env`:

| Provider | `LLM_PROVIDER` | Default model (`LLM_MODEL` empty) | Notes |
|---|---|---|---|
| Google Gemini | `gemini` (**demo default**) | `gemini-3.6-flash` | Free-tier key from Google AI Studio. The free tier allows about 5–10 requests per minute, and 429s are retried with backoff. A decision question uses 2–3 LLM calls. |
| Anthropic Claude | `anthropic` | `claude-sonnet-5-5` | Set `claude-opus-5-5` via `LLM_MODEL`. Requires API credits. |
| None | `fake` | n/a | No network. No decisions; answers are extracted from the documents. Used by the tests. |

Put the key in `LLM_API_KEY` (or the SDK's own `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`). `.env` is git-ignored; never commit it.

---

## Local development and tests

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use: source .venv/bin/activate on macOS/Linux
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch first
pip install -e ".[dev]"

docker compose up -d db           # tests use the groundwork_test database on port 5433
pytest
ruff check . && ruff format --check .
uvicorn app.main:app --reload     # API against the compose db (DATABASE_URL in .env)
```

Tests use `FakeLLMClient` and make no real API calls. Tests that need the real NLI model are opt-in:

```bash
RUN_MODEL_TESTS=1 pytest tests/test_rule_check_real.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxies /api and /auth to the API on :8000
npm run build    # strict type-check and production build
```

After changing an API route or model, regenerate the typed client: run `python scripts/export_openapi.py` (repo root), then `npm run gen:api` (in `frontend/`). API types are generated from the OpenAPI schema, never hand-written.

---

## Architecture

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

There are two credentials and two entry points, never mixed:

- **Admin flow:** log in, receive a JWT, then manage documents, the assistant link and usage.
- **Visitor flow:** the `/a/:token` widget calls `POST /api/ask` with the assistant token.

nginx serves the React build and proxies `/api` and `/auth` to FastAPI, so the browser sees a single origin and no CORS setup is needed. Models load once in FastAPI's `lifespan` handler. CPU-bound inference runs in threads via `asyncio.to_thread`, and because torch releases the GIL, independent checks really run in parallel.

**Frontend:** one React app with three areas: a landing page, the org dashboard (`/app/*`: documents, assistant link and embed code, usage) and the lazy-loaded widget route (`/a/:token`). The widget never imports dashboard code. IBM Plex Serif is reserved for text quoted from the organization's documents, so a visitor can always tell document text from generated text.

### Ask flow

```
POST /api/ask {token, question}
  → validate token → org_id (server-side, never from the request)
  → in parallel: classify(question) ‖ retrieve(question, org_id)
  → groundedness gate ── fails → "The documents for {org} don't cover this."
  → route by question type
  → System 1 checks (parallel) → three-valued combine
  → compose() writes the answer from the verdicts
  → { answer, outcome, references, route, verdicts, timings_ms, overall, confidence }
```

---

## Knowledge base pipeline

1. **Validate:** fewer than 10 non-failed documents per org (checked again under a per-org row lock), at most 10 MB (read with a cap), a PDF header, parseable, not password-protected, 1–20 pages.
2. **Store privately** at `storage/{org_id}/{document_id}.pdf`. The path is built only from UUIDs, and the write is atomic.
3. **Extract** text page by page with PyMuPDF, one block at a time. Each paragraph, list item or table row becomes one line. Hyphenation is undone and text is NFKC-normalized (so the ligature "ﬃ" becomes "ffi"). Pages with no text are reported. A PDF with no text at all fails with a clear reason.
4. **Chunk** within each page: lines are packed up to 450 tokens with a 50-token overlap. Lines that are too long are split by sentence, then by word. Line breaks are kept so numbered steps stay in order. Because chunks never cross pages, **every chunk maps to exactly one page**, which is what makes page references exact.
5. **Embed** with bge-small (L2-normalized). The `tsvector` is a generated column.
6. **Commit** chunks and mark the document `ready` in one transaction, but only if the document wasn't deleted or replaced in the meantime.

Ingestion runs as background asyncio tasks (at most 2 documents at once). Documents left `processing` by a restart resume on startup.

### Retrieval

- **Hybrid search:** pgvector cosine search (HNSW with iterative scan, so the `org_id` filter can't starve small orgs) plus Postgres full-text search. Each returns 20 candidates, and the two lists are merged with **reciprocal rank fusion** (k = 60).
- **Rerank** the fused top 20 with the cross-encoder and keep the top 5.
- Always filtered by the `org_id` from the validated token, over `ready` documents only.
- **Page references** (`filename, page N`) are attached by code from the chunks and verdict sources. The LLM can't cite a page it wasn't given.

---

## AI architecture

### Where the LLM is used, and where it isn't

| Step | Done by |
|---|---|
| Question classification (5 types) | **System 1:** logistic regression on bge embeddings |
| "Is this in the documents?" gate | **System 1:** reranker score threshold |
| Routing | **Code** |
| Turning a question into checks | **LLM:** `decompose()`, `decompose_comparison()`, `extract_comparison_values()` |
| Validating the plan (schema, cited chunk, numbers present) | **Code** (Pydantic + checks) |
| Verifying each rule exists in the document | **System 1:** NLI entailment ≥ 0.7 |
| Fact checks (`gpa >= 3.5`) | **Code:** typed comparator |
| Policy conditions | **System 1:** NLI |
| Comparisons | **Code** over extracted, verified numbers (NLI score as fallback) |
| Combining results | **Code:** three-valued logic |
| Writing the answer | **LLM:** `compose()`, which may only phrase the given verdicts |

### Decomposition

For a decision question, the LLM returns a typed plan. Every check cites a retrieved chunk and quotes the rule **as written**:

```json
{
  "user_facts": {
    "year":           { "type": "number", "value": 2 },
    "gpa":            { "type": "number", "value": 3.6 },
    "attendance_pct": { "type": "number", "value": 80 }
  },
  "decisions": [
    { "id": "d1", "check": "fact", "fact": "gpa", "op": ">=", "value": 3.5,
      "source_chunk": "c12", "label": "GPA at least 3.5",
      "rule": "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale." }
  ],
  "combine": "ALL"
}
```

Rules are extracted **at question time** from the retrieved chunks, so there is no separate rule-compilation step at upload.

### Validation and rule grounding

1. **Schema:** Pydantic with a discriminated union (`fact` or `nli`). Operators are restricted by fact type.
2. **Semantic checks (code):** every cited chunk was really retrieved for this org in this request, and every threshold number appears in the cited chunk's text after normalization (`"₹45,000"` becomes 45000, `"75%"` becomes 75).
3. **Rule grounding (NLI):** the cited chunk's *anchor sentence* (the one closest in wording to the rule) must entail the rule with probability ≥ 0.7, or the check is dropped. NLI proves the rule exists; code decides whether the user meets it. Using an anchor sentence instead of the whole chunk raised valid-rule acceptance from 3/10 to 9/10 and rejected 11/11 bad rules.
4. **One retry** with the errors fed back to the LLM. If nothing valid survives, the question gets a grounded answer flagged `review`.

### Combination (three-valued logic)

| Rule | FALSE if | UNKNOWN if | TRUE if |
|---|---|---|---|
| ALL | any check is FALSE | none FALSE, any UNKNOWN | all TRUE |
| ANY | all checks FALSE | none TRUE, any UNKNOWN | any TRUE |

**Outcomes:**
- `answered`: decided. If some facts were missing but the result is still decided (one condition already fails), the answer notes what wasn't given.
- `needs_info`: undecided only because the visitor left facts out. The answer asks for them.
- `review`: undecided because of a model failure, a timeout or an unclear document.
- `unanswered`: stopped at the groundedness gate.

### Groundedness gate

If the top reranker score is below the route's threshold, the assistant replies that the documents don't cover the question and **no LLM call is made**. Decision questions get a looser threshold (−5.0 vs 0.0), because personal facts in the question lower the match score. The looser threshold applies only when the classifier is confident the question is a decision question. Thresholds were tuned on 18 labelled questions (18/18 correct). All thresholds live in [`app/config.py`](app/config.py).

### Why this design

- **Correctness is checkable.** Each verdict is traceable to a rule sentence on a specific page and a deterministic comparison.
- **No hallucinated decisions.** An LLM can phrase a wrong answer convincingly; here it only phrases verdicts that code and NLI have already decided.
- **Graceful degradation.** If the LLM is down, decision questions still get a code-built template answer from the verdicts. Model failures surface as `review`, never as a guess.
- **Prompt-injection guard.** Document text is passed inside `<document>` tags with an explicit instruction that it is data, never instructions.

---

## Security and tenant isolation

- **`org_id` always comes from a validated credential** (JWT or assistant token), never from the request body or query string. Extra fields such as `org_id` in a request are ignored.
- **Every query** on `documents`, `chunks` and `questions` filters by `org_id`.
- **Separate credentials:** admin routes accept only the JWT, and public routes accept only the assistant token. An assistant token can never reach an admin route.
- **Assistant tokens:** generated with `secrets.token_urlsafe(32)` and looked up **only by SHA-256 hash**. A Fernet-encrypted copy lets the owner's dashboard show the link again; it is decrypted only behind the admin JWT. Regenerating revokes the old token immediately. The token reveals nothing about the org.
- **Passwords:** Argon2id. Login checks against a dummy hash for unknown emails, so response timing doesn't reveal which emails are registered.
- **JWT:** HS256 with the algorithm pinned on decode. User and org are re-checked against the database on every request, so a deleted account loses access immediately.
- **Documents are never publicly served.** Visitors see the filename and page number only.
- **Clickjacking:** only `/a/*` (the widget) can be framed. Every other route sends `frame-ancestors 'none'`.
- **Rate limit:** 20 questions per minute per assistant on `/api/ask`, which also protects the LLM quota.
- **No secrets in the repo:** everything goes through `.env`.

Isolation is covered by tests: one org's question about another org's documents (for example, the company asking about the university's merit scholarship) is stopped at the gate.

---

## API endpoints

Full contracts are in [`docs/api-contracts.md`](docs/api-contracts.md), and interactive docs are at `/docs`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | none | Create an org and its admin user |
| `POST` | `/auth/login` | none | Get a JWT |
| `GET` | `/api/admin/me` | JWT | Current user and org |
| `GET` | `/api/admin/documents` | JWT | List documents with status |
| `POST` | `/api/admin/documents` | JWT | Upload a PDF (`202`, processed in the background) |
| `PUT` | `/api/admin/documents/{id}` | JWT | Replace a document |
| `DELETE` | `/api/admin/documents/{id}` | JWT | Delete a document, its file and its chunks |
| `GET` | `/api/admin/assistant` | JWT | Assistant link and embed code |
| `POST` | `/api/admin/assistant/regenerate` | JWT | New link; the old one is revoked |
| `GET` | `/api/admin/usage` | JWT | Usage stats |
| `GET` | `/api/admin/questions` | JWT | Recent visitor questions and outcomes |
| `GET` | `/api/public/assistant/{token}` | Assistant token | Org name and suggested questions |
| `POST` | `/api/ask` | Assistant token | Ask a question |
| `GET` | `/health` | none | Health check |

<details>
<summary>Example <code>POST /api/ask</code> response</summary>

```json
{
  "answer": "Yes, you meet all four conditions for the merit scholarship ...",
  "outcome": "answered",
  "references": [{ "file": "Scholarship_Rules.pdf", "page": 4 }],
  "route": "decision",
  "verdicts": [{
    "id": "d1", "kind": "fact", "label": "GPA at least 3.5",
    "rule": "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.",
    "value": "TRUE", "confidence": 1.0, "user_value": 3.6, "missing_fact": null,
    "source": { "file": "Scholarship_Rules.pdf", "page": 4, "excerpt": "Applicants must hold..." },
    "reason": null
  }],
  "timings_ms": { "retrieve": 120, "classify": 8, "decompose": 2100, "grounding": 160,
                  "decisions": { "d1": 1, "d2": 1, "d3": 140 }, "compose": 900, "total": 3300 },
  "overall": "TRUE",
  "confidence": 1.0,
  "answer_source": "llm"
}
```
</details>

---

## Sample data and evaluation

[`sample_data/`](sample_data) contains two demo organizations:

| Org | Documents |
|---|---|
| **Riverside** (university) | `Exam_Regulations.pdf`, `Hostel_Policy.pdf`, `Scholarship_Rules.pdf` |
| **Northwind** (company) | `Leave_Policy.pdf`, `Travel_Policy.pdf`, `WFH_Policy.pdf` |

[`sample_data/questions.json`](sample_data/questions.json) holds 18 labelled test questions covering every question type, near-miss "not in KB" questions and a cross-org isolation case. See [`tests/evaluation.md`](tests/evaluation.md) for expected results.

| Script | Purpose |
|---|---|
| `scripts/make_sample_pdfs.py` | Regenerate the sample PDFs |
| `scripts/train_classifier.py` | Train the question classifier (`models/question_classifier.joblib`) |
| `scripts/eval_retrieval.py` | Retrieval and gate evaluation with the real models (last run: **18/18**) |
| `scripts/eval_engine.py` | End-to-end decision-engine evaluation |
| `scripts/export_openapi.py` | Export the OpenAPI schema for frontend type generation |

---

## Project structure

```
app/
  main.py          FastAPI app; models load once in lifespan
  config.py        Settings and every threshold
  auth/            Register, login, JWT, password hashing
  admin/           Document, assistant-link and usage routes (JWT)
  public/          /api/public/assistant/{token}, /api/ask (assistant token)
  ingestion/       Validate, extract, chunk, embed, store
  retrieval/       Hybrid search, RRF, rerank
  engine/          Pipeline, routing, spec validation, executors, combine, comparison, policy
  ml/              Embedder, reranker, NLI, question classifier
  llm/             LLMClient protocol, Gemini / Anthropic / Fake clients, prompts, retry
  assistant/       Token handling, suggested questions
  db/              Connection pool, schema.sql
frontend/          React app: landing, dashboard, widget
demo/              External pages that embed the widget
docs/              Architecture, AI design, API contracts, security, ADRs
sample_data/       Demo PDFs, labelled questions, classifier training data
scripts/           Training, evaluation and tooling
tests/             pytest suite (isolation, engine, ingestion, retrieval, API)
```

---

## Known limitations

- **No OCR:** scanned, image-only PDFs are rejected with a clear message.
- **Numbers written as words** ("six months") aren't recognized by the number validator. The sample PDFs use digits.
- **Rule grounding proves the rule's text exists** in the document, not that the LLM turned it into exactly the right check (e.g. the right operator). An evaluation against reference plans covers this.
- **Rules are extracted per question.** That adds an LLM call to every decision question, and results can vary slightly between runs.
- **The Gemini free tier is rate-limited** (about 5–10 requests per minute). Busy demos may see retries and slower answers.
- **One user per organization.** No roles yet.
- **In-process background tasks and rate limiter.** Neither is shared across multiple API processes.
- **The JWT is stored in `localStorage`** (MVP). Production should use an httpOnly SameSite cookie.
- **Memory footprint:** about 4 GB, because three local models are loaded in the API process.

## Production improvements

- Compile rules at upload time into a structured rule store, so decision questions need fewer LLM calls and give consistent results
- Multiple users per org with roles (owner, editor, viewer)
- OCR for scanned PDFs
- Object storage (S3/GCS) with signed URLs
- Postgres row-level security as a second isolation layer
- A job queue (e.g. Celery/RQ or Arq) instead of in-process background tasks, and Redis for rate limiting
- An evaluation harness with regression tracking in CI
- A human-review queue for `review` and `unanswered` questions, so admins can close gaps in their documents
- httpOnly cookie sessions for the dashboard

---

