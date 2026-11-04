"""Task 03: hybrid search, RRF, rerank, groundedness gate, and org isolation in retrieval.

Runs with the fake embedder/reranker (MODEL_BACKEND=fake); scripts/eval_retrieval.py checks the
real models against the evaluation questions.
"""

from uuid import UUID, uuid4

from app.config import get_settings
from app.ml.reranker import FakeReranker
from app.retrieval.repository import Candidate, keyword_search, vector_search
from app.retrieval.search import (
    RetrievalResult,
    gate_threshold,
    passes_gate,
    reciprocal_rank_fusion,
    retrieve,
)
from tests.conftest import Account, register
from tests.pdfs import make_pdf

PDF = "application/pdf"

HOSTEL = [
    "Hostel curfew is 22:00 on weekdays and 23:30 on weekends.",
    "Block A fee is INR 45,000 per semester. Block B fee is INR 32,000 per semester.",
    "Guests may visit the common lounge between 10:00 and 20:00.",
]
LEAVE = [
    "Employees get 12 days of sick leave per calendar year.",
    "Unused casual leave cannot be carried forward.",
]


async def upload(client, app, account: Account, pages: list[str], name: str) -> str:
    r = await client.post(
        "/api/admin/documents",
        headers=account.headers,
        files={"file": (name, make_pdf(pages), PDF)},
    )
    assert r.status_code == 202, r.text
    await app.state.ingestion.drain()
    return r.json()["id"]


async def ask(app, account: Account, query: str, **kw):
    return await retrieve(
        app.state.db_pool,
        app.state.embedder,
        app.state.reranker,
        get_settings(),
        org_id=UUID(account.org_id),
        query=query,
        **kw,
    )


# --- Units --------------------------------------------------------------------------------------


def _cand(n: int) -> Candidate:
    return Candidate(chunk_id=UUID(int=n), document_id=uuid4(), filename="f.pdf", page=1, text="")


def test_rrf_rewards_agreement_between_rankings():
    a, b, c, d = (_cand(i) for i in range(4))
    fused = reciprocal_rank_fusion([[a, b, c], [c, a, d]], k=60)
    ids = [cand.chunk_id for cand, _ in fused]
    assert ids[:2] == [a.chunk_id, c.chunk_id]  # in both lists, near the top
    assert set(ids) == {a.chunk_id, b.chunk_id, c.chunk_id, d.chunk_id}
    score_a = dict((cand.chunk_id, s) for cand, s in fused)[a.chunk_id]
    assert abs(score_a - (1 / 61 + 1 / 62)) < 1e-12


def test_rrf_handles_empty_and_single_lists():
    a = _cand(1)
    assert reciprocal_rank_fusion([[], []], k=60) == []
    assert [c.chunk_id for c, _ in reciprocal_rank_fusion([[a], []], k=60)] == [a.chunk_id]


def test_fake_reranker_scale():
    r = FakeReranker()
    full, half, none = r.score(
        "hostel curfew", ["The hostel curfew is 22:00", "hostel fees", "menu"]
    )
    assert (full, half, none) == (5.0, 0.0, -5.0)


# --- Retrieval end to end (fake models, real Postgres) ------------------------------------------


async def test_relevant_page_ranks_first_with_source(client, app, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    result = await ask(app, org_a, "What time is the hostel curfew?")
    assert result.grounded
    top = result.chunks[0]
    assert (top.filename, top.page) == ("Hostel_Policy.pdf", 1)
    assert "22:00" in top.text
    assert result.top_score == top.rerank_score
    assert set(result.timings_ms) == {"embed", "search", "rerank"}


async def test_results_are_capped_and_sorted_by_rerank_score(client, app, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    await upload(client, app, org_a, LEAVE, "Leave_Policy.pdf")
    result = await ask(app, org_a, "hostel block fee per semester", top_k=3)
    assert len(result.chunks) <= 3
    scores = [c.rerank_score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)
    assert (result.chunks[0].filename, result.chunks[0].page) == ("Hostel_Policy.pdf", 2)


async def test_keyword_search_ors_question_words(client, app, db, org_a):
    """'time' isn't in the curfew chunk; AND-matching would miss it."""
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    async with app.state.db_pool.acquire() as conn:
        hits = await keyword_search(conn, UUID(org_a.org_id), "What time is the curfew?", 10)
        assert [h.page for h in hits][:1] == [1]
        assert await keyword_search(conn, UUID(org_a.org_id), "what is the", 10) == []


async def test_gate_rejects_unrelated_question(client, app, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    result = await ask(app, org_a, "What's on the canteen menu this week?")
    assert not result.grounded
    assert result.top_score is not None and result.top_score < get_settings().groundedness_threshold


def test_gate_threshold_is_looser_for_decision_questions():
    s = get_settings()
    assert gate_threshold(s, "decision") == s.groundedness_threshold_decision
    for route in ("direct", "procedural", "policy", "comparison", None):
        assert gate_threshold(s, route) == s.groundedness_threshold
    assert s.groundedness_threshold_decision < s.groundedness_threshold


async def test_passes_gate_uses_route(client, app, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    # Fake reranker: 1 of 4 content words match -> -2.5, between the two thresholds (0, -5).
    result = await ask(app, org_a, "hostel gym opening schedule")
    assert result.top_score == -2.5
    assert not passes_gate(result, get_settings(), "direct")
    assert passes_gate(result, get_settings(), "decision")
    nothing = RetrievalResult(chunks=[], top_score=None, grounded=False)
    assert not passes_gate(nothing, get_settings(), "decision")


async def test_org_without_documents_gets_nothing(client, app, org_a):
    result = await ask(app, org_a, "What time is the hostel curfew?")
    assert result.chunks == [] and result.top_score is None and not result.grounded


async def test_deleted_and_unready_documents_are_not_searched(client, app, db, org_a):
    doc_id = await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    await db.execute(
        "UPDATE documents SET status = 'processing' WHERE id = $1 AND org_id = $2",
        UUID(doc_id),
        UUID(org_a.org_id),
    )
    assert (await ask(app, org_a, "hostel curfew")).chunks == []
    await db.execute(
        "UPDATE documents SET status = 'ready' WHERE id = $1 AND org_id = $2",
        UUID(doc_id),
        UUID(org_a.org_id),
    )
    assert (await ask(app, org_a, "hostel curfew")).chunks
    await client.delete(f"/api/admin/documents/{doc_id}", headers=org_a.headers)
    assert (await ask(app, org_a, "hostel curfew")).chunks == []


# --- Isolation (tests/evaluation.md: "Retrieval for org A never returns chunks with org B's org_id")


async def test_retrieval_never_returns_another_orgs_chunks(client, app, db, org_a, org_b):
    a_doc = await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    # Org B has the *same* text plus its own, so similarity alone can't separate them.
    b_doc = await upload(client, app, org_b, HOSTEL + LEAVE, "Shared_Text.pdf")
    b_chunk_ids = {
        r["id"]
        for r in await db.fetch("SELECT id FROM chunks WHERE org_id = $1", UUID(org_b.org_id))
    }
    assert b_chunk_ids

    for query in ["hostel curfew", "sick leave days", "casual leave carried forward", "fee"]:
        result = await ask(app, org_a, query)
        assert all(c.document_id == UUID(a_doc) for c in result.chunks), query
        assert not {c.chunk_id for c in result.chunks} & b_chunk_ids, query
        async with app.state.db_pool.acquire() as conn:
            vec = app.state.embedder.embed_query(query)
            raw = await vector_search(conn, UUID(org_a.org_id), vec, 50)
            raw += await keyword_search(conn, UUID(org_a.org_id), query, 50)
        assert all(c.document_id != UUID(b_doc) for c in raw), query

    # Content that exists only in org B's documents is ungrounded for org A.
    result = await ask(app, org_a, "How many sick leave days per calendar year?")
    assert not result.grounded


async def test_small_org_not_crowded_out_by_large_org(client, app, org_a):
    """With many near-identical chunks in another org, org A still gets its own chunk."""
    big = await register(client, "Big Org", "big@bigorg.com")
    for i in range(3):
        await upload(
            client, app, big, [f"Hostel curfew rule {i}-{j}." for j in range(20)], f"b{i}.pdf"
        )
    await upload(client, app, org_a, ["Hostel curfew is 22:00."], "Mine.pdf")
    result = await ask(app, org_a, "hostel curfew")
    assert [c.filename for c in result.chunks] == ["Mine.pdf"]
