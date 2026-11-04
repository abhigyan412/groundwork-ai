# 0004: Route by question type

**Status:** Accepted

## Context
Running decomposition on every question adds latency and failure points for simple lookups.

## Decision
A System 1 classifier routes questions: only multi-condition questions are decomposed; comparison uses per-option retrieval with Score + Choice; policy uses a single NLI Boolean; direct and procedural go straight to a grounded answer.

## Consequences
- Simple questions are fast and cheap.
- A misroute must not cause a wrong answer: low classifier confidence goes to the decision path, and the decomposer may return zero decisions.
