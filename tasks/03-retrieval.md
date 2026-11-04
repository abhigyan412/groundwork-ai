# Task 03: Retrieval

**Day 1** · Refs: `docs/ai-design.md` §1–2

## Goal
Given a question and `org_id`, return the most relevant chunks with sources, or decide that nothing relevant exists.

## Checklist
- [x] Vector search (pgvector cosine), filtered by `org_id`
- [x] Keyword search (`tsvector`), filtered by `org_id`
- [x] Reciprocal rank fusion
- [x] Cross-encoder rerank, top ~5
- [x] Groundedness gate with threshold in config
- [x] Repository-level test: org A results never include org B chunks

## Done when
Test questions return the expected document and page in the top results; not-in-KB questions fall below the gate.

## Notes
- Code: `app/retrieval/{repository,search}.py`, `app/ml/reranker.py`. No HTTP endpoint yet; `/api/ask` (task 05) calls `retrieve()`.
- Gate is per route (`passes_gate(result, settings, route)`): 0.0 for direct/procedural/policy/comparison, −5.0 for decision. See `docs/ai-design.md` §2 for the evidence.
- `scripts/eval_retrieval.py`: 18/18 with real models, including 4 near-miss not-in-KB questions added to `sample_data/questions.json`.
- Tests: `tests/test_retrieval.py` (fake models), including org isolation at the repository level and a small org next to a large one.
