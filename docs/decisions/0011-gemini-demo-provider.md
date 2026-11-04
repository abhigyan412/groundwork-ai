# 0011: Gemini free tier as the demo LLM provider

**Status:** Accepted

## Context
The LLM was planned as Anthropic Claude (`claude-sonnet-5-5`), but the project has no Anthropic API credits, so the end-to-end eval couldn't run: every call returned "credit balance is too low". The demo needs an LLM that is free to use.

## Decision
- Add a Gemini client (`google-genai` SDK, Flash model, structured JSON output) behind the existing `LLMClient` protocol, and make `gemini` the default `LLM_PROVIDER`.
- Keep the Anthropic client unchanged and selectable (`LLM_PROVIDER=anthropic`). `fake` remains for tests and offline work.
- The free tier allows about 5-10 requests per minute, so the Gemini client retries 429s and 5xx with exponential backoff, and `scripts/eval_engine.py` paces its calls (`--rpm`, default 8 for Gemini).

## Consequences
- Prompts, schemas, validation and the System 1 decision path are shared, so switching providers needs no other code change. The ADR 0003 boundary (LLM only in the decompose step and `compose()`) holds for every provider.
- Gemini's structured output gets a flattened schema (no `anyOf`). The strictness lives in the Pydantic models, which every provider's output must pass.
- Under free-tier limits, a burst of visitors will hit 429s. Retries absorb short bursts; beyond that, requests degrade to template answers or 503. That is acceptable for a demo; production would use a paid tier.
- Answer quality and plan accuracy may differ between providers; `scripts/eval_engine.py` reports plan-vs-reference per run so the difference is measured, not assumed.
