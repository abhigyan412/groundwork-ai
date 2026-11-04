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
