# 0009: Comparison by extraction, decided by code

**Status:** Accepted

## Context
Comparison questions ("Which block is cheaper, A or B?") need the options, the criterion and its direction. Nothing in the original design was allowed to extract them: the router skipped decomposition, and the LLM was limited to `decompose()` and `compose()`. Matching numbers in chunks to options by regex alone is unreliable.

## Decision
1. `decompose_comparison()` returns `{options, criterion, better: "lower" | "higher"}`.
2. Retrieve per option with `"{option} {criterion}"`.
3. `extract_comparison_values()` returns at most one value per option, with its source chunk.
4. Code checks that each value appears in its cited chunk, then compares. A missing value, a tie or a unit mismatch gives "the documents don't clearly answer this".
5. If no option has a numeric value, the NLI Score + Choice fallback is used.

Both new LLM calls belong to the understanding (decompose) edge. CLAUDE.md's rule now reads "the decompose step and `compose()`".

## Consequences
- The LLM reads; code decides. The Choice verdict is a deterministic comparison of grounded numbers.
- Comparison costs 2 LLM calls plus `compose()`, against 1 plus `compose()` on the decision path.
- Comparisons that aren't numeric rely on NLI scores, which are weaker. The tie margin keeps weak preferences from being stated as facts.
