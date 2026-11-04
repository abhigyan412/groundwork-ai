"""Train the question classifier and report cross-validated accuracy.

    python scripts/train_classifier.py

Embeds sample_data/classifier_examples.json with the configured embedding model, prints 5-fold
cross-validation accuracy and a confusion summary, then saves the model to CLASSIFIER_PATH.
"""

import sys
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.ml.classifier import load_examples, model_key, train  # noqa: E402
from app.ml.embedder import load_embedder  # noqa: E402


def main() -> None:
    s = get_settings()
    embedder = load_embedder(
        s.model_backend, s.embedding_model, s.embedding_dim, s.embed_batch_size
    )
    questions, labels = load_examples(s.classifier_examples_path)
    x = np.stack([embedder.embed_query(q) for q in questions])

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    estimator = LogisticRegression(max_iter=5000, C=s.classifier_c)
    predicted = cross_val_predict(estimator, x, labels, cv=folds)
    correct = sum(p == t for p, t in zip(predicted, labels, strict=True))
    print(f"{len(questions)} examples, 5-fold CV accuracy {correct / len(labels):.0%}")
    mistakes = Counter((t, p) for p, t in zip(predicted, labels, strict=True) if p != t)
    for (true, pred), n in mistakes.most_common():
        print(f"  {true} → {pred}: {n}")

    model = train(embedder, questions, labels, c=s.classifier_c)
    s.classifier_path.parent.mkdir(parents=True, exist_ok=True)
    key = model_key(s.model_backend, s.embedding_model, s.classifier_c)
    joblib.dump({"embedding_model": key, "model": model}, s.classifier_path)
    print(f"saved {s.classifier_path}")


if __name__ == "__main__":
    main()
