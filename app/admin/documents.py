"""Knowledge base admin routes. org_id always comes from the JWT (CurrentOrg)."""

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel

from app.auth.deps import CurrentOrg
from app.config import Settings, get_settings
from app.db.pool import get_db
from app.ingestion import repository as repo
from app.ingestion import storage
from app.ingestion.pipeline import IngestionQueue
from app.ingestion.validate import (
    UploadRejectedError,
    clean_filename,
    inspect_pdf,
    read_limited,
)

router = APIRouter(prefix="/api/admin/documents", tags=["documents"])

DB = Annotated[asyncpg.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
PdfFile = Annotated[UploadFile, File(description="PDF, up to 20 pages and 10 MB")]


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    page_count: int | None
    size_bytes: int
    status: Literal["processing", "ready", "failed"]
    error: str | None
    pages_without_text: list[int]
    created_at: datetime


class Limits(BaseModel):
    documents_used: int
    documents_max: int
    max_pages: int
    max_mb: int


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    limits: Limits


class UploadAccepted(BaseModel):
    id: UUID
    filename: str
    status: Literal["processing"]


_NOT_FOUND = HTTPException(status_code=404, detail="Document not found.")
_UPLOAD_ERRORS = {
    400: {"description": "Not a valid PDF, password-protected, or too many pages"},
    409: {"description": "Document limit reached"},
    413: {"description": "PDF exceeds the size limit"},
}


def _queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion


def _limit_error(settings: Settings) -> HTTPException:
    n = settings.max_documents_per_org
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Document limit reached ({n}). Delete one to upload more.",
    )


def _parse_id(document_id: str) -> UUID:
    # Malformed ids get the same 404 as other orgs' documents: nothing is revealed.
    try:
        return UUID(document_id)
    except ValueError:
        raise _NOT_FOUND from None


async def _validated_upload(file: UploadFile, settings: Settings) -> tuple[bytes, int]:
    try:
        data = await read_limited(file, settings.max_pdf_bytes)
        pages = await asyncio.to_thread(inspect_pdf, data, settings.max_pages_per_pdf)
    except UploadRejectedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return data, pages


@router.get("")
async def list_documents(account: CurrentOrg, conn: DB, settings: AppSettings) -> DocumentList:
    docs = await repo.list_documents(conn, account.org_id)
    return DocumentList(
        documents=[DocumentOut(**d.__dict__) for d in docs],
        limits=Limits(
            documents_used=sum(d.status != "failed" for d in docs),
            documents_max=settings.max_documents_per_org,
            max_pages=settings.max_pages_per_pdf,
            max_mb=settings.max_pdf_bytes // (1024 * 1024),
        ),
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, responses=_UPLOAD_ERRORS)
async def upload_document(
    file: PdfFile, account: CurrentOrg, conn: DB, settings: AppSettings, request: Request
) -> UploadAccepted:
    org_id = account.org_id
    # Cheap pre-check so a full workspace fails fast, before parsing the file.
    if await repo.count_active(conn, org_id) >= settings.max_documents_per_org:
        raise _limit_error(settings)

    data, pages = await _validated_upload(file, settings)
    filename = clean_filename(file.filename)
    document_id = uuid4()
    rel = storage.relative_path(org_id, document_id)

    async with conn.transaction():
        await repo.lock_org(conn, org_id)
        if await repo.count_active(conn, org_id) >= settings.max_documents_per_org:
            raise _limit_error(settings)
        await repo.insert_document(
            conn,
            org_id=org_id,
            document_id=document_id,
            filename=filename,
            storage_path=rel,
            size_bytes=len(data),
            page_count=pages,
        )
        # Inside the transaction: if the write fails, the row is rolled back too.
        await asyncio.to_thread(storage.write_pdf, settings.storage_dir, rel, data)

    _queue(request).submit(org_id, document_id)
    return UploadAccepted(id=document_id, filename=filename, status="processing")


@router.put(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_UPLOAD_ERRORS, 404: {"description": "Not found"}},
)
async def replace_document(
    document_id: str,
    file: PdfFile,
    account: CurrentOrg,
    conn: DB,
    settings: AppSettings,
    request: Request,
) -> UploadAccepted:
    """Swap the file behind an existing document. Keeps its slot, so it works at 10/10 (except
    when replacing a failed document at the limit: 409)."""
    doc_id = _parse_id(document_id)
    if await repo.get_status(conn, account.org_id, doc_id) is None:
        raise _NOT_FOUND
    data, pages = await _validated_upload(file, settings)
    filename = clean_filename(file.filename)

    async with conn.transaction():
        await repo.lock_org(conn, account.org_id)
        current = await repo.get_status(conn, account.org_id, doc_id)
        if current is None:
            raise _NOT_FOUND
        # A failed document doesn't count toward the limit; replacing it makes it count again.
        if (
            current == "failed"
            and await repo.count_active(conn, account.org_id) >= settings.max_documents_per_org
        ):
            raise _limit_error(settings)
        row = await repo.reset_for_replace(
            conn,
            org_id=account.org_id,
            document_id=doc_id,
            filename=filename,
            size_bytes=len(data),
            page_count=pages,
        )
        if row is None:
            raise _NOT_FOUND
        rel = storage.relative_path(account.org_id, doc_id)
        await asyncio.to_thread(storage.write_pdf, settings.storage_dir, rel, data)

    _queue(request).submit(account.org_id, doc_id)
    return UploadAccepted(id=doc_id, filename=filename, status="processing")


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Not found (or owned by another organization)"}},
)
async def delete_document(
    document_id: str, account: CurrentOrg, conn: DB, settings: AppSettings
) -> Response:
    doc_id = _parse_id(document_id)
    rel = await repo.delete_document(conn, account.org_id, doc_id)
    if rel is None:
        raise _NOT_FOUND
    await asyncio.to_thread(storage.delete_pdf, settings.storage_dir, rel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
