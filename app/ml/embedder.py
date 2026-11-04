"""Sentence embeddings (System 1). Loaded once in the lifespan handler; called via to_thread."""

import hashlib
import re
import threading
from typing import Protocol

import numpy as np

# bge models are trained with this instruction on the *query* side only; passages get no prefix.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    dim: int

    def count_tokens(self, text: str) -> int: ...
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class LocalEmbedder:
    """BAAI/bge-small-en-v1.5 via sentence-transformers, CPU, L2-normalized output."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, load lazily

        self._model = SentenceTransformer(model_name, device="cpu")
        self._batch_size = batch_size
        self.dim = int(self._model.get_sentence_embedding_dimension() or 0)
        # HF fast tokenizers raise "Already borrowed" when shared across threads concurrently.
        self._lock = threading.Lock()

    def count_tokens(self, text: str) -> int:
        with self._lock:
            return len(self._model.tokenizer.encode(text, add_special_tokens=False))

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vectors = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return np.asarray(vectors, dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([BGE_QUERY_PREFIX + text])[0]


_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors. Tests only: no model download, shared words
    still give similar vectors, so retrieval tests behave sensibly."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for word in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0
        norm = float(np.linalg.norm(v))
        return v / norm if norm else v

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


def load_embedder(backend: str, model_name: str, dim: int, batch_size: int) -> Embedder:
    embedder: Embedder = (
        FakeEmbedder(dim) if backend == "fake" else LocalEmbedder(model_name, batch_size)
    )
    if embedder.dim != dim:
        raise RuntimeError(
            f"Embedding model {model_name} has dimension {embedder.dim}, but the schema "
            f"expects {dim}. Change EMBEDDING_MODEL or the vector(N) column together."
        )
    return embedder
