# Task 04: Decision Engine

**Day 2** · Refs: `docs/ai-design.md` §3–15, `docs/decisions/0002–0005`, `0008–0010`

## Goal
Route each question; run structured decisions with System 1 models in parallel; combine results.

## Checklist

### Classifier and router
- [x] Label 60–80 example questions (`sample_data/classifier_examples.json`)
- [x] `scripts/train_classifier.py` → `.joblib` (C = 64; also auto-trained at startup)
- [x] Router with low-confidence fallback to decision path
- [x] Apply the per-route groundedness gate (`passes_gate`) after `gather(classify, retrieve)`
- [x] Re-run the eval with the classifier's *predicted* routes; confirm near misses (Q15–18) aren't misrouted to decision (Q17 would leak)

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
- Eval review fixes, all approved:
  - rule check against an anchor sentence (in place of the whole chunk)
  - classifier C = 4 → 64
  - two gate safeguards
  See `docs/ai-design.md` §2, §3 and §8.
- With reference plans, `scripts/eval_engine.py` passes **18/18** (it was 8/18 before the fixes) with the real classifier, NLI, reranker and embeddings. This covers the predicted-route check for Q15–18: all are refused.
- **Tests:** 227 pass offline, plus 21 opt-in real-NLI rule-check cases (`RUN_MODEL_TESTS=1`).
- **Next:** end-to-end runs with Claude (`claude-sonnet-5-5`).
