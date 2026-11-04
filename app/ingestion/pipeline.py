"""Background processing: extract per page → chunk → embed → store (tsvector is a generated column).

Runs as in-process asyncio tasks (a job queue is a production improvement). CPU-bound steps use
asyncio.to_thread; a semaphore bounds how many documents are processed at once.
"""

import asyncio
import logging
from uuid import UUID

import asyncpg

from app.config import Settings
from app.ingestion import repository as repo
from app.ingestion.chunk import chunk_text
from app.ingestion.extract import extract_pages
from app.ingestion.storage import read_pdf
from app.ml.embedder import Embedder

log = logging.getLogger(__name__)

NO_TEXT_ERROR = "No readable text found. Scanned PDFs aren't supported; upload a text-based PDF."
EXTRACT_ERROR = "Couldn't read the text in this PDF. Try exporting it again and re-uploading."
FAILED_ERROR = "Processing failed. Upload the file again; if it keeps failing, try another export."


class _ProcessingError(Exception):
    pass


class IngestionQueue:
    def __init__(self, pool: asyncpg.Pool, embedder: Embedder, settings: Settings) -> None:
        self._pool = pool
        self._embedder = embedder
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.processing_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, org_id: UUID, document_id: UUID) -> None:
        task = asyncio.create_task(self._process(org_id, document_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for all submitted work (tests, graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def requeue_interrupted(self) -> int:
        """Resume documents left `processing` by a restart."""
        async with self._pool.acquire() as conn:
            pending = await repo.processing_documents_by_org(conn)
        for org_id, document_id in pending:
            self.submit(org_id, document_id)
        return len(pending)

    async def _process(self, org_id: UUID, document_id: UUID) -> None:
        async with self._semaphore:
            async with self._pool.acquire() as conn:
                info = await repo.get_storage_info(conn, org_id, document_id)
            if info is None:
                return  # deleted before we started
            storage_path, generation = info
            try:
                chunks, vectors, empty_pages = await self._build(storage_path)
                async with self._pool.acquire() as conn:
                    stored = await repo.store_chunks_and_mark_ready(
                        conn,
                        org_id=org_id,
                        document_id=document_id,
                        generation=generation,
                        chunks=chunks,
                        embeddings=vectors,
                        pages_without_text=empty_pages,
                    )
                if not stored:
                    log.info("document %s deleted or replaced during processing", document_id)
            except asyncio.CancelledError:
                raise  # shutdown: stays `processing`, requeued on next start
            except Exception as exc:
                message = str(exc) if isinstance(exc, _ProcessingError) else FAILED_ERROR
                if not isinstance(exc, _ProcessingError):
                    log.exception("processing failed for document %s", document_id)
                async with self._pool.acquire() as conn:
                    await repo.mark_failed(
                        conn,
                        org_id=org_id,
                        document_id=document_id,
                        generation=generation,
                        error=message,
                    )

    async def _build(self, storage_path: str):
        s = self._settings
        data = await asyncio.to_thread(read_pdf, s.storage_dir, storage_path)
        try:
            pages = await asyncio.to_thread(extract_pages, data)
        except Exception as exc:
            raise _ProcessingError(EXTRACT_ERROR) from exc

        empty_pages = [p.page for p in pages if not p.text]
        if len(empty_pages) == len(pages):
            raise _ProcessingError(NO_TEXT_ERROR)

        def _chunk_all() -> list[tuple[int, str]]:
            out: list[tuple[int, str]] = []
            for p in pages:
                for text in chunk_text(
                    p.text,
                    self._embedder.count_tokens,
                    s.chunk_target_tokens,
                    s.chunk_overlap_tokens,
                ):
                    out.append((p.page, text))
            return out

        chunks = await asyncio.to_thread(_chunk_all)
        vectors = await asyncio.to_thread(self._embedder.embed_passages, [t for _, t in chunks])
        return chunks, vectors, empty_pages
