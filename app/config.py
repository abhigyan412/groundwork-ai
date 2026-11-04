"""Application settings and every tunable threshold.

All thresholds live here, never inline (CLAUDE.md). Values come from the environment / `.env`;
defaults are the [Proposed] values from docs/ai-design.md §12 and docs/requirements.md.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCT_NAME = "Groundwork"  # working name, see plan.md open decisions


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Infrastructure ---
    database_url: str
    storage_dir: Path = Path("storage")
    public_base_url: str = "http://localhost:8080"

    # --- Admin auth ---
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=480, ge=5, le=60 * 24 * 7)
    password_min_length: int = 8
    password_max_length: int = 128  # bounds hashing cost per request

    # --- Assistant token (ADR 0007) ---
    assistant_token_key: SecretStr

    # --- Knowledge base limits (docs/requirements.md) ---
    max_documents_per_org: int = 10
    max_pages_per_pdf: int = 20
    max_pdf_bytes: int = 10 * 1024 * 1024

    # --- Ingestion ---
    chunk_target_tokens: int = 450  # bge-small truncates at 512 tokens
    chunk_overlap_tokens: int = 50
    processing_concurrency: int = 2  # documents processed at once (CPU-bound)
    embed_batch_size: int = 32

    # --- Models (System 1) ---
    # "fake" swaps in deterministic stand-ins (tests only); "local" loads the real models.
    model_backend: Literal["local", "fake"] = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384  # must match chunks.embedding vector(384) in schema.sql
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    nli_model: str = "cross-encoder/nli-deberta-v3-small"
    classifier_path: Path = Path("models/question_classifier.joblib")

    # --- Retrieval (docs/ai-design.md §1-2) ---
    retrieval_candidates: int = 20
    rerank_top_k: int = 5
    rrf_k: int = 60
    groundedness_threshold: float = 0.0  # reranker logit; tuned on test data in task 07

    # --- Decision engine (docs/ai-design.md §12) ---
    nli_verdict_threshold: float = 0.7
    router_confidence_threshold: float = 0.6
    comparison_tie_margin: float = 0.1
    decision_timeout_seconds: float = 5.0
    decompose_max_retries: int = 1

    # --- LLM (only decompose() and compose()) ---
    llm_provider: str = "fake"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
