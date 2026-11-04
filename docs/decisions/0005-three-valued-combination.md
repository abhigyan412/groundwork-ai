# 0005: Three-valued decision combination

**Status:** Proposed

## Context
Users often omit facts (e.g. their GPA). Treating a missing fact as FALSE gives wrong answers; guessing invents answers.

## Decision
Every decision returns TRUE, FALSE or UNKNOWN. ALL/ANY combine with three-valued logic. Overall confidence is the minimum of the decisions that count.

## Consequences
- The system can say "eligible on 2 of 3 conditions; please share your GPA" with a citation for the missing rule.
- Decision-model failures degrade to UNKNOWN instead of failing the request.
