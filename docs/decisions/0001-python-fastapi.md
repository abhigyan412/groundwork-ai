# 0001: Python + FastAPI backend

**Status:** Accepted

## Context
The system needs local ML models (NLI, reranker, classifier), PDF processing, and an async API with parallel decision execution.

## Decision
Python with FastAPI.

## Consequences
- Direct access to sentence-transformers, scikit-learn and PyMuPDF.
- Async handlers plus `asyncio.to_thread` give real parallelism for model inference.
- Pydantic models double as API schemas and decision-spec validation.
