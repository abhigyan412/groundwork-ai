# AI Design

## Principle

The LLM works only at the edges:
- **Understanding (decompose step):** turns a question and the retrieved chunks into structured specs. Three calls share this edge:
  - `decompose()`: decision plan
  - `decompose_comparison()`: comparison plan
  - `extract_comparison_values()`: one cited value per option
- **Answering:** `compose()` turns verdicts and chunks into a natural-language answer with citations.

Everything in between is System 1 models or application code: classification, routing, gating, rule grounding, fact checks, NLI decisions, comparison and combination. The LLM never produces a verdict.

## 1. Retrieval [Proposed]

- Hybrid search: pgvector cosine plus `tsvector` keyword search, merged with reciprocal rank fusion (RRF).
- Rerank the top ~20 with the cross-encoder and keep the top ~5.
- Always filtered by `org_id` from the validated token.

## 2. Groundedness gate [Proposed]

If the top reranker score is below a threshold, the answer is "The documents for {org} don't cover this." No LLM call is made, and the question is logged as `unanswered` with `route = null`.

## 3. Question classifier (System 1) [Proposed]

- Labels: `direct`, `procedural`, `policy`, `decision`, `comparison`.
- Logistic regression on embeddings of 60–80 hand-labeled questions, saved as `.joblib`.
- Runs in parallel with retrieval.

## 4. Router [Confirmed]

| Question type | Path | Decisions |
|---|---|---|
| Direct information | Grounded answer | None |
| Procedural | Grounded answer, steps kept in order | None |
| Policy | Pattern hypothesis → NLI Boolean on top 3 chunks (§5). No pattern match → decision path with a single NLI check | Boolean |
| Multi-condition decision | Decompose → validate (schema + rule grounding) → parallel checks → combine | Boolean (fact checks + NLI) |
| Comparison | Comparison decompose → retrieve per option → extract values → code compares (§6). No numbers → NLI Score + Choice | Choice (+ Score) |
| Not in knowledge base | Stopped at the gate | Gate |

Safety rules [Proposed]:
- Classifier top probability < 0.6 → decision path.
- The decomposer may return zero decisions → falls through to a grounded answer.

## 5. Policy path [Confirmed] (ADR 0010)

1. **Hypothesis from patterns (code, no LLM).** The yes/no question is rewritten as a statement:

   | Question pattern | Hypothesis |
   |---|---|
   | Can I/we X? · May I/we X? | It is permitted to X. |
   | Can X be Y? | X can be Y. |
   | Is/Are X allowed / permitted? | X is/are allowed / permitted. |
   | Do I/we need (to) X? | It is required to X. |
   | Am I / Are we required to X? · Do I/we have to X? · Must I/we X? | It is required to X. |

   Patterns are case-insensitive and the trailing "?" is removed. Inside X, "my"/"our" become "the", and "I"/"we" are dropped from the subject position by the pattern itself, so the hypothesis is impersonal: "Can I hold the merit scholarship and a sports scholarship together?" → "It is permitted to hold the merit scholarship and a sports scholarship together."
2. **NLI against each of the top 3 reranked chunks.** A chunk is *decisive* if entailment ≥ 0.7 (TRUE) or contradiction ≥ 0.7 (FALSE). The verdict comes from the decisive chunk with the highest probability. If no chunk is decisive, the verdict is UNKNOWN and the outcome is `review`.
3. **No pattern match** → the decision path, where `decompose()` is expected to return a single `nli` check.

## 6. Comparison path [Confirmed] (ADR 0009)

1. **`decompose_comparison(question, chunks)`** returns `{ "options": ["Block A", "Block B"], "criterion": "hostel fee", "better": "lower" | "higher" }`. It must return at least 2 options; otherwise the question falls back to the decision path.
2. **Retrieve per option** using the query `"{option} {criterion}"`, with the same hybrid search, rerank and `org_id` filter.
3. **`extract_comparison_values(options, criterion, chunks_per_option)`**: the LLM returns at most one value per option, with its `source_chunk`, e.g. `{ "option": "Block A", "value": 45000, "unit": "INR/semester", "source_chunk": "c3" }`.
4. **Validation (code):** the cited chunk was retrieved for that option, and the value appears in its text after number normalization (§8). Values that fail are dropped.
5. **Compare (code):** pick the option with the lowest or highest value according to `better`.
   - If any option is missing a value, or the best values are equal, the answer is "The documents don't clearly answer this." This is outcome `review`, and the per-option evidence is still shown.
   - If units differ between options, the result is treated as missing.
6. **No numeric values for any option** → NLI fallback. Each option's chunks are scored against "{option} offers a {better-adjective} {criterion}" (Score = max entailment probability). Choice takes the top score. If the top two are within 0.1 (`comparison_tie_margin`), the answer is "doesn't clearly answer".

## 7. Decomposition [Confirmed] (ADRs 0002, 0008)

Rules are extracted **at question time** from retrieved chunks. Every decision states the rule it relies on, *as written in the document*, in `rule`.

```json
{
  "user_facts": {
    "year":                  { "type": "number",  "value": 2 },
    "gpa":                   { "type": "number",  "value": 3.6 },
    "attendance_pct":        { "type": "number",  "value": 80 },
    "has_other_scholarship": { "type": "boolean", "value": false }
  },
  "decisions": [
    { "id": "d1", "check": "fact", "fact": "gpa", "op": ">=", "value": 3.5, "source_chunk": "c12",
      "label": "GPA at least 3.5",
      "rule": "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale." },
    { "id": "d2", "check": "fact", "fact": "year", "op": ">=", "value": 2, "source_chunk": "c12",
      "label": "Year of study 2 or above",
      "rule": "The merit scholarship is open to students in year 2 or above." },
    { "id": "d3", "check": "fact", "fact": "attendance_pct", "op": ">=", "value": 75, "source_chunk": "c12",
      "label": "Attendance at least 75%",
      "rule": "Applicants must have attendance of at least 75%." },
    { "id": "d4", "check": "fact", "fact": "has_other_scholarship", "op": "==", "value": false, "source_chunk": "c17",
      "label": "No other institutional scholarship",
      "rule": "Applicants must not hold another institutional scholarship." }
  ],
  "combine": "ALL"
}
```

- **Fact types:** `number`, `boolean`, `string`. A fact the user didn't state is simply absent from `user_facts`, and its check is UNKNOWN.
- **Ops:** numbers use `>=`, `>`, `<=`, `<`, `==`, `!=`. Booleans and strings use only `==` and `!=`.
- **Units:** the decomposer converts user facts to the rule's unit ("1.5 years" → 18 when the rule says months). The fact name carries the unit where it helps (`tenure_months`).
- **`check: "nli"`** is only for conditions about the *policy itself*, not the user, e.g. "Is remote work allowed on Fridays?". Shape: `{ "id", "check": "nli", "hypothesis", "label", "rule", "source_chunk" }`.
- `label` is the short, plain-language condition shown in the evidence trail. It never decides anything.

## 8. Validation [Confirmed] (ADR 0008)

1. **Schema:** Pydantic, with a discriminated union on `check` (`fact` | `nli`). `op` is restricted by the fact's type, and `value`'s type must match the fact's declared type.
2. **Semantic checks (code):**
   - every `source_chunk` was actually retrieved for this org in this request
   - number values appear in the cited chunk's text after normalization
   - string values appear in the cited chunk's text (case-insensitive)
   - every `fact` referenced by a check is either in `user_facts` with a matching type, or absent (→ UNKNOWN at execution)
3. **Rule grounding (System 1 NLI):** for every `fact` check, the cited chunk must entail `rule` with probability ≥ 0.7 (`rule_grounding_threshold`), or the spec is dropped. NLI verifies the rule exists, and code decides whether the user meets it. For `nli` checks, the check itself is the grounding: an entailment or contradiction of `hypothesis` ≥ 0.7 decides it, and anything else is UNKNOWN.
4. **One retry** with the validation errors fed back to the LLM (schema and semantic errors; grounding failures are reported as "rule not supported by the cited chunk").
5. **Fallback:** if no valid decisions remain after the retry, give a grounded answer without decisions, logged as `review`.

**Number normalization:** extract every number from the chunk text, removing thousands separators, currency symbols and `%` ("75%" → 75, "₹45,000" → 45000, "3.5/4.0" → 3.5 and 4.0, "6-month" → 6). Numbers match if equal within 1e-9. Numbers written as words ("six") aren't recognised; the sample PDFs use digits, and this is listed as a known limitation.

## 9. Executors (System 1) [Proposed]

| Check | Executor | Output |
|---|---|---|
| Fact (number / boolean / string) | Python comparator | TRUE / FALSE; UNKNOWN if the fact is missing. Confidence 1.0 (the rule-grounding probability is recorded separately) |
| NLI (policy condition) | NLI: entailment ≥ 0.7 → TRUE; contradiction ≥ 0.7 → FALSE; else UNKNOWN | Verdict + confidence |
| Choice | Code over extracted numbers; NLI Score fallback | Option + confidence |
| Score | NLI entailment probability | 0–1 |

- One NLI model (`nli-deberta-v3-small`) serves rule grounding, NLI checks, the policy path and Score.
- Parallel: `asyncio.gather` over `asyncio.to_thread`, 5 s timeout each. Rule grounding runs in parallel across specs too.
- Failure or timeout → that decision is UNKNOWN with a reason, and the request continues (`outcome: review`).

## 10. Combiner [Proposed]

Three-valued logic:

| Rule | FALSE if | UNKNOWN if | TRUE if |
|---|---|---|---|
| ALL | any FALSE | none FALSE, any UNKNOWN | all TRUE |
| ANY | all FALSE | none TRUE, any UNKNOWN | any TRUE |

- Overall confidence = minimum confidence of the decisions that count.
- **Outcome:** `needs_info` only when the *overall* result is UNKNOWN and every UNKNOWN comes from a missing fact. The answer then asks for those facts and cites the rules that need them. If the overall result is decided (e.g. FALSE under ALL) while some facts are missing, the outcome is `answered` and the answer still notes which facts weren't given (test question 5). UNKNOWN from model failure or timeout → `review`.

## 11. Verdict shape (API and evidence trail)

Each verdict returned by `/api/ask` and stored in `questions.verdicts`:

```json
{ "id": "d1", "kind": "fact", "label": "GPA at least 3.5", "rule": "Applicants must hold…",
  "value": "TRUE", "confidence": 1.0, "user_value": 3.6, "missing_fact": null,
  "source": { "file": "Scholarship_Rules.pdf", "page": 4, "excerpt": "Applicants must hold a cumulative GPA of 3.5…" },
  "reason": null }
```

`kind` ∈ `fact` | `nli` | `policy` | `choice` | `score`. `excerpt` is cut from the cited chunk by code, never written by the LLM.

## 12. LLM client [Confirmed]

```python
class LLMClient(Protocol):
    async def decompose(self, question, chunks) -> DecisionPlan: ...
    async def decompose_comparison(self, question, chunks) -> ComparisonPlan: ...
    async def extract_comparison_values(self, plan, chunks_by_option) -> list[ExtractedValue]: ...
    async def compose(self, question, verdicts, chunks) -> str: ...
```

- Provider set by `LLM_PROVIDER` in `.env`. The real implementation is **Anthropic (Claude)**, with the default model `claude-sonnet-5-5` set by `LLM_MODEL`. `fake` stays the default until task 04.
- `FakeLLMClient` for tests.
- Timeouts, retries and "LLM unavailable" are handled here.
- Chunk text is passed as delimited data with an explicit instruction that it contains no instructions (prompt-injection guard).

## 13. Answer composition [Open]

- `compose()` uses only the verdicts and chunks it's given, and must not change a verdict.
- Citation format: `filename — Page N`.
- To decide in task 04: exact prompt guardrails, and how UNKNOWN / needs_info answers are phrased.

## 14. Thresholds (all in `config.py`) [Proposed]

| Threshold | Value |
|---|---|
| NLI verdict | 0.7 |
| Rule grounding (entailment) | 0.7 |
| Policy path: chunks checked | 3 |
| Router confidence | 0.6 |
| Comparison tie (NLI fallback) | 0.1 |
| Groundedness gate | tuned on test data |

## 15. Transparency

`/api/ask` returns `route`, `verdicts` and `timings`, and the widget shows them in a collapsible "How this was answered" panel. This shows the architecture and the parallelism without exposing chain-of-thought.
