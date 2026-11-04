# 0002: Extract rules at question time

**Status:** Proposed

## Context
Decisions need rules (thresholds, conditions) from the documents. They can be compiled into a structured store at upload, or extracted from retrieved chunks when a question is asked.

## Decision
Extract at question time. The decomposer reads the retrieved chunks and outputs decision specs that cite them.

## Consequences
- Works for any PDF, including ones reviewers upload themselves.
- One code path; no rule store to keep in sync when documents are replaced.
- More responsibility on the LLM at answer time, mitigated by semantic validation (thresholds must appear in the cited chunk).
- Compiling rules at upload is listed as a production improvement.
