# Groundwork

Multi-tenant AI knowledge and decision assistant. See `plan.md` and `docs/`. The full README comes in task 07.

## Run locally

Prerequisites: Docker Desktop and Python 3.11+.

**Memory:** the full stack needs about **4 GB of free memory**. That covers Postgres in Docker plus the three local models the API loads at startup (bge-small embeddings, the MiniLM reranker, the DeBERTa NLI model), with some headroom. On a machine with 8 GB of RAM, close browsers and other heavy apps before starting. If startup fails with "The paging file is too small" (Windows) or the process is killed, memory ran out.

```bash
cp .env.example .env
# Fill in JWT_SECRET and ASSISTANT_TOKEN_KEY (generation commands are in .env.example)

docker compose up -d --build   # db on localhost:5433, api on localhost:8000
curl localhost:8000/health
```

API docs: http://localhost:8000/docs

## LLM providers

The LLM is used only to break questions into checkable conditions and to write the final answer; every decision is made by local models and code. Set `LLM_PROVIDER` in `.env`:

| Provider | `LLM_PROVIDER` | Default model (`LLM_MODEL` empty) | Notes |
|---|---|---|---|
| Google Gemini | `gemini` (**demo default**) | `gemini-3.6-flash` | Free-tier key from Google AI Studio. Free tier allows ~5–10 requests/minute; 429s are retried with backoff. A decision question uses 2–3 LLM calls. |
| Anthropic Claude | `anthropic` | `claude-sonnet-5-5` | `claude-opus-5-5` via `LLM_MODEL`. Requires API credits. |
| None | `fake` | n/a | No network. No decisions; answers are extracted from the documents. Used by the tests. |

Put the key in `LLM_API_KEY` (or the SDK's own `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`). `.env` is git-ignored; never commit it.

## Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /api and /auth to the API on :8000
npm run build        # strict type-check + production build
```

After changing an API route or model, regenerate the types: `python scripts/export_openapi.py` (repo root), then `npm run gen:api` (in `frontend/`).

With Docker, `docker compose up -d --build` also starts `web` (nginx) on http://localhost:8080. It serves the app and proxies the API. Only `/a/*` (the widget) can be framed; every other page sends `frame-ancestors 'none'`.

**Demo pages** (`demo/`) embed the widget from another origin:

```bash
python -m http.server 8090 -d demo
# http://localhost:8090/university.html?assistant=<assistant link from the Assistant page>
# company.html (iframe embed), js-embed.html (chat-button embed)
```

## Develop and test

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

docker compose up -d db         # tests use the groundwork_test database on port 5433
pytest
ruff check . && ruff format --check .
uvicorn app.main:app --reload   # API against the compose db (DATABASE_URL in .env)
```
