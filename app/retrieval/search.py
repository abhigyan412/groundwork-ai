"""Hybrid retrieval: vector + keyword candidates → reciprocal rank fusion → cross-encoder rerank
→ groundedness gate (docs/ai-design.md §1-2).

`org_id` must come from a validated credential; it scopes every query below.
"""

import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from app.config import Settings
from app.ml.embedder import Embedder
from app.ml.reranker import Reranker
from app.retrieval.repository import Candidate, keyword_search, vector_search


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    text: str
    rerank_score: float
    rrf_score: float


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]  # reranked, best first, at most rerank_top_k
    top_score: float | None  # best reranker score, None if nothing matched at all
    grounded: bool  # passed the strict (non-decision) gate; use passes_gate() once routed
    timings_ms: dict[str, int] = field(default_factory=dict)


def gate_threshold(settings: Settings, route: str | None) -> float:
    """Decision questions get a looser gate: their personal facts lower the reranker score."""
    if route == "decision":
        return settings.groundedness_threshold_decision
    return settings.groundedness_threshold


def passes_gate(result: RetrievalResult, settings: Settings, route: str | None) -> bool:
    """Groundedness gate for a routed question. Retrieval runs in parallel with the classifier,
    so the route is only known after both finish."""
    return result.top_score is not None and result.top_score >= gate_threshold(settings, route)


def reciprocal_rank_fusion(
    rankings: list[list[Candidate]], k: int
) -> list[tuple[Candidate, float]]:
    """Fuse ranked lists: score = Σ 1 / (k + rank), rank starting at 1. Best first.

    Ties are broken by first appearance, so the result is deterministic.
    """
    scores: dict[UUID, float] = {}
    first_seen: dict[UUID, Candidate] = {}
    for ranking in rankings:
        for rank, cand in enumerate(ranking, start=1):
            scores[cand.chunk_id] = scores.get(cand.chunk_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(cand.chunk_id, cand)
    order = list(first_seen)
    order.sort(key=lambda cid: -scores[cid])  # stable sort keeps first-appearance order on ties
    return [(first_seen[cid], scores[cid]) for cid in order]


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def retrieve(
    pool: asyncpg.Pool,
    embedder: Embedder,
    reranker: Reranker,
    settings: Settings,
    *,
    org_id: UUID,
    query: str,
    top_k: int | None = None,
) -> RetrievalResult:
    timings: dict[str, int] = {}
    n = settings.retrieval_candidates

    t = time.perf_counter()
    query_vec = await asyncio.to_thread(embedder.embed_query, query)
    timings["embed"] = _ms(t)

    t = time.perf_counter()

    async def _vector() -> list[Candidate]:
        async with pool.acquire() as conn:
            return await vector_search(conn, org_id, query_vec, n)

    async def _keyword() -> list[Candidate]:
        async with pool.acquire() as conn:
            return await keyword_search(conn, org_id, query, n)

    vector_hits, keyword_hits = await asyncio.gather(_vector(), _keyword())
    timings["search"] = _ms(t)

    fused = reciprocal_rank_fusion([vector_hits, keyword_hits], settings.rrf_k)[:n]
    if not fused:
        return RetrievalResult(chunks=[], top_score=None, grounded=False, timings_ms=timings)

    t = time.perf_counter()
    scores = await asyncio.to_thread(reranker.score, query, [c.text for c, _ in fused])
    timings["rerank"] = _ms(t)

    ranked = sorted(
        (
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                filename=c.filename,
                page=c.page,
                text=c.text,
                rerank_score=s,
                rrf_score=rrf,
            )
            for (c, rrf), s in zip(fused, scores, strict=True)
        ),
        key=lambda r: (-r.rerank_score, -r.rrf_score),
    )[: top_k or settings.rerank_top_k]
    top = ranked[0].rerank_score
    return RetrievalResult(
        chunks=ranked,
        top_score=top,
        grounded=top >= settings.groundedness_threshold,
        timings_ms=timings,
    )
