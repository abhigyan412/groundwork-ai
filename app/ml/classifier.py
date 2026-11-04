"""Question classifier (System 1): logistic regression on sentence embeddings.

See docs/ai-design.md §3.

Trained by scripts/train_classifier.py into a .joblib file. At startup the app loads it; if it's
missing or was trained with a different embedding model, it retrains from the labelled examples
(a second or two for ~75 questions) so a fresh clone works without a manual step.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from app.ml.embedder import Embedder

log = logging.getLogger(__name__)

LABELS = ("direct", "procedural", "policy", "decision", "comparison")


@dataclass(frozen=True)
class Classification:
    label: str
    probability: float
    probabilities: dict[str, float]


class QuestionClassifier:
    def __init__(self, embedder: Embedder, model: LogisticRegression) -> None:
        self._embedder = embedder
        self._model = model

    def classify(self, question: str) -> Classification:
        """CPU-bound: call via asyncio.to_thread."""
        vec = self._embedder.embed_query(question).reshape(1, -1)
        probs = self._model.predict_proba(vec)[0]
        by_label = {str(c): float(p) for c, p in zip(self._model.classes_, probs, strict=True)}
        label = max(by_label, key=by_label.__getitem__)
        return Classification(label=label, probability=by_label[label], probabilities=by_label)


def load_examples(path: Path) -> tuple[list[str], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = [e["question"] for e in data["examples"]]
    labels = [e["label"] for e in data["examples"]]
    unknown = set(labels) - set(LABELS)
    if unknown:
        raise ValueError(f"unknown labels in {path}: {unknown}")
    return questions, labels


def train(embedder: Embedder, questions: list[str], labels: list[str]) -> LogisticRegression:
    # Embed as queries: that's how questions are embedded at prediction time.
    x = np.stack([embedder.embed_query(q) for q in questions])
    model = LogisticRegression(max_iter=2000, C=4.0)
    model.fit(x, labels)
    return model


def model_key(backend: str, embedding_model: str) -> str:
    """Identifies the embedder a saved classifier was trained with."""
    return f"{backend}:{embedding_model}"


def load_or_train(
    embedder: Embedder, embedding_model: str, model_path: Path, examples_path: Path
) -> QuestionClassifier:
    try:
        bundle = joblib.load(model_path)
        if bundle.get("embedding_model") == embedding_model:
            return QuestionClassifier(embedder, bundle["model"])
        log.info("classifier was trained with %s; retraining", bundle.get("embedding_model"))
    except FileNotFoundError:
        log.info("no classifier at %s; training from %s", model_path, examples_path)
    model = train(embedder, *load_examples(examples_path))
    try:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"embedding_model": embedding_model, "model": model}, model_path)
    except OSError:
        log.warning("couldn't save classifier to %s; using it in memory", model_path)
    return QuestionClassifier(embedder, model)
