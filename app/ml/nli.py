"""Natural-language inference (System 1): does a premise entail or contradict a hypothesis?

One model (cross-encoder/nli-deberta-v3-small) serves rule grounding, NLI checks, the policy path
and comparison scores (docs/ai-design.md §9).
"""

import re
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NliResult:
    entailment: float
    contradiction: float
    neutral: float


class Nli(Protocol):
    def predict(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        """pairs: (premise, hypothesis). Probabilities sum to 1 per pair."""
        ...


class LocalNli:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # heavy import, load lazily

        self._model = CrossEncoder(model_name, device="cpu", max_length=512)
        id2label = {int(k): v.lower() for k, v in self._model.config.id2label.items()}
        self._index = {label: i for i, label in id2label.items()}
        missing = {"entailment", "contradiction", "neutral"} - set(self._index)
        if missing:
            raise RuntimeError(f"NLI model {model_name} lacks labels {missing}: {id2label}")
        self._lock = threading.Lock()  # tokenizers aren't safe to share across threads

    def predict(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        if not pairs:
            return []
        with self._lock:
            probs = self._model.predict(
                pairs, apply_softmax=True, show_progress_bar=False, convert_to_numpy=True
            )
        i = self._index
        return [
            NliResult(
                entailment=float(p[i["entailment"]]),
                contradiction=float(p[i["contradiction"]]),
                neutral=float(p[i["neutral"]]),
            )
            for p in probs
        ]


_WORD = re.compile(r"[a-z0-9]+")
_NEGATIONS = frozenset({"not", "no", "cannot", "never", "nor", "without"})
_STOP = frozenset(
    "a an and are as at be by can do for from has have in is it may of on or the to was we "
    "will with".split()
)


class FakeNli:
    """Tests only. Hypothesis content words all in the premise → entailment, or contradiction
    if exactly one side is negated; otherwise neutral. `overrides` maps a hypothesis to a fixed
    result for tests that need a specific outcome."""

    def __init__(self, overrides: dict[str, NliResult] | None = None) -> None:
        self.overrides = overrides or {}

    def predict(self, pairs: list[tuple[str, str]]) -> list[NliResult]:
        return [self._one(p, h) for p, h in pairs]

    def _one(self, premise: str, hypothesis: str) -> NliResult:
        if hypothesis in self.overrides:
            return self.overrides[hypothesis]
        p_words = set(_WORD.findall(premise.lower()))
        h_words = _WORD.findall(hypothesis.lower())
        content = {w for w in h_words if w not in _STOP and w not in _NEGATIONS}
        if not content or not content <= p_words:
            return NliResult(entailment=0.05, contradiction=0.05, neutral=0.9)
        if bool(p_words & _NEGATIONS) != bool(set(h_words) & _NEGATIONS):
            return NliResult(entailment=0.03, contradiction=0.92, neutral=0.05)
        return NliResult(entailment=0.92, contradiction=0.03, neutral=0.05)


def load_nli(backend: str, model_name: str) -> Nli:
    return FakeNli() if backend == "fake" else LocalNli(model_name)
