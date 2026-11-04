"""Validate a decision plan from the LLM (docs/ai-design.md §8, ADR 0008).

1. Schema: Pydantic (DecisionPlan) — done by the caller when parsing.
2. Semantic checks (code): cited chunk retrieved, value present in it, fact types and ops agree.
3. Rule grounding (System 1 NLI): the cited chunk must entail each fact check's `rule`.

Invalid specs are dropped and their errors returned, so the caller can retry once with them.
"""

import asyncio
from dataclasses import dataclass, field

from app.engine.normalize import string_in_text, value_in_text
from app.engine.spec import EQUALITY_OPS, DecisionPlan, FactCheck, NliCheck
from app.ml.nli import Nli
from app.retrieval.search import RetrievedChunk


@dataclass
class ValidSpec:
    spec: FactCheck | NliCheck
    chunk: RetrievedChunk
    grounding: float | None = None  # entailment probability of `rule` (fact checks)


@dataclass
class ValidationReport:
    valid: list[ValidSpec] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _value_type(value: float | bool | str) -> str:
    if isinstance(value, bool):  # before numbers: bool is an int subclass
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "string"


def semantic_check(plan: DecisionPlan, chunks: dict[str, RetrievedChunk]) -> ValidationReport:
    report = ValidationReport()
    facts = plan.facts()
    seen_ids: set[str] = set()

    for fact in plan.user_facts:
        if _value_type(fact.value) != fact.type:
            report.errors.append(
                f"user_facts.{fact.name}: declared type {fact.type} but value "
                f"{fact.value!r} is a {_value_type(fact.value)}"
            )

    for spec in plan.decisions:
        where = f"{spec.id}"
        problems: list[str] = []
        if spec.id in seen_ids:
            problems.append("duplicate id")
        seen_ids.add(spec.id)
        chunk = chunks.get(spec.source_chunk)
        if chunk is None:
            problems.append(
                f"source_chunk {spec.source_chunk!r} was not among the retrieved chunks "
                f"({', '.join(chunks)})"
            )
        if not spec.rule.strip():
            problems.append("rule is empty")
        if not spec.label.strip():
            problems.append("label is empty")

        if isinstance(spec, FactCheck):
            vtype = _value_type(spec.value)
            declared = facts.get(spec.fact)
            if declared is not None and declared.type != vtype:
                problems.append(
                    f"fact {spec.fact!r} is a {declared.type} but the check compares it with "
                    f"a {vtype} ({spec.value!r})"
                )
            if vtype != "number" and spec.op not in EQUALITY_OPS:
                problems.append(f"op {spec.op!r} is not allowed for a {vtype}; use == or !=")
            if chunk is not None:
                if vtype == "number" and not value_in_text(float(spec.value), chunk.text):
                    problems.append(
                        f"value {spec.value} does not appear in the text of {spec.source_chunk}"
                    )
                if vtype == "string" and not string_in_text(str(spec.value), chunk.text):
                    problems.append(
                        f"value {spec.value!r} does not appear in the text of {spec.source_chunk}"
                    )
        elif not spec.hypothesis.strip():
            problems.append("hypothesis is empty")

        if problems:
            report.errors.extend(f"{where}: {p}" for p in problems)
        else:
            assert chunk is not None
            report.valid.append(ValidSpec(spec=spec, chunk=chunk))
    return report


async def ground_rules(report: ValidationReport, nli: Nli, threshold: float) -> ValidationReport:
    """Drop fact checks whose cited chunk doesn't entail their `rule` (System 1 NLI)."""
    fact_specs = [v for v in report.valid if isinstance(v.spec, FactCheck)]
    if not fact_specs:
        return report
    results = await asyncio.to_thread(
        nli.predict, [(v.chunk.text, v.spec.rule) for v in fact_specs]
    )
    kept: list[ValidSpec] = [v for v in report.valid if isinstance(v.spec, NliCheck)]
    errors = list(report.errors)
    for v, r in zip(fact_specs, results, strict=True):
        v.grounding = r.entailment
        if r.entailment >= threshold:
            kept.append(v)
        else:
            errors.append(
                f"{v.spec.id}: rule not supported by the cited chunk {v.spec.source_chunk} "
                f"(state the rule as the document writes it, and cite the chunk that says it)"
            )
    order = {id(v): i for i, v in enumerate(report.valid)}
    kept.sort(key=lambda v: order[id(v)])
    return ValidationReport(valid=kept, errors=errors)
