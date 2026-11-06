"""Gemini (Google) implementation of LLMClient, via the official google-genai SDK.

- Structured output: `response_mime_type="application/json"` plus `response_json_schema`, using
  the flattened (no anyOf) form of the shared schemas (app/engine/spec.py). The JSON is then
  validated with the same Pydantic models as for every provider, and semantically by code.
- Thinking: Gemini 3.x models take `thinking_level`; the configured efforts map to low/medium/high.
- Rate limits: the free tier allows a few requests per minute, so 429 and 5xx responses are
  retried with exponential backoff (app/llm/retry.py), honouring a RetryInfo delay if one is sent.
  A per-day quota 429 is not retried (LLMQuotaExhaustedError), and each call, retries included,
  is bounded by `llm_call_deadline_seconds`.
- Anything left over (auth, bad request, blocked content, truncated or empty output) becomes
  LLMUnavailableError / LLMOutputError, exactly like the Anthropic client.
"""

import json
import re
from typing import Any, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.engine.spec import (
    COMPARISON_PLAN_SCHEMA,
    DECISION_PLAN_SCHEMA,
    EXTRACTED_VALUES_SCHEMA,
    ComparisonPlan,
    DecisionPlan,
    ExtractedValues,
    flatten_any_of,
)
from app.llm import prompts, usage
from app.llm.base import (
    ComposeInput,
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMUnavailableError,
    PromptChunk,
)
from app.llm.retry import DeadlineExceededError, with_backoff

T = TypeVar("T", bound=BaseModel)

# Our effort names → Gemini 3.x thinking levels.
THINKING_LEVEL = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
# Finish reasons that mean the model declined or was blocked (vs. a normal stop).
BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}
_SCHEMAS = {
    "decision": flatten_any_of(DECISION_PLAN_SCHEMA),
    "comparison": flatten_any_of(COMPARISON_PLAN_SCHEMA),
    "extracted": flatten_any_of(EXTRACTED_VALUES_SCHEMA),
}
_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")


def is_daily_quota(exc: BaseException) -> bool:
    """A 429 for a per-day quota (QuotaFailure quotaId like 'GenerateRequestsPerDay…'):
    retrying within seconds can't succeed."""
    if not isinstance(exc, errors.APIError) or exc.code != 429:
        return False
    details = exc.details if isinstance(exc.details, dict) else {}
    for item in details.get("error", {}).get("details", []) or []:
        if isinstance(item, dict) and item.get("@type", "").endswith("google.rpc.QuotaFailure"):
            for v in item.get("violations", []) or []:
                if "perday" in str(v.get("quotaId", "")).lower():
                    return True
    return False


def retry_hint(exc: BaseException) -> tuple[bool, float | None]:
    """Retry 429 (per-minute rate limit) and 5xx; use RetryInfo.retryDelay ("17s") when present.
    A per-day quota is not retried."""
    if not isinstance(exc, errors.APIError):
        return False, None
    if exc.code != 429 and not (500 <= (exc.code or 0) < 600):
        return False, None
    if is_daily_quota(exc):
        return False, None
    details = exc.details if isinstance(exc.details, dict) else {}
    for item in details.get("error", {}).get("details", []) or []:
        if isinstance(item, dict) and item.get("@type", "").endswith("google.rpc.RetryInfo"):
            m = _DELAY.match(str(item.get("retryDelay", "")))
            if m:
                return True, float(m.group(1))
    return True, None


class GeminiLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        key = settings.llm_api_key.get_secret_value() or None  # None: SDK reads GEMINI_API_KEY
        self._client: genai.Client | None
        self._init_error: str | None = None
        try:
            self._client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=int(settings.llm_timeout_seconds * 1000)),
            )
        except Exception as exc:  # no credentials yet: start anyway, fail per call
            self._client, self._init_error = None, str(exc)

    def _config(self, system: str, effort: str, schema: dict[str, Any] | None):
        model = self._settings.resolved_llm_model
        config: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": self._settings.llm_max_tokens,
        }
        if model.startswith("gemini-3"):
            config["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING_LEVEL[effort])
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = schema
        return types.GenerateContentConfig(**config)

    async def _call(
        self,
        *,
        method: str,
        system: str,
        contents: list[types.Content],
        effort: str,
        schema: dict[str, Any] | None,
    ) -> str:
        if self._client is None:
            raise LLMUnavailableError(f"LLM not configured: {self._init_error}")
        client, s = self._client, self._settings
        model = s.resolved_llm_model

        async def once():
            return await client.aio.models.generate_content(
                model=model, contents=contents, config=self._config(system, effort, schema)
            )

        try:
            response = await with_backoff(
                once,
                classify=retry_hint,
                retries=s.llm_rate_limit_retries,
                base_seconds=s.llm_retry_base_seconds,
                max_total_wait=s.llm_retry_max_wait_seconds,
                deadline=s.llm_call_deadline_seconds,
            )
        except errors.APIError as exc:
            if is_daily_quota(exc):
                raise LLMQuotaExhaustedError("LLM daily quota exhausted") from exc
            if exc.code == 429:
                raise LLMUnavailableError("LLM rate limited (retries exhausted)") from exc
            raise LLMUnavailableError(f"LLM error {exc.code}: {exc.message}") from exc
        except DeadlineExceededError as exc:
            raise LLMUnavailableError(
                f"LLM took longer than {s.llm_call_deadline_seconds:.0f} s"
            ) from exc
        except Exception as exc:  # network, timeout
            raise LLMUnavailableError(f"LLM unreachable: {type(exc).__name__}: {exc}") from exc

        meta = response.usage_metadata
        cached = (meta.cached_content_token_count or 0) if meta else 0
        candidate = response.candidates[0] if response.candidates else None
        finish = candidate.finish_reason.name if candidate and candidate.finish_reason else None
        usage.record(
            usage.LLMCall(
                method=method,
                model=getattr(response, "model_version", None) or model,
                input_tokens=((meta.prompt_token_count or 0) - cached) if meta else 0,
                # Thinking tokens are billed as output.
                output_tokens=(
                    (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
                )
                if meta
                else 0,
                cache_read_input_tokens=cached,
                stop_reason=finish,
            )
        )
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            raise LLMUnavailableError(f"The LLM blocked the prompt ({feedback.block_reason})")
        if finish in BLOCKED:
            raise LLMUnavailableError(f"The LLM declined the request ({finish})")
        if finish == "MAX_TOKENS":
            raise LLMOutputError("LLM output was cut off at max_output_tokens")
        text = (response.text or "").strip()
        if not text:
            raise LLMOutputError("LLM returned no text")
        return text

    async def _structured(
        self,
        model: type[T],
        *,
        method: str,
        system: str,
        contents: list[types.Content],
        schema: dict[str, Any],
    ) -> T:
        text = await self._call(
            method=method,
            system=system,
            contents=contents,
            effort=self._settings.llm_effort_decompose,
            schema=schema,
        )
        try:
            return model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMOutputError(f"LLM output didn't match {model.__name__}: {exc}") from exc

    @staticmethod
    def _user(text: str) -> types.Content:
        return types.Content(role="user", parts=[types.Part(text=text)])

    async def decompose(
        self,
        question: str,
        chunks: list[PromptChunk],
        feedback: list[str] | None = None,
        previous: DecisionPlan | None = None,
    ) -> DecisionPlan:
        contents = [self._user(prompts.decompose_user(question, chunks))]
        if feedback and previous is not None:  # append-only retry: prior plan, then the errors
            contents += [
                types.Content(role="model", parts=[types.Part(text=previous.model_dump_json())]),
                self._user(prompts.decompose_feedback(feedback)),
            ]
        return await self._structured(
            DecisionPlan,
            method="decompose",
            system=prompts.DECOMPOSE_SYSTEM,
            contents=contents,
            schema=_SCHEMAS["decision"],
        )

    async def decompose_comparison(
        self, question: str, chunks: list[PromptChunk]
    ) -> ComparisonPlan:
        return await self._structured(
            ComparisonPlan,
            method="decompose_comparison",
            system=prompts.COMPARISON_SYSTEM,
            contents=[self._user(prompts.comparison_user(question, chunks))],
            schema=_SCHEMAS["comparison"],
        )

    async def extract_comparison_values(
        self, plan: ComparisonPlan, chunks_by_option: dict[str, list[PromptChunk]]
    ) -> ExtractedValues:
        content = prompts.extract_user(plan.options, plan.criterion, chunks_by_option)
        return await self._structured(
            ExtractedValues,
            method="extract_comparison_values",
            system=prompts.EXTRACT_SYSTEM,
            contents=[self._user(content)],
            schema=_SCHEMAS["extracted"],
        )

    async def compose(self, data: ComposeInput) -> str:
        return await self._call(
            method="compose",
            system=prompts.COMPOSE_SYSTEM,
            contents=[self._user(prompts.compose_user(data))],
            effort=self._settings.llm_effort_compose,
            schema=None,
        )
