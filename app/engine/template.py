"""Deterministic answers built by code from verdicts.

Used when compose() is unavailable but System 1 already decided something: the visitor still
gets the result and its evidence instead of an error (docs/api-contracts.md, LLM failure).
"""

from app.engine.types import Verdict, VerdictValue

_STATE = {"TRUE": "met", "FALSE": "not met", "UNKNOWN": "not checked"}


def template_answer(
    route: str,
    overall: VerdictValue | None,
    verdicts: list[Verdict],
    *,
    combine: str | None = None,
    winner: str | None = None,
) -> str:
    if route == "comparison":
        if winner is None:
            return "The documents don't clearly answer this comparison."
        win = next((v for v in verdicts if v.label.startswith(f"{winner}:")), None)
        detail = f" ({win.detail})" if win and win.detail else ""
        return f"{winner}{detail}, based on the values in the documents."

    if route == "policy":
        if overall == "TRUE":
            return "Yes. The documents allow this."
        if overall == "FALSE":
            return "No. The documents don't allow this."
        return "The documents don't clearly say either way."

    lines = []
    if overall == "TRUE":
        lines.append("Yes, all the conditions are met." if combine != "ANY" else "Yes.")
    elif overall == "FALSE":
        lines.append("No, not every condition is met." if combine != "ANY" else "No.")
    else:
        lines.append("I can't decide this yet.")
    for v in verdicts:
        lines.append(f"- {v.label}: {_STATE[v.value]}")
    missing = [v.label for v in verdicts if v.missing_fact]
    if missing and overall == "UNKNOWN":
        lines.append("Please share: " + "; ".join(missing) + ".")
    return "\n".join(lines)
