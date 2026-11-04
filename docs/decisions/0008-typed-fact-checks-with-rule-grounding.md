# 0008: Typed fact checks with NLI rule grounding

**Status:** Accepted

## Context
The original decision spec had numeric checks and NLI checks. Conditions about the *user* that aren't numbers, such as "must not hold another institutional scholarship", were modelled as NLI checks of the policy. That evaluates the rule, not the user, so it returned FALSE for every student: test question 4 ("no other scholarship") would have come out not eligible.

There was also no proof that a rule the LLM extracted actually exists in the cited chunk, beyond a numeric value appearing somewhere in its text.

## Decision
- Every decision carries `rule`: the rule as stated in the document.
- **Fact checks** (`check: "fact"`) compare a typed user fact (number, boolean, string) with a value, using an op whitelisted per type. Code runs them, and a missing fact gives UNKNOWN.
- **Grounding:**
  - Numbers must appear in the cited chunk after normalization ("75%" → 75), and strings must appear case-insensitively.
  - For every fact check, the NLI model must find that the cited chunk entails `rule` (≥ 0.7). Otherwise the spec is dropped. NLI verifies the rule exists, and code decides whether the user meets it.
- **NLI checks** (`check: "nli"`) are only for conditions about the policy itself. The decisive entailment or contradiction is both the grounding and the verdict.

## Consequences
- Q4 becomes `has_other_scholarship == false` → TRUE, and ALL TRUE holds.
- Each user-facing verdict is produced by deterministic code, and each rule it relies on is checked by a System 1 model. The LLM proposes, and System 1 and code dispose.
- This adds one NLI pass per fact check, run in parallel (~tens of ms each on CPU).
- Paraphrased rules the NLI model can't confirm are dropped. They show up as `review`, not as wrong answers.
