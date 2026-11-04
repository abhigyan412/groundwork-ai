"""Candidate search over chunks. Both queries filter by org_id and only see `ready` documents."""

from dataclasses import dataclass
from uuid import UUID

import asyncpg
import numpy as np


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    text: str


_SELECT = """
    SELECT c.id AS chunk_id, c.document_id, d.filename, c.page, c.text
    FROM chunks c
    JOIN documents d ON d.id = c.document_id AND d.org_id = c.org_id
    WHERE c.org_id = $1 AND d.status = 'ready'
"""


def _candidates(rows: list[asyncpg.Record]) -> list[Candidate]:
    return [Candidate(**{k: r[k] for k in Candidate.__dataclass_fields__}) for r in rows]


async def vector_search(
    conn: asyncpg.Connection, org_id: UUID, query_vec: np.ndarray, limit: int
) -> list[Candidate]:
    """Nearest chunks by cosine distance, best first."""
    async with conn.transaction():
        # HNSW filters after scanning the index; without an iterative scan, a small org's chunks
        # can be crowded out by other orgs' vectors and fewer than `limit` rows come back.
        # (pgvector >= 0.8; the setting registers once the library loads, so SET LOCAL is safe.)
        await conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        rows = await conn.fetch(
            _SELECT + " ORDER BY c.embedding <=> $2 LIMIT $3", org_id, query_vec, limit
        )
    return _candidates(rows)


async def keyword_search(
    conn: asyncpg.Connection, org_id: UUID, query: str, limit: int
) -> list[Candidate]:
    """Full-text matches ranked by ts_rank_cd, best first.

    The query's words are OR-ed: questions contain words the answer doesn't ("What *time* is the
    curfew?"), and plainto_tsquery's AND would drop the right chunk. Ranking still favours chunks
    that match more of the words.
    """
    rows = await conn.fetch(
        """
        WITH q AS (
            SELECT replace(plainto_tsquery('english', $2)::text, '&', '|')::tsquery AS tsq
        )
        """
        + _SELECT.replace("FROM chunks c", "FROM q, chunks c")
        + """
          AND q.tsq <> ''::tsquery AND c.tsv @@ q.tsq
        ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, c.id
        LIMIT $3
        """,
        org_id,
        query,
        limit,
    )
    return _candidates(rows)
