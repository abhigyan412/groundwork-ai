"""Pick the sentence(s) of a chunk that best support a statement, for the evidence trail.

Excerpts are cut from the chunk text by code, so what the visitor sees as "from your document"
always is (CLAUDE.md: serif text is document text).
"""

import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def best_excerpt(chunk_text: str, statement: str, max_chars: int) -> str:
    sentences = [s.strip() for s in _SENTENCE.split(chunk_text) if s.strip()]
    if not sentences:
        return ""
    target = _words(statement)
    best = max(sentences, key=lambda s: (len(target & _words(s)), -len(s)))
    if len(best) <= max_chars:
        return best
    cut = best[: max_chars - 1].rsplit(" ", 1)[0]
    return cut + "…"
