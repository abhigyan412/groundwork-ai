# Task 02: Knowledge Base

**Day 1** · Refs: `docs/architecture.md` (ingestion flow), `docs/api-contracts.md`, `docs/security.md`

## Goal
Organizations can upload, list and delete PDFs; uploaded PDFs become searchable chunks with page numbers.

## Checklist
- [ ] Upload endpoint with validation: PDF magic bytes, parseable, ≤ 10 MB, ≤ 20 pages, < 10 documents
- [ ] Specific error messages per `docs/api-contracts.md`
- [ ] Private storage at `storage/{org_id}/{document_id}.pdf`
- [ ] Background processing: extract per page → chunk → embed → `tsvector`
- [ ] Status `processing` / `ready` / `failed` with reason
- [ ] List endpoint with limits used
- [ ] Delete endpoint: removes file + chunks; 404 for other orgs' documents
- [ ] Write the 6 test PDFs (see `tests/evaluation.md`)

## Done when
Upload all 6 test PDFs across 2 orgs; each shows `ready`; chunks in DB have correct `org_id` and `page`.
