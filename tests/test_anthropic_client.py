"""AnthropicLLM with the SDK stubbed out: request shape, parsing, usage, error mapping.
No network (CLAUDE.md: no real API calls in tests)."""

import json
from types import SimpleNamespace

import anthropic
import pytest

from app.config import get_settings
from app.engine.spec import DecisionPlan
from app.llm import usage
from app.llm.anthropic_client import FALLBACK_BETA, AnthropicLLM
from app.llm.base import ComposeInput, LLMOutputError, LLMUnavailableError, PromptChunk

PLAN = {
    "user_facts": [{"name": "gpa", "type": "number", "value": 3.6}],
    "decisions": [
        {
            "id": "d1",
            "check": "fact",
            "fact": "gpa",
            "op": ">=",
            "value": 3.5,
            "source_chunk": "c1",
            "label": "GPA at least 3.5",
            "rule": "GPA of at least 3.5.",
        }
    ],
    "combine": "ALL",
}
CHUNKS = [
    PromptChunk("c1", "Scholarship_Rules.pdf", 2, "Applicants must hold a GPA of at least 3.5.")
]


def response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=300,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=None,
        ),
    )


class StubMessages:
    def __init__(self, result):
        self.result = result
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_with(result) -> tuple[AnthropicLLM, StubMessages]:
    llm = AnthropicLLM(get_settings().model_copy(update={"llm_provider": "anthropic"}))
    stub = StubMessages(result)
    llm._client = SimpleNamespace(beta=SimpleNamespace(messages=stub))  # type: ignore[assignment]
    return llm, stub


async def test_decompose_request_shape_parsing_and_usage():
    llm, stub = client_with(response(json.dumps(PLAN)))
    with usage.metered() as meter:
        plan = await llm.decompose("Am I eligible with GPA 3.6?", CHUNKS)
    assert isinstance(plan, DecisionPlan) and plan.decisions[0].value == 3.5
    (req,) = stub.requests
    s = get_settings()
    assert req["model"] == "claude-sonnet-5-5"  # provider default when LLM_MODEL is empty
    assert req["betas"] == [FALLBACK_BETA] and req["fallbacks"] == "default"
    assert req["output_config"]["effort"] == s.llm_effort_decompose
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in req and "temperature" not in req
    assert (
        '<document ref="c1" file="Scholarship_Rules.pdf" page="2">' in req["messages"][0]["content"]
    )
    (call,) = meter.calls
    assert (call.method, call.input_tokens, call.output_tokens) == ("decompose", 1200, 300)
    assert call.cache_read_input_tokens == 800 and call.cache_creation_input_tokens == 0


async def test_retry_is_append_only_previous_plan_then_errors():
    llm, stub = client_with(response(json.dumps(PLAN)))
    previous = DecisionPlan.model_validate(PLAN)
    await llm.decompose("q", CHUNKS, feedback=["d1: value 3.7 does not appear"], previous=previous)
    roles = [m["role"] for m in stub.requests[0]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert "value 3.7 does not appear" in stub.requests[0]["messages"][2]["content"]


async def test_compose_uses_low_effort_and_no_schema():
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
    req = stub.requests[0]
    assert req["output_config"] == {"effort": get_settings().llm_effort_compose}


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (response("{}", stop_reason="refusal"), LLMUnavailableError),
        (response('{"user_facts": [', stop_reason="max_tokens"), LLMOutputError),
        (response("not json"), LLMOutputError),
        (response(json.dumps({"decisions": [{"id": "d1", "check": "regex"}]})), LLMOutputError),
        (anthropic.APIConnectionError(request=None), LLMUnavailableError),  # type: ignore[arg-type]
    ],
)
async def test_failures_map_to_llm_errors(result, error):
    llm, _ = client_with(result)
    with pytest.raises(error):
        await llm.decompose("q", CHUNKS)


async def test_usage_is_recorded_even_when_the_call_is_refused():
    llm, _ = client_with(response("", stop_reason="refusal"))
    with usage.metered() as meter, pytest.raises(LLMUnavailableError):
        await llm.compose(ComposeInput("q", "direct", "answered", None, None, [], CHUNKS, "o", []))
    assert meter.calls[0].stop_reason == "refusal"
