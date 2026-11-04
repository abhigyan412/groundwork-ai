# Task 04: Decision Engine

**Day 2** · Refs: `docs/ai-design.md` §3–12, `docs/decisions/0002–0005`

## Goal
Route each question; run structured decisions with System 1 models in parallel; combine results.

## Checklist

### Classifier and router
- [ ] Label 60–80 example questions (`sample_data/classifier_examples.json`)
- [ ] `scripts/train_classifier.py` → `.joblib`
- [ ] Router with low-confidence fallback to decision path

### LLM client
- [ ] `LLMClient` protocol, one provider implementation
- [ ] `FakeLLMClient` for tests
- [ ] `decompose()` prompt producing the decision spec JSON

### Validation
- [ ] Pydantic models for the decision plan
- [ ] Semantic checks: chunk retrieved, threshold in chunk text, fact present or missing, op whitelist
- [ ] One retry with errors, then fallback

### Executors
- [ ] Numeric comparator
- [ ] NLI Boolean (entail/contradict thresholds)
- [ ] NLI Choice (zero-shot)
- [ ] NLI Score
- [ ] Parallel execution with per-decision timeout; failure → UNKNOWN

### Paths
- [ ] Policy path: template hypothesis → NLI Boolean
- [ ] Comparison path: per-option retrieval → Score → Choice (numeric compare when possible)
- [ ] Decision path: decompose → validate → execute → combine

### Combiner and composer
- [ ] ALL/ANY three-valued logic, min confidence
- [ ] `needs_info` outcome for missing facts
- [ ] `compose()` with citations, using only verdicts + chunks

## Done when
Unit tests for combiner and validator pass; test questions 4, 5 and 10 produce correct verdicts.
