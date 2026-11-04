"""FakeLLMClient: no network. Used by tests (scripted) and when LLM_PROVIDER=fake (degraded).

Scripted mode: tests pass plans/answers keyed by question. Unscripted:
- decompose → no decisions (the pipeline falls through to a grounded answer)
- decompose_comparison → raises (the pipeline falls back to the decision path)
- compose → an extractive answer: the most relevant sentences of the top documents, so the app
  is usable for demos of retrieval and the UI before an API key exists.
"""

import re
from dataclasses import dataclass, field

from app.engine.excerpt import best_excerpt
from app.engine.spec import ComparisonPlan, DecisionPlan, ExtractedValues
from app.llm.base import ComposeInput, LLMOutputError, LLMUnavailableError, PromptChunk


@dataclass
class FakeLLMClient:
    plans: dict[str, DecisionPlan | list[DecisionPlan]] = field(default_factory=dict)
    comparison_plans: dict[str, ComparisonPlan] = field(default_factory=dict)
    extracted: dict[str, ExtractedValues] = field(default_factory=dict)  # keyed by criterion
    answers: dict[str, str] = field(default_factory=dict)
    fail: set[str] = field(default_factory=set)  # method names that raise LLMUnavailableError
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _check(self, method: str, payload: object) -> None:
        self.calls.append((method, payload))
        if method in self.fail:
            raise LLMUnavailableError(f"fake {method} failure")

    async def decompose(
        self,
        question: str,
        chunks: list[PromptChunk],
        feedback: list[str] | None = None,
        previous: DecisionPlan | None = None,
    ) -> DecisionPlan:
        self._check("decompose", {"question": question, "feedback": feedback})
        scripted = self.plans.get(question)
        if isinstance(scripted, list):  # successive attempts (first try, retry)
            attempt = (
                sum(
                    1
                    for m, p in self.calls
                    if m == "decompose" and isinstance(p, dict) and p["question"] == question
                )
                - 1
            )
            return scripted[min(attempt, len(scripted) - 1)]
        return scripted or DecisionPlan()

    async def decompose_comparison(
        self, question: str, chunks: list[PromptChunk]
    ) -> ComparisonPlan:
        self._check("decompose_comparison", question)
        if question not in self.comparison_plans:
            raise LLMOutputError("no scripted comparison plan")
        return self.comparison_plans[question]

    async def extract_comparison_values(
        self, plan: ComparisonPlan, chunks_by_option: dict[str, list[PromptChunk]]
    ) -> ExtractedValues:
        self._check("extract_comparison_values", plan)
        return self.extracted.get(plan.criterion, ExtractedValues(values=[]))

    async def compose(self, data: ComposeInput) -> str:
        self._check("compose", data)
        if data.question in self.answers:
            return self.answers[data.question]
        return extractive_answer(data)


_STEP = re.compile(r"^\d+\.\s")


def extractive_answer(data: ComposeInput) -> str:
    """Best-matching document sentences; numbered steps kept in order for procedures."""
    if not data.chunks:
        return "The documents don't cover this."
    if data.route == "procedural":
        steps = [ln for ln in data.chunks[0].text.splitlines() if _STEP.match(ln)]
        if steps:
            return "\n".join(steps)
    return best_excerpt(data.chunks[0].text, data.question, 400)
