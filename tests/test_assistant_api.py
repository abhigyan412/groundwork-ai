"""Task 05: assistant tokens, public endpoints, /api/ask, question log, usage, isolation."""

from dataclasses import replace
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from app.assistant.tokens import hash_token
from app.config import get_settings
from app.llm.fake import FakeLLMClient
from tests.conftest import Account
from tests.pdfs import make_pdf

PDF = "application/pdf"
HOSTEL = ["Hostel curfew is 22:00 on weekdays.", "Block A fee is INR 45,000 per semester."]
LEAVE = ["Employees get 12 days of sick leave per calendar year."]


async def upload(client, app, account: Account, pages, name):
    r = await client.post(
        "/api/admin/documents",
        headers=account.headers,
        files={"file": (name, make_pdf(pages), PDF)},
    )
    assert r.status_code == 202, r.text
    await app.state.ingestion.drain()


async def link(client, account: Account) -> dict:
    r = await client.get("/api/admin/assistant", headers=account.headers)
    assert r.status_code == 200, r.text
    return r.json()


def token_of(url: str) -> str:
    return url.rsplit("/a/", 1)[1]


async def ask(client, token: str, question: str, **extra):
    return await client.post("/api/ask", json={"token": token, "question": question, **extra})


# --- Assistant link ------------------------------------------------------------------------------


async def test_first_get_creates_link_and_later_gets_return_the_same(client, db, org_a):
    first = await link(client, org_a)
    second = await link(client, org_a)
    assert first == second
    token = token_of(first["url"])
    assert first["url"] == f"{get_settings().public_base_url}/a/{token}"
    assert first["token_prefix"] == token[:6]
    assert f'src="{first["url"]}"' in first["embed_code"] and "<iframe" in first["embed_code"]
    assert 'title="Riverside University assistant"' in first["embed_code"]
    rows = await db.fetch("SELECT * FROM assistants WHERE org_id = $1", UUID(org_a.org_id))
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["token_hash"] == hash_token(token)
    assert token not in {str(v) for v in row.values()}  # the plain token is never stored
    key = get_settings().assistant_token_key.get_secret_value()
    assert Fernet(key.encode()).decrypt(row["token_encrypted"].encode()).decode() == token


async def test_regenerate_revokes_the_old_link_immediately(client, org_a):
    old = token_of((await link(client, org_a))["url"])
    r = await client.post("/api/admin/assistant/regenerate", headers=org_a.headers)
    assert r.status_code == 200
    new = r.json()
    assert new["token"] == token_of(new["url"]) != old
    assert (await link(client, org_a))["url"] == new["url"]
    for path in (f"/api/public/assistant/{old}",):
        assert (await client.get(path)).status_code == 401
    revoked = await ask(client, old, "anything")
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "This assistant link is invalid or has been reset"
    assert (await client.get(f"/api/public/assistant/{new['token']}")).status_code == 200


async def test_assistant_routes_require_admin_jwt(client, org_a):
    token = token_of((await link(client, org_a))["url"])
    for method, path in (
        ("GET", "/api/admin/assistant"),
        ("POST", "/api/admin/assistant/regenerate"),
        ("GET", "/api/admin/usage"),
        ("GET", "/api/admin/questions"),
        ("GET", "/api/admin/me"),
        ("GET", "/api/admin/documents"),
    ):
        r = await client.request(method, path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, path  # an assistant token never opens admin routes


async def test_each_org_has_its_own_link(client, org_a, org_b):
    assert (await link(client, org_a))["url"] != (await link(client, org_b))["url"]


# --- Public assistant info -----------------------------------------------------------------------


# One text block per page in test PDFs, and block extraction joins a block into one line, so
# each heading gets its own page to stay a line of its own (as in the real sample PDFs).
HEADED = [
    "1. Curfew",
    "Hostel curfew is 22:00 on weekdays.",
    "2. Guest rules",
    "Guests may visit the lounge until 20:00.",
    "3. Purpose",
]


class _GateStub:
    """Reranker stub: only the curfew question is relevant, so only it may be suggested."""

    def score(self, query, passages):
        return [5.0 if "curfew" in query.lower() else -8.0 for _ in passages]


async def test_public_assistant_offers_only_suggestions_that_pass_the_gate(client, app, org_a):
    await upload(client, app, org_a, HEADED, "Hostel_Policy.pdf")
    app.state.engine = replace(app.state.engine, reranker=_GateStub())
    token = token_of((await link(client, org_a))["url"])
    r = await client.get(f"/api/public/assistant/{token}")
    assert r.status_code == 200
    assert r.json() == {
        "org_name": "Riverside University",
        "suggested_questions": ["What does the Hostel Policy say about curfew?"],
    }
    # Cached per org until its ready documents change.
    assert list(app.state.suggestion_cache.entries) == [UUID(org_a.org_id)]


@pytest.mark.parametrize("token", ["not-a-token", "x" * 43])
async def test_public_assistant_unknown_token_is_401(client, token):
    r = await client.get(f"/api/public/assistant/{token}")
    assert r.status_code == 401


def test_candidate_questions_from_headings():
    from app.assistant.suggestions import candidate_questions

    docs = [
        ("Hostel_Policy.pdf", ["Title\n1. Curfew\ntext", "2. Accommodation fees\n3. Purpose"]),
        ("WFH_Policy.pdf", ["1. Eligibility\n2.1 WFH limits\n1. Eligibility"]),
        ("Scholarship_Rules.pdf", ["2. Eligibility conditions"]),
    ]
    # Round-robin across documents; repeated and generic headings ("Purpose") dropped.
    assert candidate_questions(docs) == [
        "What does the Hostel Policy say about curfew?",
        "What does the WFH Policy say about eligibility?",
        "What do the Scholarship Rules say about eligibility conditions?",  # plural title: do
        "What does the Hostel Policy say about accommodation fees?",
        "What does the WFH Policy say about WFH limits?",
    ]


# --- /api/ask validation ---------------------------------------------------------------------------


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
async def test_empty_question_is_400(client, org_a, question):
    token = token_of((await link(client, org_a))["url"])
    r = await ask(client, token, question)
    assert r.status_code == 400 and r.json()["detail"] == "Please enter a question"


async def test_long_question_is_400(client, org_a):
    token = token_of((await link(client, org_a))["url"])
    r = await ask(client, token, "why " * 300)
    assert r.status_code == 400 and "up to 1000 characters" in r.json()["detail"]


async def test_bad_token_is_checked_before_the_question(client):
    r = await ask(client, "unknown-token", "")
    assert r.status_code == 401  # the widget shows "link no longer active", not a form error


async def test_admin_jwt_is_not_an_assistant_token(client, org_a):
    r = await ask(client, org_a.token, "What time is the curfew?")
    assert r.status_code == 401


async def test_missing_fields_are_400(client):
    r = await client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 400 and r.json()["detail"] == "Token is required."


# --- /api/ask end to end (fake models and fake LLM) ----------------------------------------------


async def test_ask_returns_full_result_and_logs_it(client, app, db, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    token = token_of((await link(client, org_a))["url"])
    r = await ask(client, token, "  What time is the hostel   curfew? ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {
        "answer",
        "outcome",
        "references",
        "route",
        "verdicts",
        "timings_ms",
        "overall",
        "confidence",
        "answer_source",
    }
    assert body["outcome"] in ("answered", "review")
    assert {"file": "Hostel_Policy.pdf", "page": 1} in body["references"]
    assert {"retrieve", "classify", "total"} <= set(body["timings_ms"])
    row = await db.fetchrow(
        'SELECT question, route, outcome, answer, "references", llm_usage FROM questions'
        " WHERE org_id = $1",
        UUID(org_a.org_id),
    )
    assert row["question"] == "What time is the hostel curfew?"  # whitespace normalized
    assert row["outcome"] == body["outcome"] and row["answer"] == body["answer"]
    assert '"Hostel_Policy.pdf"' in row["references"] and '"calls"' in row["llm_usage"]


async def test_ask_unanswered_is_logged_with_no_route(client, app, db, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    token = token_of((await link(client, org_a))["url"])
    r = await ask(client, token, "What's on the canteen menu this week?")
    assert r.status_code == 200
    assert r.json()["outcome"] == "unanswered" and r.json()["references"] == []
    row = await db.fetchrow(
        "SELECT route, outcome FROM questions WHERE org_id = $1", UUID(org_a.org_id)
    )
    assert row["route"] is None and row["outcome"] == "unanswered"


async def test_llm_down_is_503_and_still_logged(client, app, db, org_a):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    token = token_of((await link(client, org_a))["url"])
    app.state.engine = replace(
        app.state.engine,
        llm=FakeLLMClient(
            fail={"compose", "decompose", "decompose_comparison", "extract_comparison_values"}
        ),
    )
    r = await ask(client, token, "What time is the hostel curfew?")
    assert r.status_code == 503
    assert r.json()["detail"] == "Couldn't generate an answer, please try again"
    usage = (await client.get("/api/admin/usage", headers=org_a.headers)).json()
    assert usage["asked"] == 1 and usage["review"] == 1


async def test_rate_limit_per_assistant(client, app, org_a, org_b):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"ask_rate_limit_per_minute": 2}
    )
    try:
        token = token_of((await link(client, org_a))["url"])
        statuses = [(await ask(client, token, "hostel curfew")).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
        other = token_of((await link(client, org_b))["url"])
        assert (await ask(client, other, "hostel curfew")).status_code == 200  # own window
    finally:
        app.dependency_overrides.clear()


# --- Isolation (tests/evaluation.md) -------------------------------------------------------------


async def test_org_a_token_cannot_reach_org_b_content(client, app, db, org_a, org_b):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    await upload(client, app, org_b, LEAVE, "Leave_Policy.pdf")
    token_a = token_of((await link(client, org_a))["url"])
    r = await ask(
        client, token_a, "How many sick leave days per calendar year?", org_id=org_b.org_id
    )  # an org_id in the body is ignored
    assert r.status_code == 200
    assert r.json()["outcome"] == "unanswered"
    assert all(ref["file"] != "Leave_Policy.pdf" for ref in r.json()["references"])
    # Logged under org A only.
    assert (
        await db.fetchval("SELECT count(*) FROM questions WHERE org_id = $1", UUID(org_a.org_id))
        == 1
    )
    assert (
        await db.fetchval("SELECT count(*) FROM questions WHERE org_id = $1", UUID(org_b.org_id))
        == 0
    )


# --- Usage and recent questions ------------------------------------------------------------------


async def test_usage_and_recent_questions_are_per_org(client, app, org_a, org_b):
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    token = token_of((await link(client, org_a))["url"])
    await ask(client, token, "What time is the hostel curfew?")
    await ask(client, token, "What's on the canteen menu this week?")

    usage = (await client.get("/api/admin/usage", headers=org_a.headers)).json()
    assert usage["asked"] == 2 and usage["unanswered"] == 1
    assert sum(usage[k] for k in ("answered", "unanswered", "needs_info", "review")) == 2
    recent = (await client.get("/api/admin/questions?limit=1", headers=org_a.headers)).json()
    (q,) = recent["questions"]
    assert q["question"] == "What's on the canteen menu this week?"  # newest first
    assert q["outcome"] == "unanswered" and q["verdicts"] == [] and q["references"] == []

    assert (await client.get("/api/admin/usage", headers=org_b.headers)).json()["asked"] == 0
    other = await client.get("/api/admin/questions", headers=org_b.headers)
    assert other.json() == {"questions": []}


@pytest.mark.parametrize("limit", [0, 101, -1])
async def test_questions_limit_is_validated(client, org_a, limit):
    r = await client.get(f"/api/admin/questions?limit={limit}", headers=org_a.headers)
    assert r.status_code == 400
