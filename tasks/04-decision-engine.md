# Task 04: Decision Engine

**Day 2** · Refs: `docs/ai-design.md` §3–15, `docs/decisions/0002–0005`, `0008–0010`

## Goal
Route each question; run structured decisions with System 1 models in parallel; combine results.

## Checklist

### Classifier and router
- [ ] Label 60–80 example questions (`sample_data/classifier_examples.json`)
- [ ] `scripts/train_classifier.py` → `.joblib`
- [ ] Router with low-confidence fallback to decision path
- [ ] Apply the per-route groundedness gate (`passes_gate`) after `gather(classify, retrieve)`
- [ ] Re-run `scripts/eval_retrieval.py` with the classifier's *predicted* routes; confirm near misses (Q15–18) aren't misrouted to decision (Q17 would leak)

### LLM client
- [ ] `LLMClient` protocol (`decompose`, `decompose_comparison`, `extract_comparison_values`, `compose`), Anthropic implementation
- [ ] `FakeLLMClient` for tests
- [ ] `decompose()` prompt producing the decision spec JSON

### Validation
- [ ] Pydantic models for the decision plan: typed facts (number/boolean/string), `fact` | `nli` checks, `rule` + `label` on every decision
- [ ] Number normalization ("75%" → 75, "₹45,000" → 45000)
- [ ] Semantic checks: chunk retrieved, value in chunk text, fact type matches, op allowed for type
- [ ] Rule grounding: NLI entailment of `rule` by cited chunk ≥ 0.7, else drop (ADR 0008)
- [ ] One retry with errors, then fallback

### Executors
- [ ] Fact comparator (number/boolean/string; missing → UNKNOWN)
- [ ] NLI Boolean (entail/contradict thresholds)
- [ ] NLI Score (comparison fallback)
- [ ] Parallel execution with per-decision timeout; failure → UNKNOWN

### Paths
- [ ] Policy path: pattern hypotheses (ADR 0010) → NLI on top 3 chunks → strongest decisive verdict; no match → decision path
- [ ] Comparison path (ADR 0009): `decompose_comparison` → per-option retrieval → `extract_comparison_values` → validate → code compare; NLI Score + Choice fallback
- [ ] Decision path: decompose → validate → execute → combine

### Combiner and composer
- [ ] ALL/ANY three-valued logic, min confidence
- [ ] `needs_info` only when overall UNKNOWN from missing facts; decided results still note missing facts
- [ ] `compose()` with citations, using only verdicts + chunks

## Done when
Unit tests for combiner, validator, normalization, policy patterns and comparison pass; test questions 3, 4, 5, 6, 10, 11 and 12 produce the expected verdicts.
