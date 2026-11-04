# 0010: Policy hypotheses from question patterns

**Status:** Accepted

## Context
The policy path was "template hypothesis → NLI Boolean, no LLM", but the template was never defined. NLI needs a declarative statement, and users ask questions.

## Decision
- A small, tested set of regex patterns turns yes/no questions into statements: "Can I X?" → "It is permitted to X."; "Is X allowed?" → "X is allowed."; "Do I need to X?" / "Am I required to X?" → "It is required to X."; "Can X be Y?" → "X can be Y." The full table is in `docs/ai-design.md` §5.
- NLI runs against each of the top 3 reranked chunks, and the strongest decisive verdict (≥ 0.7) wins. If nothing is decisive, the result is UNKNOWN (`review`).
- If no pattern matches, the question goes to the decision path, where `decompose()` returns a single `nli` check.

## Consequences
- Common policy questions are answered with no LLM call before `compose()`.
- The patterns are English-only and brittle on unusual phrasings, but the fallback catches misses instead of producing wrong hypotheses.
- Checking 3 chunks helps when the rule isn't in the top-ranked chunk. Taking the strongest decisive verdict means a single clear statement is enough.
