"""Find the sentence of a chunk that a statement (a rule, a hypothesis) comes from.

The anchor sentence is chosen by wording, not by NLI score: the sentence whose content words
overlap most with the statement (Jaccard). NLI then has to confirm that this one sentence
entails (or contradicts) the statement. Choosing by wording first stops an unrelated sentence
that happens to entail the statement from being picked; e.g. the withdrawal clause "If a student
accepts another institutional scholarship…" entails "Applicants may hold another institutional
scholarship" (0.995), but the closest sentence, "Applicants must not hold another institutional
scholarship.", contradicts it (docs/ai-design.md §8, task 04 eval review).

Excerpts shown to visitors are cut from the chunk text by code, so what the visitor sees as
"from your document" always is (CLAUDE.md: serif text is document text).
"""

import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")  # keeps decimals: "3.5" is one token
_STOP = frozenset("a an and are as at be by for from in is it of on or the to with".split())
MIN_SENTENCE_WORDS = 4  # shorter lines are headings ("3.3 Withdrawal"), not statements


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def sentences(chunk_text: str) -> list[str]:
    """Sentences and list items of a chunk, headings dropped."""
    parts = (s.strip() for s in _SENTENCE.split(chunk_text))
    return [s for s in parts if len(s.split()) >= MIN_SENTENCE_WORDS]


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def anchor_sentence(chunk_text: str, statement: str) -> str | None:
    """The sentence whose wording is closest to the statement; None if the chunk has none.

    Ties go to the earlier sentence, so the choice is deterministic.
    """
    candidates = sentences(chunk_text)
    if not candidates:
        return None
    return max(candidates, key=lambda s: similarity(s, statement))


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"


def best_excerpt(chunk_text: str, statement: str, max_chars: int) -> str:
    anchor = anchor_sentence(chunk_text, statement)
    if anchor is None:  # chunk of headings only: fall back to its first line
        lines = [ln.strip() for ln in chunk_text.splitlines() if ln.strip()]
        anchor = lines[0] if lines else ""
    return truncate(anchor, max_chars)
