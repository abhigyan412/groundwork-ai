"""Run validated decisions with System 1 executors, in parallel (docs/ai-design.md §9).

- Fact checks: plain Python comparison of the user's fact with the rule's value.
- NLI checks: entailment ≥ threshold → TRUE, contradiction ≥ threshold → FALSE, else UNKNOWN.

Each decision runs in its own thread with a timeout; a failure or timeout makes that decision
UNKNOWN with a reason, and the request continues.
"""

import asyncio
import operator
import time
from collections.abc import Callable

from app.config import Settings
from app.engine.excerpt import anchor_sentence, best_excerpt
from app.engine.spec import FactCheck, NliCheck, UserFact
from app.engine.types import Source, Verdict, VerdictValue
from app.engine.validate import ValidSpec
from app.ml.nli import Nli

_OPS: dict[str, Callable[[object, object], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def compare(op: str, left: float | bool | str, right: float | bool | str) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        left, right = left.strip().lower(), right.strip().lower()
    return _OPS[op](left, right)


def nli_verdict(entailment: float, contradiction: float, threshold: float) -> VerdictValue:
    if entailment >= threshold and entailment >= contradiction:
        return "TRUE"
    if contradiction >= threshold:
        return "FALSE"
    return "UNKNOWN"


def _source(v: ValidSpec, statement: str, settings: Settings) -> Source:
    return Source(
        file=v.chunk.filename,
        page=v.chunk.page,
        excerpt=best_excerpt(v.chunk.text, statement, settings.excerpt_max_chars),
    )


def _run_fact(spec: FactCheck, facts: dict[str, UserFact]) -> tuple[VerdictValue, float, object]:
    fact = facts.get(spec.fact)
    if fact is None:
        return "UNKNOWN", 0.0, None
    return ("TRUE" if compare(spec.op, fact.value, spec.value) else "FALSE"), 1.0, fact.value


def _run_nli(spec: NliCheck, nli: Nli, chunk_text: str, threshold: float):
    # Premise: the sentence closest in wording to the hypothesis (see app/engine/excerpt.py).
    premise = anchor_sentence(chunk_text, spec.hypothesis) or chunk_text
    (r,) = nli.predict([(premise, spec.hypothesis)])
    value = nli_verdict(r.entailment, r.contradiction, threshold)
    confidence = {"TRUE": r.entailment, "FALSE": r.contradiction}.get(value, 0.0)
    return value, confidence


async def execute(
    specs: list[ValidSpec], facts: dict[str, UserFact], nli: Nli, settings: Settings
) -> tuple[list[Verdict], dict[str, int]]:
    timings: dict[str, int] = {}

    async def one(v: ValidSpec) -> Verdict:
        spec = v.spec
        start = time.perf_counter()
        base = {
            "id": spec.id,
            "label": spec.label,
            "rule": spec.rule,
            "source": _source(v, spec.rule, settings),
        }
        try:
            if isinstance(spec, FactCheck):
                value, conf, user_value = await asyncio.wait_for(
                    asyncio.to_thread(_run_fact, spec, facts), settings.decision_timeout_seconds
                )
                return Verdict(
                    kind="fact",
                    value=value,
                    confidence=conf,
                    user_value=user_value,  # type: ignore[arg-type]
                    missing_fact=spec.fact if value == "UNKNOWN" else None,
                    **base,
                )
            value, conf = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_nli, spec, nli, v.chunk.text, settings.nli_verdict_threshold
                ),
                settings.decision_timeout_seconds,
            )
            reason = None if value != "UNKNOWN" else "The document doesn't clearly say."
            return Verdict(kind="nli", value=value, confidence=conf, reason=reason, **base)
        except TimeoutError:
            return Verdict(
                kind="fact" if isinstance(spec, FactCheck) else "nli",
                value="UNKNOWN",
                confidence=0.0,
                reason="The check timed out.",
                **base,
            )
        except Exception:
            return Verdict(
                kind="fact" if isinstance(spec, FactCheck) else "nli",
                value="UNKNOWN",
                confidence=0.0,
                reason="The check failed to run.",
                **base,
            )
        finally:
            timings[spec.id] = round((time.perf_counter() - start) * 1000)

    verdicts = list(await asyncio.gather(*(one(v) for v in specs)))
    return verdicts, timings
