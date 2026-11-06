"""Application settings and every tunable threshold.

All thresholds live here, never inline (CLAUDE.md). Values come from the environment / `.env`;
defaults are the values in docs/ai-design.md §14 (some tuned on the task 03/04 evals) and
docs/requirements.md.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCT_NAME = "Groundwork"  # working name, see plan.md open decisions

# Used when LLM_MODEL is empty. claude-sonnet-5-5: latency matters in the chat widget (Opus via
# LLM_MODEL). gemini-3.6-flash: the stable Flash model (gemini-3.8-flash is newer, marked "New").
DEFAULT_LLM_MODELS = {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.6-flash", "fake": ""}


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
    # Groundedness gate on the top reranker logit, per route (docs/ai-design.md §2). Tuned with
    # scripts/eval_retrieval.py: decision questions carry personal facts that aren't in the rule
    # text, so a correct match scores lower and gets a looser gate.
    groundedness_threshold: float = 0.0
    groundedness_threshold_decision: float = -5.0

    # --- Question classifier (docs/ai-design.md §3) ---
    classifier_examples_path: Path = Path("sample_data/classifier_examples.json")
    # Logistic regression inverse regularization. C=4 gave flat probabilities (6/11 in-KB eval
    # questions under the 0.6 router threshold despite a correct top label); C=64: CV accuracy
    # 79% -> 88%, held-out top-1 11/11, lowest in-KB confidence 0.80 (task 04 eval review).
    classifier_c: float = 64.0

    # --- Decision engine (docs/ai-design.md §5-14) ---
    nli_verdict_threshold: float = 0.7  # entail/contradict probability for a decisive NLI verdict
    rule_grounding_threshold: float = 0.7  # cited chunk must entail a fact check's `rule`
    policy_chunks_checked: int = 3
    router_confidence_threshold: float = 0.6
    comparison_tie_margin: float = 0.1  # NLI-score fallback only
    comparison_chunks_per_option: int = 3
    decision_timeout_seconds: float = 5.0
    decompose_max_retries: int = 1
    references_max: int = 3
    excerpt_max_chars: int = 240

    # --- Assistant / public API (task 05) ---
    ask_max_question_chars: int = 1000
    # Whole-question limit for /api/ask (all LLM calls included). Below nginx's 180 s
    # proxy_read_timeout, so the visitor gets a clear message instead of a bare 504.
    ask_timeout_seconds: float = 150.0
    # Per assistant token, per API process (in memory). Protects the LLM quota from one widget.
    ask_rate_limit_per_minute: int = 20
    suggested_questions_max: int = 3
    embed_width: int = 400
    embed_height: int = 600

    # --- LLM (only the decompose step and compose(); CLAUDE.md) ---
    # gemini: the demo default (free tier). anthropic: Claude. fake: no network (tests, offline).
    llm_provider: Literal["gemini", "anthropic", "fake"] = "gemini"
    llm_api_key: SecretStr = SecretStr("")  # empty: the provider SDK's own env var is used
    llm_model: str = ""  # empty: DEFAULT_LLM_MODELS[llm_provider]
    # Thinking depth per call. Anthropic: `effort`. Gemini 3.x: `thinking_level` (low/medium/high).
    llm_effort_decompose: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_effort_compose: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_max_tokens: int = 16000  # includes thinking tokens; non-streaming requests
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2  # Anthropic SDK retries 408/409/429/5xx and connection errors
    # Our own retry with backoff on 429 / 5xx (Gemini free tier: a few requests per minute).
    llm_rate_limit_retries: int = 4
    llm_retry_base_seconds: float = 2.0
    llm_retry_max_wait_seconds: float = 45.0  # total sleep across retries for one call
    # Wall-clock limit for one LLM call, attempts and retries included.
    llm_call_deadline_seconds: float = 75.0

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS.get(self.llm_provider, "")

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
