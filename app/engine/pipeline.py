"""The ask pipeline (docs/architecture.md "Ask flow", docs/ai-design.md).

    gather(classify, retrieve) → groundedness gate (per route) → route:
      direct / procedural → compose from chunks
      policy              → pattern hypothesis → NLI on top chunks      (no LLM before compose)
      decision            → decompose → validate + ground → parallel checks → combine
      comparison          → comparison decompose → per-option retrieval → extract → code compares
    → compose (LLM) → AskResult

The LLM is used only in the decompose step and compose(). Every verdict comes from System 1 models
or code. `org_id` must come from a validated credential.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.config import Settings
from app.engine import comparison as cmp
from app.engine.combine import combine, combined_confidence, outcome_for
from app.engine.executors import execute
from app.engine.policy import check_policy, policy_hypothesis
from app.engine.spec import DecisionPlan
from app.engine.template import template_answer
from app.engine.types import AskResult, Outcome, Reference, Route, Verdict, VerdictValue
from app.engine.validate import ValidationReport, ground_rules, semantic_check
from app.llm.base import ComposeInput, LLMClient, LLMOutputError, LLMUnavailableError, PromptChunk
from app.ml.classifier import QuestionClassifier
from app.ml.embedder import Embedder
from app.ml.nli import Nli
from app.ml.reranker import Reranker
from app.retrieval.search import RetrievedChunk, gate_threshold, passes_gate, retrieve


class AnswerUnavailableError(Exception):
    """No answer could be produced (the LLM failed and there were no verdicts to fall back on)."""


@dataclass
class EngineDeps:
    pool: asyncpg.Pool
    embedder: Embedder
    reranker: Reranker
    nli: Nli
    classifier: QuestionClassifier
    llm: LLMClient
    settings: Settings


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def prompt_chunks(
    chunks: list[RetrievedChunk], start: int = 1
) -> tuple[list[PromptChunk], dict[str, RetrievedChunk]]:
    refs = {f"c{i}": c for i, c in enumerate(chunks, start=start)}
    return [PromptChunk(r, c.filename, c.page, c.text) for r, c in refs.items()], refs


def _dedupe_refs(pairs: list[tuple[str, int]], limit: int) -> list[Reference]:
    seen: list[tuple[str, int]] = []
    for p in pairs:
        if p not in seen:
            seen.append(p)
    return [Reference(file=f, page=p) for f, p in seen[:limit]]


def _verdict_refs(verdicts: list[Verdict], limit: int) -> list[Reference]:
    return _dedupe_refs([(v.source.file, v.source.page) for v in verdicts if v.source], limit)


class _Run:
    """One question's run: shared inputs and the timings collected along the way."""

    def __init__(self, deps: EngineDeps, org_id: UUID, org_name: str, question: str) -> None:
        self.d = deps
        self.s = deps.settings
        self.org_id = org_id
        self.org_name = org_name
        self.q = question
        self.timings: dict[str, Any] = {}

    # --- shared steps ---------------------------------------------------------------------------

    def chunk_refs(self, chunks: list[RetrievedChunk], route: str) -> list[Reference]:
        """References for a grounded answer: chunks that clear the route's gate (at least one)."""
        threshold = gate_threshold(self.s, route)
        good = [c for c in chunks if c.rerank_score >= threshold] or chunks[:1]
        return _dedupe_refs([(c.filename, c.page) for c in good], self.s.references_max)

    async def compose(self, data: ComposeInput) -> str:
        t = time.perf_counter()
        try:
            return await self.d.llm.compose(data)
        finally:
            self.timings["compose"] = _ms(t)

    def result(
        self,
        *,
        answer: str,
        outcome: Outcome,
        references: list[Reference],
        route: Route | None,
        verdicts: list[Verdict],
        overall: VerdictValue | None = None,
        source: str = "llm",
    ) -> AskResult:
        return AskResult(
            answer=answer,
            outcome=outcome,
            references=references,
            route=route,
            verdicts=verdicts,
            timings_ms=self.timings,
            overall=overall,
            answer_source=source,  # type: ignore[arg-type]
        )

    def unanswered(self) -> AskResult:
        return self.result(
            answer=f"The documents for {self.org_name} don't cover this.",
            outcome="unanswered",
            references=[],
            route=None,
            verdicts=[],
            source="none",
        )

    async def answer_or_template(
        self, data: ComposeInput, *, references: list[Reference], route: Route
    ) -> AskResult:
        """Compose with the LLM; if that fails, fall back to a code-built answer from verdicts."""
        try:
            text, source = await self.compose(data), "llm"
        except LLMUnavailableError as exc:
            if not data.verdicts or data.overall is None:
                raise AnswerUnavailableError(str(exc)) from exc
            text, source = (
                template_answer(
                    route, data.overall, data.verdicts, combine=data.combine, winner=data.winner
                ),
                "template",
            )
        return self.result(
            answer=text,
            outcome=data.outcome,
            references=references,  # type: ignore[arg-type]
            route=route,
            verdicts=data.verdicts,
            overall=data.overall,
            source=source,
        )

    # --- paths ----------------------------------------------------------------------------------

    async def grounded(
        self, chunks: list[RetrievedChunk], route: Route, outcome: Outcome = "answered"
    ) -> AskResult:
        pchunks, _ = prompt_chunks(chunks)
        data = ComposeInput(
            question=self.q,
            route=route,
            outcome=outcome,
            overall=None,
            combine=None,
            verdicts=[],
            chunks=pchunks,
            org_name=self.org_name,
            missing_facts=[],
        )
        return await self.answer_or_template(
            data, references=self.chunk_refs(chunks, route), route=route
        )

    async def policy(self, chunks: list[RetrievedChunk], hypothesis: str) -> AskResult:
        t = time.perf_counter()
        verdict, chunk = await check_policy(hypothesis, chunks, self.d.nli, self.s)
        self.timings["decisions"] = {"p1": _ms(t)}
        outcome: Outcome = "answered" if verdict.value != "UNKNOWN" else "review"
        refs = (
            _verdict_refs([verdict], self.s.references_max)
            if chunk
            else self.chunk_refs(chunks, "policy")
        )
        pchunks, _ = prompt_chunks(chunks[: self.s.policy_chunks_checked])
        data = ComposeInput(
            question=self.q,
            route="policy",
            outcome=outcome,
            overall=verdict.value,
            combine=None,
            verdicts=[verdict],
            chunks=pchunks,
            org_name=self.org_name,
            missing_facts=[],
        )
        return await self.answer_or_template(data, references=refs, route="policy")

    async def _decompose(
        self, pchunks: list[PromptChunk], refs: dict[str, RetrievedChunk]
    ) -> tuple[DecisionPlan | None, ValidationReport]:
        """Decompose, validate, ground; one retry with the errors fed back."""
        llm, s = self.d.llm, self.s
        plan: DecisionPlan | None = None
        report = ValidationReport()
        attempts = 0
        grounding_ms = 0
        t = time.perf_counter()
        while True:
            attempts += 1
            try:
                if plan is not None and report.errors:
                    new_plan = await llm.decompose(
                        self.q, pchunks, feedback=report.errors, previous=plan
                    )
                else:
                    new_plan = await llm.decompose(self.q, pchunks)
            except LLMOutputError:
                new_plan = None  # malformed output: retry fresh if allowed
            except LLMUnavailableError:
                break
            if new_plan is not None:
                plan = new_plan
                g = time.perf_counter()
                report = await ground_rules(
                    semantic_check(plan, refs), self.d.nli, s.rule_grounding_threshold
                )
                grounding_ms += _ms(g)
                if not report.errors:
                    break
            if attempts > s.decompose_max_retries:
                break
        self.timings["decompose"] = _ms(t) - grounding_ms
        self.timings["grounding"] = grounding_ms
        return plan, report

    async def decision(self, chunks: list[RetrievedChunk]) -> AskResult:
        pchunks, refs = prompt_chunks(chunks)
        plan, report = await self._decompose(pchunks, refs)

        if plan is not None and not plan.decisions and not report.errors:
            # The decomposer judged this not to be a rule-based decision, so the looser decision
            # gate no longer applies: answer from the chunks only if they clear the strict gate.
            if chunks[0].rerank_score < gate_threshold(self.s, None):
                return self.unanswered()
            return await self.grounded(chunks, "decision")
        if not report.valid:
            # No valid plan (still invalid after the retry, or the LLM was unavailable): grounded
            # answer, flagged for review.
            return await self.grounded(chunks, "decision", outcome="review")

        assert plan is not None
        verdicts, dtimings = await execute(report.valid, plan.facts(), self.d.nli, self.s)
        self.timings["decisions"] = dtimings
        overall = combine([v.value for v in verdicts], plan.combine)
        outcome = outcome_for(overall, verdicts)
        data = ComposeInput(
            question=self.q,
            route="decision",
            outcome=outcome,
            overall=overall,
            combine=plan.combine,
            verdicts=verdicts,
            chunks=pchunks,
            org_name=self.org_name,
            missing_facts=[v.label for v in verdicts if v.missing_fact],
        )
        result = await self.answer_or_template(
            data, references=_verdict_refs(verdicts, self.s.references_max), route="decision"
        )
        result.confidence = combined_confidence(verdicts, overall)
        return result

    async def comparison(self, chunks: list[RetrievedChunk]) -> AskResult:
        llm, s = self.d.llm, self.s
        pchunks, _ = prompt_chunks(chunks)
        t = time.perf_counter()
        try:
            plan = await llm.decompose_comparison(self.q, pchunks)
        except LLMUnavailableError:
            plan = None
        if plan is None or len(set(plan.options)) < 2:
            self.timings["decompose"] = _ms(t)
            return await self.decision(chunks)  # not a usable comparison

        async def for_option(option: str) -> list[RetrievedChunk]:
            r = await retrieve(
                self.d.pool,
                self.d.embedder,
                self.d.reranker,
                s,
                org_id=self.org_id,
                query=f"{option} {plan.criterion}",
                top_k=s.comparison_chunks_per_option,
            )
            return r.chunks

        per_option = dict(
            zip(
                plan.options,
                await asyncio.gather(*(for_option(o) for o in plan.options)),
                strict=True,
            )
        )
        refs_by_option: dict[str, dict[str, RetrievedChunk]] = {}
        prompts_by_option: dict[str, list[PromptChunk]] = {}
        n = 1
        for option, found in per_option.items():
            prompts_by_option[option], refs_by_option[option] = prompt_chunks(found, start=n)
            n += len(found)

        values: dict[str, cmp.OptionValue] = {}
        try:
            extracted = await llm.extract_comparison_values(plan, prompts_by_option)
            values, _errors = cmp.validate_values(plan, extracted.values, refs_by_option)
        except LLMUnavailableError:
            pass
        self.timings["decompose"] = _ms(t)

        t = time.perf_counter()
        if values:
            result = cmp.decide_numeric(plan, values, s)
        else:
            result = await cmp.decide_by_nli(plan, per_option, self.d.nli, s)
        self.timings["decisions"] = {"compare": _ms(t)}

        overall: VerdictValue = "TRUE" if result.winner else "UNKNOWN"
        outcome: Outcome = "answered" if result.winner else "review"
        evidence = result.chunks or [c for found in per_option.values() for c in found[:1]]
        context, _ = prompt_chunks(evidence)
        data = ComposeInput(
            question=self.q,
            route="comparison",
            outcome=outcome,
            overall=overall,
            combine=None,
            verdicts=result.verdicts,
            chunks=context,
            org_name=self.org_name,
            missing_facts=[],
            winner=result.winner,
        )
        refs = _dedupe_refs([(c.filename, c.page) for c in evidence], s.references_max)
        return await self.answer_or_template(data, references=refs, route="comparison")


async def answer_question(
    deps: EngineDeps, *, org_id: UUID, org_name: str, question: str
) -> AskResult:
    run = _Run(deps, org_id, org_name, question)
    s = deps.settings
    start = time.perf_counter()

    async def classify():
        t = time.perf_counter()
        c = await asyncio.to_thread(deps.classifier.classify, question)
        run.timings["classify"] = _ms(t)
        return c

    async def find():
        t = time.perf_counter()
        r = await retrieve(
            deps.pool, deps.embedder, deps.reranker, s, org_id=org_id, query=question
        )
        run.timings["retrieve"] = _ms(t)
        return r

    classification, retrieval = await asyncio.gather(classify(), find())
    confident = classification.probability >= s.router_confidence_threshold
    route: Route = classification.label if confident else "decision"  # type: ignore[assignment]

    # Safeguard: the looser decision gate is earned only by a *confident* decision label. A
    # low-confidence question still takes the decision path (safest for multi-condition
    # questions) but must clear the strict gate, so a misrouted short question can't slip
    # through on the looser threshold (Q17 in the task 04 eval).
    gate_route = classification.label if confident else None
    if not passes_gate(retrieval, s, gate_route):
        run.timings["total"] = _ms(start)
        return run.unanswered()

    chunks = retrieval.chunks
    if route in ("direct", "procedural"):
        result = await run.grounded(chunks, route)
    elif route == "policy":
        hypothesis = policy_hypothesis(question)
        result = await run.policy(chunks, hypothesis) if hypothesis else await run.decision(chunks)
    elif route == "comparison":
        result = await run.comparison(chunks)
    else:
        result = await run.decision(chunks)
    run.timings["total"] = _ms(start)
    result.timings_ms = run.timings
    return result
