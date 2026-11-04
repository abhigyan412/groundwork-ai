"""Split page text into retrieval chunks.

Chunks never cross a page boundary, so every chunk cites exactly one page. Within a page, text is
packed line by line (and sentence by sentence for long lines) up to `target_tokens`, and each
new chunk starts with the last ~`overlap_tokens` of the previous one. Line breaks are kept so
numbered procedure steps stay readable and in order.
"""

import re
from collections.abc import Callable

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")

TokenCounter = Callable[[str], int]


def _split_words(unit: str, count: TokenCounter, target: int) -> list[str]:
    """Break a sentence that alone exceeds the budget into word windows."""
    pieces: list[str] = []
    current: list[str] = []
    for word in unit.split():
        if current and count(" ".join([*current, word])) > target:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _units(text: str, count: TokenCounter, target: int) -> list[str]:
    """Lines as written; only a line over budget is split into sentences, then word windows."""
    units: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if count(line) <= target:
            units.append(line)
            continue
        for sentence in (s.strip() for s in _SENTENCE_END.split(line)):
            if not sentence:
                continue
            if count(sentence) <= target:
                units.append(sentence)
            else:
                units.extend(_split_words(sentence, count, target))
    return units


def chunk_text(
    text: str, count: TokenCounter, target_tokens: int, overlap_tokens: int
) -> list[str]:
    units = _units(text, count, target_tokens)
    chunks: list[str] = []
    current: list[tuple[str, int]] = []  # (unit, tokens)
    current_tokens = 0
    for unit in units:
        n = count(unit)
        if current and current_tokens + n > target_tokens:
            chunks.append("\n".join(u for u, _ in current))
            # Carry the tail of the previous chunk forward as overlap.
            tail: list[tuple[str, int]] = []
            tail_tokens = 0
            for u, t in reversed(current):
                if tail_tokens + t > overlap_tokens:
                    break
                tail.insert(0, (u, t))
                tail_tokens += t
            if tail_tokens + n > target_tokens:
                tail, tail_tokens = [], 0
            current, current_tokens = tail, tail_tokens
        current.append((unit, n))
        current_tokens += n
    if current:
        chunks.append("\n".join(u for u, _ in current))
    return chunks
