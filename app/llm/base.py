"""The LLM's only jobs: the decompose step and compose() (CLAUDE.md, ADRs 0003 and 0009).

Inputs are passed as labelled chunks (refs "c1", "c2", …) so the LLM can cite them and code can
check every citation. Implementations raise LLMUnavailableError when no answer could be had
(network, rate limit, timeout, refusal, malformed output after the SDK's retries).
"""

from dataclasses import dataclass
from typing import Protocol

from app.engine.spec import ComparisonPlan, DecisionPlan, ExtractedValues
from app.engine.types import Verdict, VerdictValue


class LLMUnavailableError(Exception):
    """The LLM couldn't produce a usable response."""


class LLMOutputError(LLMUnavailableError):
    """The LLM responded, but not with output matching the requested schema."""


class LLMQuotaExhaustedError(LLMUnavailableError):
    """The provider's daily (or longer) quota is used up: retrying now can't help."""


@dataclass(frozen=True)
class PromptChunk:
    ref: str  # "c1"
    file: str
    page: int
    text: str


@dataclass(frozen=True)
class ComposeInput:
    question: str
    route: str  # direct | procedural | policy | decision | comparison
    outcome: str  # answered | needs_info | review
    overall: VerdictValue | None
    combine: str | None  # ALL | ANY for decisions
    verdicts: list[Verdict]
    chunks: list[PromptChunk]
    org_name: str
    missing_facts: list[str]  # labels of the conditions that need a fact from the user
    winner: str | None = None  # comparison


class LLMClient(Protocol):
    async def decompose(
        self,
        question: str,
        chunks: list[PromptChunk],
        feedback: list[str] | None = None,
        previous: DecisionPlan | None = None,
    ) -> DecisionPlan: ...

    async def decompose_comparison(
        self, question: str, chunks: list[PromptChunk]
    ) -> ComparisonPlan: ...

    async def extract_comparison_values(
        self, plan: ComparisonPlan, chunks_by_option: dict[str, list[PromptChunk]]
    ) -> ExtractedValues: ...

    async def compose(self, data: ComposeInput) -> str: ...
