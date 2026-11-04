# Task 02: Knowledge Base

**Day 1** · Refs: `docs/architecture.md` (ingestion flow), `docs/api-contracts.md`, `docs/security.md`

## Goal
Organizations can upload, list and delete PDFs; uploaded PDFs become searchable chunks with page numbers.

## Checklist
- [x] Upload endpoint with validation: PDF magic bytes, parseable, ≤ 10 MB, ≤ 20 pages, < 10 documents
- [x] Specific error messages per `docs/api-contracts.md`
- [x] Private storage at `storage/{org_id}/{document_id}.pdf`
- [x] Background processing: extract per page → chunk → embed → `tsvector`
- [x] Status `processing` / `ready` / `failed` with reason
- [x] List endpoint with limits used
- [x] Delete endpoint: removes file + chunks; 404 for other orgs' documents
- [x] Write the 6 test PDFs (see `tests/evaluation.md`)

## Done when
Upload all 6 test PDFs across 2 orgs; each shows `ready`; chunks in DB have correct `org_id` and `page`.

## Notes
- Replace is `PUT /api/admin/documents/{id}` (keeps the slot; see `docs/api-contracts.md`).
- Sample PDFs: `python scripts/make_sample_pdfs.py` writes `sample_data/{riverside,northwind}/` (committed). Every rule a test question needs is stated once, with digits, on a known page.
- Processing is in-process (`IngestionQueue`); interrupted documents resume on startup.
- Verified with the real bge-small model: all 6 PDFs `ready` in ~4 s; chunks on every page with the uploading org's `org_id`.
- Tests run with `MODEL_BACKEND=fake` (hashed bag-of-words embedder), so no model download is needed.
