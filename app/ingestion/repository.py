"""SQL for documents and chunks. Every statement is scoped by org_id (CLAUDE.md)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg
import numpy as np


@dataclass(frozen=True)
class DocumentRow:
    id: UUID
    filename: str
    page_count: int | None
    size_bytes: int
    status: str
    error: str | None
    pages_without_text: list[int]
    created_at: datetime


_COLUMNS = "id, filename, page_count, size_bytes, status, error, pages_without_text, created_at"


def _row(r: asyncpg.Record) -> DocumentRow:
    return DocumentRow(**{k: r[k] for k in DocumentRow.__dataclass_fields__})


async def count_active(conn: asyncpg.Connection, org_id: UUID) -> int:
    """Documents that count against the limit: everything except `failed`."""
    return await conn.fetchval(
        "SELECT count(*) FROM documents WHERE org_id = $1 AND status <> 'failed'", org_id
    )


async def lock_org(conn: asyncpg.Connection, org_id: UUID) -> None:
    """Serialize uploads per org inside a transaction, so two parallel uploads can't both
    pass the limit check."""
    await conn.execute("SELECT 1 FROM organizations WHERE id = $1 FOR UPDATE", org_id)


async def insert_document(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    document_id: UUID,
    filename: str,
    storage_path: str,
    size_bytes: int,
    page_count: int,
) -> DocumentRow:
    r = await conn.fetchrow(
        f"""
        INSERT INTO documents (id, org_id, filename, storage_path, size_bytes, page_count)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_COLUMNS}
        """,  # noqa: S608 - _COLUMNS is a constant
        document_id,
        org_id,
        filename,
        storage_path,
        size_bytes,
        page_count,
    )
    return _row(r)


async def list_documents(conn: asyncpg.Connection, org_id: UUID) -> list[DocumentRow]:
    rows = await conn.fetch(
        f"SELECT {_COLUMNS} FROM documents WHERE org_id = $1 ORDER BY created_at DESC, id",  # noqa: S608
        org_id,
    )
    return [_row(r) for r in rows]


async def get_storage_info(
    conn: asyncpg.Connection, org_id: UUID, document_id: UUID
) -> tuple[str, int] | None:
    """(storage_path, generation) for an org's document, or None."""
    r = await conn.fetchrow(
        "SELECT storage_path, generation FROM documents WHERE id = $1 AND org_id = $2",
        document_id,
        org_id,
    )
    return (r["storage_path"], r["generation"]) if r else None


async def get_status(conn: asyncpg.Connection, org_id: UUID, document_id: UUID) -> str | None:
    return await conn.fetchval(
        "SELECT status FROM documents WHERE id = $1 AND org_id = $2", document_id, org_id
    )


async def reset_for_replace(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    document_id: UUID,
    filename: str,
    size_bytes: int,
    page_count: int,
) -> DocumentRow | None:
    """Point an existing document at a new file: drop its chunks, bump generation, reprocess."""
    r = await conn.fetchrow(
        f"""
        UPDATE documents
        SET filename = $3, size_bytes = $4, page_count = $5, status = 'processing',
            error = NULL, pages_without_text = '{{}}', generation = generation + 1,
            updated_at = now()
        WHERE id = $1 AND org_id = $2
        RETURNING {_COLUMNS}
        """,  # noqa: S608
        document_id,
        org_id,
        filename,
        size_bytes,
        page_count,
    )
    if r is None:
        return None
    await conn.execute(
        "DELETE FROM chunks WHERE document_id = $1 AND org_id = $2", document_id, org_id
    )
    return _row(r)


async def delete_document(conn: asyncpg.Connection, org_id: UUID, document_id: UUID) -> str | None:
    """Delete the row (chunks cascade). Returns storage_path, or None if not this org's."""
    return await conn.fetchval(
        "DELETE FROM documents WHERE id = $1 AND org_id = $2 RETURNING storage_path",
        document_id,
        org_id,
    )


async def store_chunks_and_mark_ready(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    document_id: UUID,
    generation: int,
    chunks: list[tuple[int, str]],
    embeddings: np.ndarray,
    pages_without_text: list[int],
) -> bool:
    """Atomically replace the document's chunks and mark it ready.

    Returns False (and writes nothing) if the document was deleted or replaced meanwhile.
    """
    async with conn.transaction():
        updated = await conn.fetchval(
            """
            UPDATE documents
            SET status = 'ready', error = NULL, pages_without_text = $4, updated_at = now()
            WHERE id = $1 AND org_id = $2 AND generation = $3
            RETURNING id
            """,
            document_id,
            org_id,
            generation,
            pages_without_text,
        )
        if updated is None:
            return False
        await conn.execute(
            "DELETE FROM chunks WHERE document_id = $1 AND org_id = $2", document_id, org_id
        )
        await conn.executemany(
            "INSERT INTO chunks (org_id, document_id, page, text, embedding)"
            " VALUES ($1, $2, $3, $4, $5)",
            [
                (org_id, document_id, page, text, embeddings[i])
                for i, (page, text) in enumerate(chunks)
            ],
        )
    return True


async def mark_failed(
    conn: asyncpg.Connection, *, org_id: UUID, document_id: UUID, generation: int, error: str
) -> None:
    await conn.execute(
        """
        UPDATE documents SET status = 'failed', error = $4, updated_at = now()
        WHERE id = $1 AND org_id = $2 AND generation = $3
        """,
        document_id,
        org_id,
        generation,
        error,
    )


async def processing_documents_by_org(conn: asyncpg.Connection) -> list[tuple[UUID, UUID]]:
    """(org_id, document_id) for documents left `processing` by a restart.

    Walks organizations and queries documents per org_id, so even this maintenance query keeps
    the "every documents query filters by org_id" rule.
    """
    found: list[tuple[UUID, UUID]] = []
    for org in await conn.fetch("SELECT id FROM organizations"):
        rows = await conn.fetch(
            "SELECT id FROM documents WHERE org_id = $1 AND status = 'processing'", org["id"]
        )
        found.extend((org["id"], r["id"]) for r in rows)
    return found
