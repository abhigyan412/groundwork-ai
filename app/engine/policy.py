"""Policy path: yes/no question → hypothesis by pattern (code, no LLM) → NLI on the top chunks
(docs/ai-design.md §5, ADR 0010)."""

import asyncio
import re
from collections.abc import Callable

from app.config import Settings
from app.engine.excerpt import best_excerpt
from app.engine.executors import nli_verdict
from app.engine.types import Source, Verdict
from app.ml.nli import Nli
from app.retrieval.search import RetrievedChunk

_SUBJECT = r"(?:i|we)"


def _clean(x: str) -> str:
    x = re.sub(r"\b(?:my|our)\b", "the", x, flags=re.IGNORECASE)
    return " ".join(x.split()).strip(" ,")


def _is_allowed(m: re.Match[str]) -> str:
    """'Is remote work allowed on Fridays' → 'Remote work is allowed on Fridays'."""
    rest = _clean(m["rest"])
    return " ".join(p for p in (_clean(m["x"]), m["be"].lower(), m["adj"].lower(), rest) if p)


def _sentence(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] + "."


# Order matters: first-person forms before the generic "Can X be Y?".
_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    (
        re.compile(r"^(?:am i|are we) (?:allowed|permitted) to (?P<x>.+)$", re.I),
        lambda m: f"It is permitted to {_clean(m['x'])}",
    ),
    (
        re.compile(rf"^(?:can|may) {_SUBJECT} (?P<x>.+)$", re.I),
        lambda m: f"It is permitted to {_clean(m['x'])}",
    ),
    (
        re.compile(r"^(?:am i|are we) required to (?P<x>.+)$", re.I),
        lambda m: f"It is required to {_clean(m['x'])}",
    ),
    (
        re.compile(rf"^(?:do|does) {_SUBJECT} have to (?P<x>.+)$", re.I),
        lambda m: f"It is required to {_clean(m['x'])}",
    ),
    (
        re.compile(rf"^must {_SUBJECT} (?P<x>.+)$", re.I),
        lambda m: f"It is required to {_clean(m['x'])}",
    ),
    (
        re.compile(rf"^(?:do|does) {_SUBJECT} need to (?P<x>.+)$", re.I),
        lambda m: f"It is required to {_clean(m['x'])}",
    ),
    (
        re.compile(rf"^(?:do|does) {_SUBJECT} need (?P<x>.+)$", re.I),
        lambda m: f"{_clean(m['x'])} is required",
    ),
    (
        re.compile(r"^(?P<be>is|are) (?P<x>.+?) (?P<adj>allowed|permitted)(?P<rest>.*)$", re.I),
        lambda m: _is_allowed(m),
    ),
    (
        re.compile(r"^can (?P<x>.+?) be (?P<y>.+)$", re.I),
        lambda m: f"{_clean(m['x'])} can be {_clean(m['y'])}",
    ),
]


def policy_hypothesis(question: str) -> str | None:
    """'Can I hold X and Y together?' → 'It is permitted to hold X and Y together.'

    None when no pattern matches; the caller then uses the decision path.
    """
    q = " ".join(question.strip().split()).rstrip("?").strip()
    for pattern, build in _PATTERNS:
        m = pattern.match(q)
        if m:
            return _sentence(build(m))
    return None


async def check_policy(
    hypothesis: str, chunks: list[RetrievedChunk], nli: Nli, settings: Settings
) -> tuple[Verdict, RetrievedChunk | None]:
    """NLI of the hypothesis against each top chunk; the strongest decisive verdict wins."""
    top = chunks[: settings.policy_chunks_checked]
    results = await asyncio.to_thread(nli.predict, [(c.text, hypothesis) for c in top])
    best: tuple[float, str, RetrievedChunk] | None = None
    for chunk, r in zip(top, results, strict=True):
        value = nli_verdict(r.entailment, r.contradiction, settings.nli_verdict_threshold)
        if value == "UNKNOWN":
            continue
        prob = r.entailment if value == "TRUE" else r.contradiction
        if best is None or prob > best[0]:
            best = (prob, value, chunk)

    label = hypothesis.rstrip(".")
    if best is None:
        return (
            Verdict(
                id="p1",
                kind="policy",
                label=label,
                value="UNKNOWN",
                confidence=0.0,
                reason="The documents don't clearly say either way.",
            ),
            None,
        )
    prob, value, chunk = best
    excerpt = best_excerpt(chunk.text, hypothesis, settings.excerpt_max_chars)
    return (
        Verdict(
            id="p1",
            kind="policy",
            label=label,
            rule=excerpt,
            value=value,  # type: ignore[arg-type]
            confidence=prob,
            source=Source(file=chunk.filename, page=chunk.page, excerpt=excerpt),
        ),
        chunk,
    )
