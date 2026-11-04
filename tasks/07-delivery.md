# Task 07: Delivery

**Day 3 (afternoon)** · Refs: `tests/evaluation.md`, `docs/requirements.md` (submission)

## Checklist

### Tests
- [ ] All isolation tests in `tests/evaluation.md` pass
- [ ] Combiner, validator and limit tests pass
- [ ] Run all test questions; tune groundedness gate; record results

### Sample data
- [ ] `sample_data/` with 6 PDFs and `questions.json`
- [ ] `scripts/seed_demo.py` creates both orgs and uploads PDFs

### README
- [ ] Setup: prerequisites, install, env vars, run commands
- [ ] Architecture: diagram, components, data flow, API flow, frontend overview
- [ ] Knowledge base: processing, chunking, retrieval, page references
- [ ] AI architecture: LLM use, System 1 use, decomposition, combination, rationale
- [ ] Security: isolation, token handling, auth, document access
- [ ] Major endpoints
- [ ] Known limitations and production improvements

### Demo video (8–15 min)
1. Problem and core principle (1 min)
2. Architecture walkthrough (3 min)
3. Register, upload, assistant URL, embed (2 min)
4. Question types, including the multi-decision question with the "How this was answered" panel (4 min)
5. Two orgs, isolation demo (2 min)
6. Limitations and production improvements (1 min)

### Final checks
- [ ] No secrets in git history
- [ ] Fresh clone + README steps works end to end

## Production improvements (for README)
- Compile rules at upload into a structured rule store
- Multiple users per org with roles
- OCR for scanned PDFs
- Object storage with signed URLs
- Postgres row-level security
- Job queue instead of background tasks
- Evaluation harness with regression tracking
- Human-review queue for `review` / `unanswered` questions
