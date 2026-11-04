"""Result types shared by the engine and the API (docs/ai-design.md §11, docs/api-contracts.md)."""

from typing import Literal

from pydantic import BaseModel, Field

VerdictValue = Literal["TRUE", "FALSE", "UNKNOWN"]
VerdictKind = Literal["fact", "nli", "policy", "choice", "score"]
Route = Literal["direct", "procedural", "policy", "decision", "comparison"]
Outcome = Literal["answered", "unanswered", "needs_info", "review"]


class Source(BaseModel):
    file: str
    page: int
    excerpt: str = Field(description="Cut from the cited chunk by code, never written by the LLM")


class Verdict(BaseModel):
    id: str
    kind: VerdictKind
    label: str = Field(description="Short plain-language condition shown in the evidence trail")
    rule: str | None = None
    value: VerdictValue
    confidence: float
    user_value: float | bool | str | None = None
    missing_fact: str | None = Field(
        default=None, description="Set when UNKNOWN for lack of a fact"
    )
    source: Source | None = None
    reason: str | None = Field(default=None, description="Why UNKNOWN (model error, timeout, …)")
    detail: str | None = Field(default=None, description="Extra display text, e.g. 'INR 32,000'")


class Reference(BaseModel):
    file: str
    page: int


class AskResult(BaseModel):
    answer: str
    outcome: Outcome
    references: list[Reference]
    route: Route | None
    verdicts: list[Verdict]
    timings_ms: dict[str, int | dict[str, int]]
    overall: VerdictValue | None = Field(
        default=None, description="Combined result for decision/policy/comparison paths"
    )
    confidence: float | None = Field(
        default=None, description="Min confidence of the deciding verdicts (decision path)"
    )
    answer_source: Literal["llm", "template", "none"] = "llm"
