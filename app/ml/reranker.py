"""Cross-encoder reranker (System 1). Scores (query, passage) pairs; higher = more relevant.

The real model (ms-marco-MiniLM-L-6-v2) outputs unbounded logits: roughly +5..+10 for a passage
that answers the query and below 0 for unrelated text. The groundedness gate compares the top
logit with the route's threshold in config (`groundedness_threshold*`).
"""

import re
import threading
from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


class LocalReranker:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # heavy import, load lazily

        self._model = CrossEncoder(model_name, device="cpu", max_length=512)
        self._lock = threading.Lock()  # tokenizers aren't safe to share across threads

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        with self._lock:
            scores = self._model.predict(
                [(query, p) for p in passages], show_progress_bar=False, convert_to_numpy=True
            )
        return [float(s) for s in scores]


_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by can do does for from how i in is it my of on or the to was "
    "we what when where which who why will with you your".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class FakeReranker:
    """Tests only. Score = 10 * (share of the query's content words found in the passage) - 5,
    so a passage containing every query word scores +5 and an unrelated one scores -5."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = _content_words(query)
        if not q:
            return [-5.0] * len(passages)
        return [10.0 * len(q & _content_words(p)) / len(q) - 5.0 for p in passages]


def load_reranker(backend: str, model_name: str) -> Reranker:
    return FakeReranker() if backend == "fake" else LocalReranker(model_name)
