# 0003: LLM only at the edges

**Status:** Accepted

## Context
The assignment's primary objective is to show LLMs and System 1 decision models working together, not an LLM doing everything.

## Decision
The LLM has exactly two jobs, `decompose()` and `compose()`. Classification, gating, decisions, validation and combination are done by System 1 models or code.

## Consequences
- Decisions are reproducible and testable without API calls.
- Each decision carries a confidence and a source, which makes answers explainable.
- Requires a strict contract (decision spec schema) between the LLM and System 1.
