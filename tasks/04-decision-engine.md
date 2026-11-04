# Task 04: Decision Engine

**Day 2** · Refs: `docs/ai-design.md` §3–15, `docs/decisions/0002–0005`, `0008–0010`

## Goal
Route each question; run structured decisions with System 1 models in parallel; combine results.

## Checklist

### Classifier and router
- [x] Label 60–80 example questions (`sample_data/classifier_examples.json`)
- [ ] `scripts/train_classifier.py` → `.joblib`
- [x] Router with low-confidence fallback to decision path
- [x] Apply the per-route groundedness gate (`passes_gate`) after `gather(classify, retrieve)`
- [ ] Re-run `scripts/eval_retrieval.py` with the classifier's *predicted* routes; confirm near misses (Q15–18) aren't misrouted to decision (Q17 would leak)

### LLM client
- [x] `LLMClient` protocol (`decompose`, `decompose_comparison`, `extract_comparison_values`, `compose`), Anthropic implementation
- [x] `FakeLLMClient` for tests
- [x] `decompose()` prompt producing the decision spec JSON

### Validation
- [x] Pydantic models for the decision plan: typed facts (number/boolean/string), `fact` | `nli` checks, `rule` + `label` on every decision
- [x] Number normalization ("75%" → 75, "₹45,000" → 45000)
- [x] Semantic checks: chunk retrieved, value in chunk text, fact type matches, op allowed for type
- [x] Rule grounding: NLI entailment of `rule` by cited chunk ≥ 0.7, else drop (ADR 0008)
- [x] One retry with errors, then fallback

### Executors
- [x] Fact comparator (number/boolean/string; missing → UNKNOWN)
- [x] NLI Boolean (entail/contradict thresholds)
- [x] NLI Score (comparison fallback)
- [x] Parallel execution with per-decision timeout; failure → UNKNOWN

### Paths
- [x] Policy path: pattern hypotheses (ADR 0010) → NLI on top 3 chunks → strongest decisive verdict; no match → decision path
- [x] Comparison path (ADR 0009): `decompose_comparison` → per-option retrieval → `extract_comparison_values` → validate → code compare; NLI Score + Choice fallback
- [x] Decision path: decompose → validate → execute → combine

### Combiner and composer
- [x] ALL/ANY three-valued logic, min confidence
- [x] `needs_info` only when overall UNKNOWN from missing facts; decided results still note missing facts
- [x] `compose()` with citations, using only verdicts + chunks

## Done when
Unit tests for combiner, validator, normalization, policy patterns and comparison pass; test questions 3, 4, 5, 6, 10, 11 and 12 produce the expected verdicts.

## Status
- Built and verified with fake models and a scripted LLM: 214 tests pass, including `tests/test_pipeline.py` (test questions 4, 5 and 10 end to end, every path, all LLM-failure fallbacks) and `tests/test_engine_units.py` (combiner over all 27 three-value combinations per rule, validator, normalization, policy patterns, comparison, executor timeout).
- **Still open (real models):** `scripts/eval_engine.py` runs the 18 questions through the pipeline with the real classifier, NLI and rule grounding (and Claude once `LLM_PROVIDER=anthropic`). It couldn't run yet because the dev machine ran out of memory loading the models. It also covers the two open items above: training the classifier with real embeddings, and the predicted-route check for Q15–18.
- LLM: `claude-opus-5-5` via `app/llm/anthropic_client.py`. It has not been called yet (no API key); `LLM_PROVIDER=fake` until then.
