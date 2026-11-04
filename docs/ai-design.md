# AI Design

## Principle

LLM at the edges only:
- `decompose()`: question + retrieved chunks → structured decision plan
- `compose()`: verdicts + chunks → natural-language answer with citations

Everything else is System 1 models or application code.

## 1. Retrieval [Proposed]

- Hybrid search: pgvector cosine + `tsvector` keyword search, merged with reciprocal rank fusion (RRF).
- Rerank top ~20 with the cross-encoder; keep top ~5.
- Always filtered by `org_id` from the validated token.

## 2. Groundedness gate [Proposed]

If the top reranker score is below a threshold, return "The knowledge base doesn't contain this information." No LLM call. Logged as `unanswered`.

## 3. Question classifier (System 1) [Proposed]

- Labels: `direct`, `procedural`, `policy`, `decision`, `comparison`.
- Logistic regression on embeddings of 60–80 hand-labeled questions; saved as `.joblib`.
- Runs in parallel with retrieval.

## 4. Router [Confirmed]

| Question type | Path | Decisions |
|---|---|---|
| Direct information | Grounded answer | None |
| Procedural | Grounded answer, steps kept in order | None |
| Policy | Template hypothesis → NLI Boolean (no LLM decomposition) | Boolean |
| Multi-condition decision | Decompose → validate → parallel decisions → combine | Boolean (numeric + NLI) |
| Comparison | Retrieve per option → NLI Score each → Choice | Score + Choice |
| Not in knowledge base | Stopped at the gate | Gate |

Safety rules [Proposed]:
- Classifier top probability < 0.6 → decision path.
- Decomposer may return zero decisions → falls through to a grounded answer.

## 5. Comparison [Proposed]

1. Retrieve chunks for each option separately.
2. NLI-score each option's chunks against the criterion (e.g. "Plan A provides high travel reimbursement").
3. Choice picks the higher score. If scores are within 0.1, the answer says the documents don't clearly favor either.
4. If both options have explicit numbers, extract and compare with code instead of NLI.

## 6. Decomposition [Confirmed shape]

Rules are extracted **at question time** from retrieved chunks (see ADR 0002).

```json
{
  "user_facts": { "year": 2, "gpa": 3.6, "has_sports_scholarship": true },
  "decisions": [
    { "id": "d1", "type": "boolean", "check": "numeric", "fact": "gpa", "op": ">=", "value": 3.5, "source_chunk": "c12" },
    { "id": "d2", "type": "boolean", "check": "numeric", "fact": "year", "op": ">=", "value": 2, "source_chunk": "c12" },
    { "id": "d3", "type": "boolean", "check": "nli", "source_chunk": "c17",
      "hypothesis": "A student may hold a merit and a sports scholarship at the same time" }
  ],
  "combine": "ALL"
}
```

## 7. Validation [Proposed]

1. **Schema:** Pydantic, discriminated union on `check`.
2. **Semantic checks (code):**
   - every `source_chunk` was actually retrieved for this org
   - every numeric `value` appears in the cited chunk's text
   - every `fact` exists in `user_facts` or is explicitly missing
   - `op` ∈ {`>=`, `>`, `<=`, `<`, `==`, `!=`}
   Invalid specs are dropped.
3. **One retry** with validation errors fed back to the LLM.
4. **Fallback:** grounded answer without decisions, logged as `review`.

## 8. Executors (System 1) [Proposed]

| Check | Executor | Output |
|---|---|---|
| Numeric Boolean | Python comparator | TRUE / FALSE; UNKNOWN if fact missing |
| Text Boolean | NLI: entailment > 0.7 → TRUE; contradiction > 0.7 → FALSE; else UNKNOWN | Verdict + confidence |
| Choice | NLI zero-shot over candidate labels | Label + confidence |
| Score | NLI entailment probability | 0–1 |

- One NLI model (`nli-deberta-v3-small`) serves Boolean-on-text, Choice and Score.
- Parallel: `asyncio.gather` over `asyncio.to_thread`, 5 s timeout each.
- Failure or timeout → that decision is UNKNOWN with a reason; the request continues.

## 9. Combiner [Proposed]

Three-valued logic:

| Rule | FALSE if | UNKNOWN if | TRUE if |
|---|---|---|---|
| ALL | any FALSE | none FALSE, any UNKNOWN | all TRUE |
| ANY | all FALSE | none TRUE, any UNKNOWN | any TRUE |

- Overall confidence = minimum confidence of the decisions that count.
- UNKNOWN from a missing fact → answer asks for that fact and cites the rule needing it (`outcome: needs_info`).

## 10. LLM client [Proposed]

```python
class LLMClient(Protocol):
    async def decompose(self, question, chunks) -> DecisionPlan: ...
    async def compose(self, question, verdicts, chunks) -> str: ...
```

- Provider set by `LLM_PROVIDER` in `.env`; one real implementation is enough.
- `FakeLLMClient` for tests.
- Timeouts, retries and "LLM unavailable" handled here.

## 11. Answer composition [Open]

- `compose()` uses only given verdicts and chunks; must not change a verdict.
- Citation format: `filename — Page N`.
- To decide: exact prompt guardrails, how UNKNOWN / needs_info answers are phrased.

## 12. Thresholds (all in `config.py`) [Proposed]

| Threshold | Value |
|---|---|
| NLI verdict | 0.7 |
| Router confidence | 0.6 |
| Comparison tie | 0.1 |
| Groundedness gate | tuned on test data |

## 13. Transparency

`/api/ask` returns `route`, `verdicts` and `timings`; the widget shows them in a collapsible "How this was answered" panel. This shows architecture and parallelism without exposing chain-of-thought.
