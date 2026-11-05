"""GeminiLLM with the SDK stubbed out: request shape, parsing, usage, error mapping, 429 backoff.
No network (CLAUDE.md: no real API calls in tests)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import errors, types

from app.config import get_settings
from app.engine.spec import DecisionPlan
from app.llm import usage
from app.llm.base import ComposeInput, LLMOutputError, LLMUnavailableError, PromptChunk
from app.llm.gemini_client import GeminiLLM, retry_hint
from app.llm.retry import with_backoff

PLAN = {
    "user_facts": [{"name": "gpa", "type": "number", "value": 3.6}],
    "decisions": [
        # Gemini's flattened schema: branch-specific fields arrive as null on the other branch.
        {
            "id": "d1",
            "check": "fact",
            "fact": "gpa",
            "op": ">=",
            "value": 3.5,
            "hypothesis": None,
            "source_chunk": "c1",
            "label": "GPA at least 3.5",
            "rule": "GPA of at least 3.5.",
        },
        {
            "id": "d2",
            "check": "nli",
            "fact": None,
            "op": None,
            "value": None,
            "hypothesis": "Remote work is allowed on Fridays.",
            "source_chunk": "c1",
            "label": "Fridays allowed",
            "rule": "Remote work is allowed on Fridays.",
        },
    ],
    "combine": "ALL",
}
CHUNKS = [
    PromptChunk("c1", "Scholarship_Rules.pdf", 2, "Applicants must hold a GPA of at least 3.5.")
]


def response(text: str | None, finish: str = "STOP", block_reason=None):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=types.FinishReason[finish])],
        prompt_feedback=SimpleNamespace(block_reason=block_reason) if block_reason else None,
        model_version="gemini-3.6-flash",
        usage_metadata=SimpleNamespace(
            prompt_token_count=1500,
            candidates_token_count=200,
            thoughts_token_count=120,
            cached_content_token_count=500,
        ),
    )


def rate_limited(delay: str | None = None) -> errors.ClientError:
    details = (
        [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]
        if delay
        else []
    )
    return errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded",
                "details": details,
            }
        },
    )


class StubModels:
    def __init__(self, *results):
        self.results = list(results)
        self.requests: list[dict] = []

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


def client_with(*results, **settings) -> tuple[GeminiLLM, StubModels]:
    s = get_settings().model_copy(
        update={"llm_provider": "gemini", "llm_retry_base_seconds": 0.01, **settings}
    )
    llm = GeminiLLM(s)
    stub = StubModels(*results)
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=stub))  # type: ignore[assignment]
    return llm, stub


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.llm.retry.asyncio.sleep", fake_sleep)
    return slept


async def test_decompose_request_shape_parsing_and_usage():
    llm, stub = client_with(response(json.dumps(PLAN)))
    with usage.metered() as meter:
        plan = await llm.decompose("Am I eligible with GPA 3.6?", CHUNKS)
    assert isinstance(plan, DecisionPlan)
    assert [d.check for d in plan.decisions] == ["fact", "nli"]  # nulls on the other branch ignored
    (req,) = stub.requests
    assert req["model"] == "gemini-3.6-flash"  # provider default when LLM_MODEL is empty
    cfg = req["config"]
    assert cfg.response_mime_type == "application/json"
    assert "anyOf" not in json.dumps(cfg.response_json_schema)
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM  # decompose effort
    assert cfg.system_instruction.startswith("You turn a visitor's question")
    assert (
        '<document ref="c1" file="Scholarship_Rules.pdf" page="2">'
        in req["contents"][0].parts[0].text
    )
    (call,) = meter.calls
    assert (call.method, call.input_tokens, call.output_tokens) == ("decompose", 1000, 320)
    assert call.cache_read_input_tokens == 500 and call.stop_reason == "STOP"


async def test_retry_is_append_only_previous_plan_then_errors():
    llm, stub = client_with(response(json.dumps(PLAN)))
    previous = DecisionPlan.model_validate(PLAN)
    await llm.decompose("q", CHUNKS, feedback=["d1: value 3.7 does not appear"], previous=previous)
    roles = [c.role for c in stub.requests[0]["contents"]]
    assert roles == ["user", "model", "user"]
    assert "value 3.7 does not appear" in stub.requests[0]["contents"][2].parts[0].text


async def test_compose_uses_low_thinking_and_no_schema():
    llm, stub = client_with(response("Yes, you're eligible."))
    data = ComposeInput(
        question="q",
        route="decision",
        outcome="answered",
        overall="TRUE",
        combine="ALL",
        verdicts=[],
        chunks=CHUNKS,
        org_name="Riverside",
        missing_facts=[],
    )
    assert await llm.compose(data) == "Yes, you're eligible."
    cfg = stub.requests[0]["config"]
    assert cfg.response_json_schema is None and cfg.response_mime_type is None
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW


async def test_non_gemini3_model_gets_no_thinking_level():
    llm, stub = client_with(response("ok"), llm_model="gemini-2.5-flash")
    await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert stub.requests[0]["config"].thinking_config is None


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (response("{}", finish="SAFETY"), LLMUnavailableError),
        (response("{}", block_reason="PROHIBITED_CONTENT"), LLMUnavailableError),
        (response('{"user_facts": [', finish="MAX_TOKENS"), LLMOutputError),
        (response(None), LLMOutputError),
        (response("not json"), LLMOutputError),
        (response(json.dumps({"decisions": [{"id": "d1", "check": "regex"}]})), LLMOutputError),
        (
            errors.ClientError(
                400, {"error": {"code": 400, "message": "bad", "status": "INVALID"}}
            ),
            LLMUnavailableError,
        ),
        (
            errors.ClientError(403, {"error": {"code": 403, "message": "key", "status": "DENIED"}}),
            LLMUnavailableError,
        ),
    ],
)
async def test_failures_map_to_llm_errors(result, error):
    llm, _ = client_with(result)
    with pytest.raises(error):
        await llm.decompose("q", CHUNKS)


# --- 429 backoff ---------------------------------------------------------------------------------


async def test_429_is_retried_with_retry_info_delay(no_sleep):
    llm, stub = client_with(rate_limited("3s"), rate_limited(), response(json.dumps(PLAN)))
    plan = await llm.decompose("q", CHUNKS)
    assert len(plan.decisions) == 2 and len(stub.requests) == 3
    assert 3.0 <= no_sleep[0] < 3.01  # RetryInfo hint (+ small jitter)
    assert 0.02 <= no_sleep[1] < 0.03  # exponential: base 0.01 * 2^1 (+ jitter)


async def test_5xx_is_retried_too(no_sleep):
    server = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    llm, stub = client_with(server, response("ok"))
    assert (
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
        == "ok"
    )
    assert len(stub.requests) == 2


async def test_429_gives_up_after_retries(no_sleep):
    llm, stub = client_with(rate_limited(), llm_rate_limit_retries=2)
    with pytest.raises(LLMUnavailableError, match="rate limited"):
        await llm.decompose("q", CHUNKS)
    assert len(stub.requests) == 3 and len(no_sleep) == 2


async def test_backoff_respects_total_wait_cap(no_sleep):
    llm, stub = client_with(rate_limited("30s"), response("ok"), llm_retry_max_wait_seconds=10)
    with pytest.raises(LLMUnavailableError):
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert no_sleep == [] and len(stub.requests) == 1  # a 30 s wait would exceed the 10 s cap


async def test_with_backoff_does_not_retry_other_errors(no_sleep):
    calls = 0

    async def boom():
        nonlocal calls
        calls += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        await with_backoff(boom, classify=retry_hint, retries=3, base_seconds=1, max_total_wait=60)
    assert calls == 1 and no_sleep == []


def test_retry_hint_parsing():
    assert retry_hint(rate_limited("17s")) == (True, 17.0)
    assert retry_hint(rate_limited()) == (True, None)
    assert retry_hint(errors.ClientError(404, {"error": {"code": 404}})) == (False, None)
    assert retry_hint(RuntimeError()) == (False, None)


async def test_usage_is_recorded_even_when_blocked():
    llm, _ = client_with(response("", finish="SAFETY"))
    with usage.metered() as meter, pytest.raises(LLMUnavailableError):
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert meter.calls[0].stop_reason == "SAFETY"


# --- Deadline and daily quota (2026-11-05: gemini-3.8-flash timed out per attempt) ---------------


def daily_quota() -> errors.ClientError:
    return errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "per day",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "42456s"},
                ],
            }
        },
    )


class HangingModels(StubModels):
    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        await asyncio.Event().wait()  # never returns (asyncio.sleep is patched in these tests)


async def test_hung_provider_fails_within_the_call_deadline():
    import time

    llm, _ = client_with(response("unused"), llm_call_deadline_seconds=0.3)
    stub = HangingModels(response("unused"))
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=stub))  # type: ignore[assignment]
    start = time.monotonic()
    with pytest.raises(LLMUnavailableError, match="took longer than"):
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert time.monotonic() - start < 2  # bounded by the deadline, not by retries x timeouts
    assert len(stub.requests) == 1


async def test_daily_quota_is_not_retried_and_raises_quota_error(no_sleep):
    from app.llm.base import LLMQuotaExhaustedError

    llm, stub = client_with(daily_quota(), response("never reached"))
    with pytest.raises(LLMQuotaExhaustedError):
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert len(stub.requests) == 1 and no_sleep == []
    assert retry_hint(daily_quota()) == (False, None)
