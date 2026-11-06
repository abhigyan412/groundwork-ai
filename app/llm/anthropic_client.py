"""Anthropic (Claude) implementation of LLMClient.

- Structured outputs (`output_config.format` with a JSON schema) for the decompose step; the
  parsed JSON is then validated with Pydantic, and semantically by code (app/engine/validate.py).
- Server-side refusal fallback (`fallbacks="default"`, beta server-side-fallback-2026-07-01).
- Effort is set explicitly per call (the default differs by model). Thinking stays on
  (adaptive); it can't be disabled on the supported models.
- SDK retries handle 408/409/429/5xx and connection errors; anything left becomes
  LLMUnavailableError so the pipeline can degrade gracefully.
"""

import json
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.engine.spec import (
    COMPARISON_PLAN_SCHEMA,
    DECISION_PLAN_SCHEMA,
    EXTRACTED_VALUES_SCHEMA,
    ComparisonPlan,
    DecisionPlan,
    ExtractedValues,
)
from app.llm import prompts, usage
from app.llm.base import ComposeInput, LLMOutputError, LLMUnavailableError, PromptChunk

FALLBACK_BETA = "server-side-fallback-2026-07-01"
T = TypeVar("T", bound=BaseModel)


class AnthropicLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        key = settings.llm_api_key.get_secret_value() or None  # None: SDK resolves credentials
        self._client: anthropic.AsyncAnthropic | None
        self._init_error: str | None = None
        try:
            self._client = anthropic.AsyncAnthropic(
                api_key=key,
                timeout=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
            )
        except anthropic.AnthropicError as exc:  # no credentials yet: start anyway, fail per call
            self._client, self._init_error = None, str(exc)

    async def _call(
        self,
        *,
        method: str,
        system: str,
        messages: list[dict[str, Any]],
        effort: str,
        schema: dict[str, Any] | None,
    ) -> str:
        if self._client is None:
            raise LLMUnavailableError(f"LLM not configured: {self._init_error}")
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        try:
            response = await self._client.beta.messages.create(
                model=self._settings.resolved_llm_model,
                max_tokens=self._settings.llm_max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                output_config=output_config,
            )
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise LLMUnavailableError(f"LLM unreachable: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("LLM rate limited") from exc
        except anthropic.APIStatusError as exc:  # auth, bad request, 5xx after retries
            raise LLMUnavailableError(f"LLM error {exc.status_code}: {exc.message}") from exc
        except anthropic.AnthropicError as exc:  # e.g. missing credentials
            raise LLMUnavailableError(f"LLM client error: {exc}") from exc

        u = response.usage
        usage.record(
            usage.LLMCall(
                method=method,
                model=response.model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_input_tokens=u.cache_read_input_tokens or 0,
                cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
                stop_reason=response.stop_reason,
            )
        )
        if response.stop_reason == "refusal":
            raise LLMUnavailableError("The LLM declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMOutputError("LLM output was cut off at max_tokens")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise LLMOutputError("LLM returned no text")
        return text

    async def _structured(
        self,
        model: type[T],
        *,
        method: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> T:
        text = await self._call(
            method=method,
            system=system,
            messages=messages,
            effort=self._settings.llm_effort_decompose,
            schema=schema,
        )
        try:
            return model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMOutputError(f"LLM output didn't match {model.__name__}: {exc}") from exc

    async def decompose(
        self,
        question: str,
        chunks: list[PromptChunk],
        feedback: list[str] | None = None,
        previous: DecisionPlan | None = None,
    ) -> DecisionPlan:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompts.decompose_user(question, chunks)}
        ]
        if feedback and previous is not None:  # append-only retry: prior plan, then the errors
            messages += [
                {"role": "assistant", "content": previous.model_dump_json()},
                {"role": "user", "content": prompts.decompose_feedback(feedback)},
            ]
        return await self._structured(
            DecisionPlan,
            method="decompose",
            system=prompts.DECOMPOSE_SYSTEM,
            messages=messages,
            schema=DECISION_PLAN_SCHEMA,
        )

    async def decompose_comparison(
        self, question: str, chunks: list[PromptChunk]
    ) -> ComparisonPlan:
        return await self._structured(
            ComparisonPlan,
            method="decompose_comparison",
            system=prompts.COMPARISON_SYSTEM,
            messages=[{"role": "user", "content": prompts.comparison_user(question, chunks)}],
            schema=COMPARISON_PLAN_SCHEMA,
        )

    async def extract_comparison_values(
        self, plan: ComparisonPlan, chunks_by_option: dict[str, list[PromptChunk]]
    ) -> ExtractedValues:
        content = prompts.extract_user(plan.options, plan.criterion, chunks_by_option)
        return await self._structured(
            ExtractedValues,
            method="extract_comparison_values",
            system=prompts.EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": content}],
            schema=EXTRACTED_VALUES_SCHEMA,
        )

    async def compose(self, data: ComposeInput) -> str:
        return await self._call(
            method="compose",
            system=prompts.COMPOSE_SYSTEM,
            messages=[{"role": "user", "content": prompts.compose_user(data)}],
            effort=self._settings.llm_effort_compose,
            schema=None,
        )
