# Task 03: Retrieval

**Day 1** · Refs: `docs/ai-design.md` §1–2

## Goal
Given a question and `org_id`, return the most relevant chunks with sources, or decide that nothing relevant exists.

## Checklist
- [ ] Vector search (pgvector cosine), filtered by `org_id`
- [ ] Keyword search (`tsvector`), filtered by `org_id`
- [ ] Reciprocal rank fusion
- [ ] Cross-encoder rerank, top ~5
- [ ] Groundedness gate with threshold in config
- [ ] Repository-level test: org A results never include org B chunks

## Done when
Test questions return the expected document and page in the top results; not-in-KB questions fall below the gate.
