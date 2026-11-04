"""Task 02: upload, limits, processing, list, replace, delete, and per-org isolation."""

from pathlib import Path
from uuid import UUID

import pytest

from app.config import get_settings
from tests.conftest import Account
from tests.pdfs import make_pdf, simple_pdf

PDF = "application/pdf"


async def upload(client, account: Account, data: bytes, name: str = "Hostel_Policy.pdf"):
    return await client.post(
        "/api/admin/documents", headers=account.headers, files={"file": (name, data, PDF)}
    )


async def upload_ready(client, app, account: Account, data: bytes, name: str = "Doc.pdf") -> str:
    r = await upload(client, account, data, name)
    assert r.status_code == 202, r.text
    await app.state.ingestion.drain()
    return r.json()["id"]


async def list_docs(client, account: Account) -> dict:
    r = await client.get("/api/admin/documents", headers=account.headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- Happy path ---------------------------------------------------------------------------------


async def test_upload_processes_to_ready_with_page_numbered_chunks(client, app, db, org_a):
    data = make_pdf(
        ["Hostel curfew is 22:00 on weekdays.", "Block A fee is INR 45,000 per semester."]
    )
    r = await upload(client, org_a, data)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "processing" and body["filename"] == "Hostel_Policy.pdf"

    await app.state.ingestion.drain()
    docs = (await list_docs(client, org_a))["documents"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["status"] == "ready", doc
    assert doc["page_count"] == 2 and doc["size_bytes"] == len(data)
    assert doc["pages_without_text"] == []

    rows = await db.fetch(
        "SELECT page, text, tsv IS NOT NULL AS has_tsv FROM chunks"
        " WHERE org_id = $1 AND document_id = $2 ORDER BY page",
        UUID(org_a.org_id),
        UUID(body["id"]),
    )
    assert [r["page"] for r in rows] == [1, 2]
    assert "22:00" in rows[0]["text"] and "45,000" in rows[1]["text"]
    assert all(r["has_tsv"] for r in rows)


async def test_file_stored_privately_under_org_folder(client, app, org_a):
    doc_id = await upload_ready(client, app, org_a, simple_pdf(), name="../../etc/passwd.pdf")
    path = get_settings().storage_dir / org_a.org_id / f"{doc_id}.pdf"
    assert path.is_file()
    docs = (await list_docs(client, org_a))["documents"]
    assert docs[0]["filename"] == "passwd.pdf"  # directory parts stripped from the display name


async def test_limits_reported(client, app, org_a):
    await upload_ready(client, app, org_a, simple_pdf())
    limits = (await list_docs(client, org_a))["limits"]
    assert limits == {"documents_used": 1, "documents_max": 10, "max_pages": 20, "max_mb": 10}


# --- Validation and limits ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"hello, this is a text file", "This file isn't a valid PDF."),
        (b"", "This file isn't a valid PDF."),
        (b"%PDF-1.7\nthis is not really a pdf", "This file isn't a valid PDF."),
    ],
)
async def test_invalid_pdf_rejected(client, org_a, data, message):
    r = await upload(client, org_a, data, name="notes.pdf")
    assert r.status_code == 400
    assert r.json()["detail"] == message


async def test_password_protected_pdf_rejected(client, org_a):
    r = await upload(client, org_a, make_pdf(["secret"], password="pw"))
    assert r.status_code == 400
    assert "password-protected" in r.json()["detail"]


async def test_over_10mb_rejected_413(client, org_a):
    data = b"%PDF-1.7\n" + b"0" * (10 * 1024 * 1024)
    r = await upload(client, org_a, data)
    assert r.status_code == 413
    assert r.json()["detail"].endswith("The limit is 10 MB.")


async def test_over_20_pages_rejected(client, org_a):
    r = await upload(client, org_a, make_pdf([f"page {i}" for i in range(21)]))
    assert r.status_code == 400
    assert r.json()["detail"] == "This PDF has 21 pages. The limit is 20."


async def test_exactly_20_pages_accepted(client, org_a):
    r = await upload(client, org_a, make_pdf([f"page {i}" for i in range(20)]))
    assert r.status_code == 202


async def test_11th_document_rejected_409_and_failed_ones_dont_count(client, app, org_a):
    for i in range(10):
        r = await upload(client, org_a, simple_pdf(1, f"topic {i}"), name=f"doc{i}.pdf")
        assert r.status_code == 202, r.text
    await app.state.ingestion.drain()

    r = await upload(client, org_a, simple_pdf(), name="eleventh.pdf")
    assert r.status_code == 409
    assert r.json()["detail"] == "Document limit reached (10). Delete one to upload more."

    # A failed document frees its slot.
    docs = (await list_docs(client, org_a))["documents"]
    await client.delete(f"/api/admin/documents/{docs[0]['id']}", headers=org_a.headers)
    r = await upload(client, org_a, make_pdf(["", ""]), name="scanned.pdf")  # no text → failed
    assert r.status_code == 202
    await app.state.ingestion.drain()
    r = await upload(client, org_a, simple_pdf(), name="after-failed.pdf")
    assert r.status_code == 202


async def test_missing_file_is_400(client, org_a):
    r = await client.post("/api/admin/documents", headers=org_a.headers)
    assert r.status_code == 400
    assert r.json()["detail"] == "File is required."


# --- Processing outcomes ------------------------------------------------------------------------


async def test_pdf_without_text_fails_with_reason(client, app, org_a):
    await upload_ready(client, app, org_a, make_pdf(["", ""]), name="scan.pdf")
    doc = (await list_docs(client, org_a))["documents"][0]
    assert doc["status"] == "failed"
    assert doc["error"].startswith("No readable text found.")


async def test_pages_without_text_are_flagged(client, app, org_a):
    await upload_ready(client, app, org_a, make_pdf(["Rules on page one.", "", "Page three."]))
    doc = (await list_docs(client, org_a))["documents"][0]
    assert doc["status"] == "ready" and doc["pages_without_text"] == [2]


async def test_interrupted_processing_is_resumed_on_restart(client, app, db, org_a):
    doc_id = await upload_ready(client, app, org_a, simple_pdf())
    # Simulate a crash mid-processing: back to `processing` with no chunks.
    await db.execute(
        "UPDATE documents SET status = 'processing' WHERE id = $1 AND org_id = $2",
        UUID(doc_id),
        UUID(org_a.org_id),
    )
    await db.execute(
        "DELETE FROM chunks WHERE document_id = $1 AND org_id = $2",
        UUID(doc_id),
        UUID(org_a.org_id),
    )
    assert await app.state.ingestion.requeue_interrupted() == 1
    await app.state.ingestion.drain()
    assert (await list_docs(client, org_a))["documents"][0]["status"] == "ready"


# --- Replace ------------------------------------------------------------------------------------


async def test_replace_swaps_file_and_chunks(client, app, db, org_a):
    doc_id = await upload_ready(client, app, org_a, make_pdf(["Old curfew 21:00."]), "Hostel.pdf")
    r = await client.put(
        f"/api/admin/documents/{doc_id}",
        headers=org_a.headers,
        files={
            "file": ("Hostel_v2.pdf", make_pdf(["New curfew 23:00.", "Guests until 20:00."]), PDF)
        },
    )
    assert r.status_code == 202, r.text
    assert r.json()["id"] == doc_id
    await app.state.ingestion.drain()

    doc = (await list_docs(client, org_a))["documents"][0]
    assert (
        doc["filename"] == "Hostel_v2.pdf" and doc["page_count"] == 2 and doc["status"] == "ready"
    )
    texts = [
        r["text"]
        for r in await db.fetch(
            "SELECT text FROM chunks WHERE org_id = $1 AND document_id = $2",
            UUID(org_a.org_id),
            UUID(doc_id),
        )
    ]
    assert any("23:00" in t for t in texts) and not any("21:00" in t for t in texts)


async def test_replace_works_at_the_limit(client, app, org_a):
    ids = [
        await upload_ready(client, app, org_a, simple_pdf(1, f"t{i}"), f"d{i}.pdf")
        for i in range(10)
    ]
    r = await client.put(
        f"/api/admin/documents/{ids[0]}",
        headers=org_a.headers,
        files={"file": ("new.pdf", simple_pdf(), PDF)},
    )
    assert r.status_code == 202


async def test_replace_validates_new_file(client, app, org_a):
    doc_id = await upload_ready(client, app, org_a, simple_pdf())
    r = await client.put(
        f"/api/admin/documents/{doc_id}",
        headers=org_a.headers,
        files={"file": ("x.pdf", b"not a pdf", PDF)},
    )
    assert r.status_code == 400
    assert (await list_docs(client, org_a))["documents"][0]["status"] == "ready"  # untouched


# --- Delete -------------------------------------------------------------------------------------


async def test_delete_removes_row_chunks_and_file(client, app, db, org_a):
    doc_id = await upload_ready(client, app, org_a, simple_pdf())
    path: Path = get_settings().storage_dir / org_a.org_id / f"{doc_id}.pdf"
    assert path.is_file()

    r = await client.delete(f"/api/admin/documents/{doc_id}", headers=org_a.headers)
    assert r.status_code == 204
    assert not path.exists()
    assert (await list_docs(client, org_a))["documents"] == []
    n = await db.fetchval(
        "SELECT count(*) FROM chunks WHERE org_id = $1 AND document_id = $2",
        UUID(org_a.org_id),
        UUID(doc_id),
    )
    assert n == 0


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
async def test_delete_unknown_is_404(client, org_a, bad_id):
    r = await client.delete(f"/api/admin/documents/{bad_id}", headers=org_a.headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Document not found."


# --- Isolation (tests/evaluation.md) ------------------------------------------------------------


async def test_org_cannot_delete_or_replace_another_orgs_document(client, app, org_a, org_b):
    doc_id = await upload_ready(client, app, org_b, simple_pdf())
    r = await client.delete(f"/api/admin/documents/{doc_id}", headers=org_a.headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Document not found."  # same as a missing id: nothing revealed
    r = await client.put(
        f"/api/admin/documents/{doc_id}",
        headers=org_a.headers,
        files={"file": ("x.pdf", simple_pdf(), PDF)},
    )
    assert r.status_code == 404
    assert len((await list_docs(client, org_b))["documents"]) == 1


async def test_list_shows_only_own_documents(client, app, org_a, org_b):
    await upload_ready(client, app, org_a, simple_pdf(), "A.pdf")
    await upload_ready(client, app, org_b, simple_pdf(), "B.pdf")
    assert [d["filename"] for d in (await list_docs(client, org_a))["documents"]] == ["A.pdf"]
    assert [d["filename"] for d in (await list_docs(client, org_b))["documents"]] == ["B.pdf"]


async def test_chunks_carry_the_uploading_orgs_id(client, app, db, org_a, org_b):
    a_doc = await upload_ready(client, app, org_a, simple_pdf(3), "A.pdf")
    b_doc = await upload_ready(client, app, org_b, simple_pdf(2), "B.pdf")
    for org, doc, pages in ((org_a, a_doc, 3), (org_b, b_doc, 2)):
        rows = await db.fetch(
            "SELECT DISTINCT page FROM chunks WHERE org_id = $1 AND document_id = $2",
            UUID(org.org_id),
            UUID(doc),
        )
        assert sorted(r["page"] for r in rows) == list(range(1, pages + 1))
    # Org A's org_id matches none of org B's document's chunks.
    leaked = await db.fetchval(
        "SELECT count(*) FROM chunks WHERE org_id = $1 AND document_id = $2",
        UUID(org_a.org_id),
        UUID(b_doc),
    )
    assert leaked == 0


async def test_documents_require_admin_jwt(client):
    assert (await client.get("/api/admin/documents")).status_code == 401
    r = await client.post("/api/admin/documents", files={"file": ("a.pdf", simple_pdf(), PDF)})
    assert r.status_code == 401
