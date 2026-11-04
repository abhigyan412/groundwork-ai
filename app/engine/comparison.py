"""Comparison path, decided by code (docs/ai-design.md §6, ADR 0009).

The LLM proposes options/criterion/direction and extracts one cited value per option; code checks
each value appears in its cited chunk and compares. Without numbers, NLI scores each option.
"""

import asyncio
from dataclasses import dataclass

from app.config import Settings
from app.engine.excerpt import anchor_sentence, best_excerpt
from app.engine.normalize import format_number, value_in_text
from app.engine.spec import ComparisonPlan, ExtractedValue
from app.engine.types import Source, Verdict, VerdictValue
from app.ml.nli import Nli
from app.retrieval.search import RetrievedChunk


@dataclass
class OptionValue:
    option: str
    value: float
    unit: str | None
    chunk: RetrievedChunk


@dataclass
class ComparisonResult:
    verdicts: list[Verdict]
    winner: str | None  # None: the documents don't clearly answer it
    method: str  # "numeric" | "nli"
    chunks: list[RetrievedChunk]  # evidence used, for references
    errors: list[str]


def validate_values(
    plan: ComparisonPlan,
    extracted: list[ExtractedValue],
    chunks_by_option: dict[str, dict[str, RetrievedChunk]],
) -> tuple[dict[str, OptionValue], list[str]]:
    """Keep values whose cited chunk was retrieved *for that option* and contains the number."""
    valid: dict[str, OptionValue] = {}
    errors: list[str] = []
    for ev in extracted:
        if ev.option not in plan.options:
            errors.append(f"{ev.option!r} is not one of the options {plan.options}")
            continue
        if ev.value is None:
            continue
        refs = chunks_by_option.get(ev.option, {})
        chunk = refs.get(ev.source_chunk or "")
        if chunk is None:
            errors.append(
                f"{ev.option}: source_chunk {ev.source_chunk!r} was not retrieved for this option"
            )
            continue
        if not value_in_text(ev.value, chunk.text):
            errors.append(f"{ev.option}: value {ev.value} does not appear in {ev.source_chunk}")
            continue
        if ev.option in valid:
            errors.append(f"{ev.option}: more than one value")
            continue
        unit = " ".join(ev.unit.lower().split()) if ev.unit else None
        valid[ev.option] = OptionValue(ev.option, ev.value, unit, chunk)
    return valid, errors


def decide_numeric(
    plan: ComparisonPlan, values: dict[str, OptionValue], settings: Settings
) -> ComparisonResult:
    """Every option needs a value in the same unit; best by `better`; a tie is unclear."""
    errors: list[str] = []
    complete = all(o in values for o in plan.options)
    units = {values[o].unit for o in plan.options if o in values}
    if complete and len(units) > 1:
        errors.append(f"units differ between options: {sorted(u or '-' for u in units)}")
    winner: str | None = None
    if complete and len(units) <= 1:
        pick = min if plan.better == "lower" else max
        best = pick(values[o].value for o in plan.options)
        leaders = [o for o in plan.options if values[o].value == best]
        winner = leaders[0] if len(leaders) == 1 else None

    verdicts: list[Verdict] = []
    for i, option in enumerate(plan.options, start=1):
        ov = values.get(option)
        value: VerdictValue = (
            "UNKNOWN" if winner is None else ("TRUE" if option == winner else "FALSE")
        )
        if ov is None:
            verdicts.append(
                Verdict(
                    id=f"o{i}",
                    kind="choice",
                    label=f"{option}: {plan.criterion}",
                    value="UNKNOWN",
                    confidence=0.0,
                    reason="No value found in the documents.",
                )
            )
            continue
        detail = " ".join(x for x in (format_number(ov.value), ov.unit or "") if x)
        excerpt = best_excerpt(
            ov.chunk.text, f"{option} {plan.criterion} {ov.value}", settings.excerpt_max_chars
        )
        verdicts.append(
            Verdict(
                id=f"o{i}",
                kind="choice",
                label=f"{option}: {plan.criterion}",
                value=value,
                confidence=1.0 if winner else 0.0,
                detail=detail,
                source=Source(file=ov.chunk.filename, page=ov.chunk.page, excerpt=excerpt),
            )
        )
    used = list({id(v.chunk): v.chunk for v in values.values()}.values())
    return ComparisonResult(verdicts, winner, "numeric", used, errors)


async def decide_by_nli(
    plan: ComparisonPlan,
    chunks_by_option: dict[str, list[RetrievedChunk]],
    nli: Nli,
    settings: Settings,
) -> ComparisonResult:
    """Fallback with no numbers: Score = max entailment of '{option} offers a {lower|higher}
    {criterion}' over the option's chunks; Choice = top score unless within the tie margin."""
    pairs: list[tuple[str, str]] = []
    owners: list[tuple[str, RetrievedChunk]] = []
    hypotheses = {o: f"{o} offers a {plan.better} {plan.criterion}." for o in plan.options}
    for option in plan.options:
        for chunk in chunks_by_option.get(option, []):
            premise = anchor_sentence(chunk.text, hypotheses[option]) or chunk.text
            pairs.append((premise, hypotheses[option]))
            owners.append((option, chunk))
    results = await asyncio.to_thread(nli.predict, pairs) if pairs else []

    best: dict[str, tuple[float, RetrievedChunk | None]] = {o: (0.0, None) for o in plan.options}
    for (option, chunk), r in zip(owners, results, strict=True):
        if r.entailment > best[option][0]:
            best[option] = (r.entailment, chunk)

    ranked = sorted(plan.options, key=lambda o: -best[o][0])
    top, runner_up = best[ranked[0]][0], (best[ranked[1]][0] if len(ranked) > 1 else 0.0)
    winner = ranked[0] if top - runner_up > settings.comparison_tie_margin else None

    verdicts: list[Verdict] = []
    for i, option in enumerate(plan.options, start=1):
        score, chunk = best[option]
        value: VerdictValue = (
            "UNKNOWN" if winner is None else ("TRUE" if option == winner else "FALSE")
        )
        source = None
        if chunk is not None:
            excerpt = best_excerpt(chunk.text, hypotheses[option], settings.excerpt_max_chars)
            source = Source(file=chunk.filename, page=chunk.page, excerpt=excerpt)
        verdicts.append(
            Verdict(
                id=f"o{i}",
                kind="score",
                label=f"{option}: {plan.criterion}",
                rule=hypotheses[option],
                value=value,
                confidence=score,
                source=source,
            )
        )
    used = [c for _, c in best.values() if c is not None]
    return ComparisonResult(verdicts, winner, "nli", used, [])
