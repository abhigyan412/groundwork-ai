"""Three-valued combination of decisions, and the resulting outcome.

See docs/ai-design.md §10 and ADR 0005.
"""

from collections.abc import Sequence

from app.engine.types import Outcome, Verdict, VerdictValue


def combine(values: Sequence[VerdictValue], rule: str) -> VerdictValue:
    """ALL / ANY over TRUE / FALSE / UNKNOWN (Kleene logic). An empty list is UNKNOWN."""
    if not values:
        return "UNKNOWN"
    if rule == "ALL":
        if "FALSE" in values:
            return "FALSE"
        return "UNKNOWN" if "UNKNOWN" in values else "TRUE"
    if rule == "ANY":
        if "TRUE" in values:
            return "TRUE"
        return "UNKNOWN" if "UNKNOWN" in values else "FALSE"
    raise ValueError(f"unknown combine rule {rule!r}")


def combined_confidence(verdicts: Sequence[Verdict], overall: VerdictValue) -> float:
    """Minimum confidence of the decisions that determine the result.

    ALL→FALSE / ANY→TRUE: the decisions with that value decide it. ALL→TRUE / ANY→FALSE: every
    decision counts. UNKNOWN: no confidence.
    """
    if overall == "UNKNOWN" or not verdicts:
        return 0.0
    deciding = [v for v in verdicts if v.value == overall]
    return min(v.confidence for v in deciding) if deciding else 0.0


def outcome_for(overall: VerdictValue, verdicts: Sequence[Verdict]) -> Outcome:
    """`needs_info` only when the overall result is UNKNOWN and every UNKNOWN is a missing fact.
    A decided result is `answered` even if some facts were missing (they're noted in the answer).
    UNKNOWN from a model failure, timeout or an unclear document is `review`."""
    if overall != "UNKNOWN":
        return "answered"
    unknowns = [v for v in verdicts if v.value == "UNKNOWN"]
    if unknowns and all(v.missing_fact for v in unknowns):
        return "needs_info"
    return "review"
