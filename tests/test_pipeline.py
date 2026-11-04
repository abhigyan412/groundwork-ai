"""Task 04 end to end: router → paths → verdicts → compose, with real Postgres, fake System 1
models and a scripted FakeLLMClient. Shows which parts the LLM touches (decompose/compose only)
and that every verdict comes from code or NLI."""

from dataclasses import replace
from uuid import UUID

import pytest

from app.engine.pipeline import AnswerUnavailableError, answer_question
from app.engine.spec import ComparisonPlan, DecisionPlan, ExtractedValue, ExtractedValues
from app.llm.fake import FakeLLMClient
from app.ml.classifier import Classification
from app.ml.nli import NliResult
from tests.conftest import Account
from tests.pdfs import make_pdf

PDF = "application/pdf"

SCHOLARSHIP = [
    "Merit scholarship overview. It covers 50% of tuition fees.",
    "The merit scholarship is open to students in year 2 or above.\n"
    "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.\n"
    "Applicants must have attendance of at least 75% across all registered courses.",
    "Applicants must not hold another institutional scholarship. The merit scholarship may not "
    "be held together with any other scholarship, including the sports scholarship.",
]
HOSTEL = [
    "Hostel curfew is 22:00 on weekdays.",
    "The Block A hostel fee is INR 45,000 per semester. The Block B hostel fee is INR 32,000 per "
    "semester.",
]
WFH = [
    "Employees are eligible to work from home after completing the 6-month probation period. "
    "Employees may work from home for a maximum of 2 days per week.",
]


class StubClassifier:
    def __init__(self, label: str, probability: float = 0.95) -> None:
        self.result = Classification(label, probability, {label: probability})

    def classify(self, question: str) -> Classification:
        return self.result


async def upload(client, app, account: Account, pages: list[str], name: str) -> None:
    r = await client.post(
        "/api/admin/documents",
        headers=account.headers,
        files={"file": (name, make_pdf(pages), PDF)},
    )
    assert r.status_code == 202, r.text
    await app.state.ingestion.drain()


async def ask(
    app,
    account: Account,
    question: str,
    *,
    route: str,
    llm: FakeLLMClient,
    probability: float = 0.95,
    nli=None,
):
    deps = replace(
        app.state.engine,
        classifier=StubClassifier(route, probability),
        llm=llm,
        nli=nli or app.state.engine.nli,
    )
    return await answer_question(
        deps, org_id=UUID(account.org_id), org_name=account.org_name, question=question
    )


def fact(id, fact, op, value, ref, rule, label):
    return {
        "id": id,
        "check": "fact",
        "fact": fact,
        "op": op,
        "value": value,
        "source_chunk": ref,
        "label": label,
        "rule": rule,
    }


Q4 = "I'm in 2nd year, GPA 3.6, 80% attendance, no other scholarship. Am I eligible for merit?"
Q5 = "I'm in 3rd year with 82% attendance and a sports scholarship. Am I eligible?"


def scholarship_plan(facts: list[dict], refs: dict[str, str]) -> DecisionPlan:
    """refs: which prompt ref holds the eligibility page and the other-scholarship page."""
    e, o = refs["eligibility"], refs["other"]
    return DecisionPlan.model_validate(
        {
            "user_facts": facts,
            "decisions": [
                fact(
                    "d1",
                    "year_of_study",
                    ">=",
                    2,
                    e,
                    "The merit scholarship is open to students in year 2 or above.",
                    "Year of study 2 or above",
                ),
                fact(
                    "d2",
                    "gpa",
                    ">=",
                    3.5,
                    e,
                    "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.",
                    "GPA at least 3.5",
                ),
                fact(
                    "d3",
                    "attendance_pct",
                    ">=",
                    75,
                    e,
                    "Applicants must have attendance of at least 75% across all registered courses.",
                    "Attendance at least 75%",
                ),
                fact(
                    "d4",
                    "has_other_scholarship",
                    "==",
                    False,
                    o,
                    "Applicants must not hold another institutional scholarship.",
                    "No other institutional scholarship",
                ),
            ],
            "combine": "ALL",
        }
    )


async def refs_for(app, account, question) -> dict[str, str]:
    """Find which prompt ref ('c1'…) each scholarship page lands on for this question."""
    from app.retrieval.search import retrieve

    result = await retrieve(
        app.state.db_pool,
        app.state.embedder,
        app.state.reranker,
        app.state.engine.settings,
        org_id=UUID(account.org_id),
        query=question,
    )
    pages = {(c.filename, c.page): f"c{i}" for i, c in enumerate(result.chunks, start=1)}
    return {
        "eligibility": pages[("Scholarship_Rules.pdf", 2)],
        "other": pages[("Scholarship_Rules.pdf", 3)],
    }


@pytest.fixture
async def uni(client, app, org_a):
    await upload(client, app, org_a, SCHOLARSHIP, "Scholarship_Rules.pdf")
    await upload(client, app, org_a, HOSTEL, "Hostel_Policy.pdf")
    return org_a


# --- Decision path -----------------------------------------------------------------------------


async def test_q4_all_conditions_met(app, uni):
    refs = await refs_for(app, uni, Q4)
    llm = FakeLLMClient(
        plans={
            Q4: scholarship_plan(
                [
                    {"name": "year_of_study", "type": "number", "value": 2},
                    {"name": "gpa", "type": "number", "value": 3.6},
                    {"name": "attendance_pct", "type": "number", "value": 80},
                    {"name": "has_other_scholarship", "type": "boolean", "value": False},
                ],
                refs,
            )
        },
        answers={Q4: "Yes, you're eligible."},
    )
    r = await ask(app, uni, Q4, route="decision", llm=llm)

    assert r.route == "decision" and r.outcome == "answered" and r.overall == "TRUE"
    assert [v.value for v in r.verdicts] == ["TRUE"] * 4
    assert {v.kind for v in r.verdicts} == {"fact"}
    assert r.verdicts[1].user_value == 3.6 and r.verdicts[1].source.page == 2
    assert r.verdicts[3].source.excerpt.startswith("Applicants must not hold")
    assert {(x.file, x.page) for x in r.references} == {
        ("Scholarship_Rules.pdf", 2),
        ("Scholarship_Rules.pdf", 3),
    }
    assert set(r.timings_ms["decisions"]) == {"d1", "d2", "d3", "d4"}
    assert r.confidence == 1.0 and r.answer_source == "llm"
    # The LLM only decomposed and composed; it received the verdicts, it didn't make them.
    assert [m for m, _ in llm.calls] == ["decompose", "compose"]
    compose_input = llm.calls[-1][1]
    assert compose_input.overall == "TRUE" and len(compose_input.verdicts) == 4


async def test_q5_other_scholarship_fails_and_gpa_unknown(app, uni):
    refs = await refs_for(app, uni, Q5)
    llm = FakeLLMClient(
        plans={
            Q5: scholarship_plan(
                [
                    {"name": "year_of_study", "type": "number", "value": 3},
                    {"name": "attendance_pct", "type": "number", "value": 82},
                    {"name": "has_other_scholarship", "type": "boolean", "value": True},
                ],
                refs,
            )
        }
    )
    r = await ask(app, uni, Q5, route="decision", llm=llm)
    by_label = {v.label: v for v in r.verdicts}
    assert by_label["No other institutional scholarship"].value == "FALSE"
    assert by_label["GPA at least 3.5"].value == "UNKNOWN"
    assert by_label["GPA at least 3.5"].missing_fact == "gpa"
    assert r.overall == "FALSE" and r.outcome == "answered"  # decided despite the missing GPA
    assert llm.calls[-1][1].missing_facts == ["GPA at least 3.5"]


async def test_missing_fact_with_nothing_failing_needs_info(app, uni):
    q = "I'm in 2nd year with 90% attendance and no other scholarship. Am I eligible?"
    refs = await refs_for(app, uni, q)
    llm = FakeLLMClient(
        plans={
            q: scholarship_plan(
                [
                    {"name": "year_of_study", "type": "number", "value": 2},
                    {"name": "attendance_pct", "type": "number", "value": 90},
                    {"name": "has_other_scholarship", "type": "boolean", "value": False},
                ],
                refs,
            )
        }
    )
    r = await ask(app, uni, q, route="decision", llm=llm)
    assert r.overall == "UNKNOWN" and r.outcome == "needs_info"


async def test_invalid_spec_is_retried_with_errors_then_dropped(app, uni):
    refs = await refs_for(app, uni, Q4)
    good = scholarship_plan([{"name": "gpa", "type": "number", "value": 3.6}], refs)
    bad = good.model_copy(deep=True)
    bad.decisions[1].value = 3.7  # threshold not in the cited chunk
    llm = FakeLLMClient(plans={Q4: [bad, good]})
    r = await ask(app, uni, Q4, route="decision", llm=llm)
    decompose_calls = [p for m, p in llm.calls if m == "decompose"]
    assert len(decompose_calls) == 2
    assert any("value 3.7 does not appear" in e for e in decompose_calls[1]["feedback"])
    assert len(r.verdicts) == 4 and r.timings_ms["grounding"] >= 0


async def test_still_invalid_after_retry_keeps_valid_specs(app, uni):
    refs = await refs_for(app, uni, Q4)
    bad = scholarship_plan([{"name": "gpa", "type": "number", "value": 3.6}], refs)
    bad.decisions[1].value = 3.7
    llm = FakeLLMClient(plans={Q4: [bad, bad]})
    r = await ask(app, uni, Q4, route="decision", llm=llm)
    assert [v.id for v in r.verdicts] == ["d1", "d3", "d4"]  # d2 dropped


async def test_no_valid_specs_falls_back_to_grounded_review(app, uni):
    plan = DecisionPlan.model_validate(
        {"decisions": [fact("d1", "gpa", ">=", 3.9, "c1", "made up", "GPA")]}
    )
    llm = FakeLLMClient(plans={Q4: plan})
    r = await ask(app, uni, Q4, route="decision", llm=llm)
    assert r.outcome == "review" and r.verdicts == [] and r.references


async def test_zero_decisions_gives_grounded_answer(app, uni):
    # Fake reranker: 3 of 4 content words match the overview page -> +2.5, clears the strict gate.
    q = "Merit scholarship overview, please."
    r = await ask(app, uni, q, route="decision", llm=FakeLLMClient())
    assert r.route == "decision" and r.outcome == "answered" and r.verdicts == []


async def test_zero_decisions_on_weak_retrieval_is_unanswered(app, uni):
    """Safeguard 2: no conditions means it isn't a decision question, so the looser decision
    gate no longer applies; retrieval that only cleared the looser gate gets no answer
    (Q17 in the task 04 eval: parental leave answered with the sick-leave rule)."""
    q = "hostel gym opening schedule"  # fake reranker: 1 of 4 words -> -2.5, between 0 and -5
    llm = FakeLLMClient()
    r = await ask(app, uni, q, route="decision", llm=llm)
    assert r.outcome == "unanswered" and r.route is None and r.references == []
    assert [m for m, _ in llm.calls] == ["decompose"]  # never composed an answer


async def test_low_confidence_question_must_clear_the_strict_gate(app, uni):
    """Safeguard 1: a low-confidence label goes down the decision path but is gated strictly."""
    q = "hostel gym opening schedule"  # -2.5: passes the decision gate, fails the strict one
    llm = FakeLLMClient()
    r = await ask(app, uni, q, route="decision", llm=llm, probability=0.4)
    assert r.outcome == "unanswered" and llm.calls == []
    confident = await ask(app, uni, q, route="decision", llm=FakeLLMClient(), probability=0.95)
    assert confident.timings_ms.get("decompose") is not None  # passed the gate, reached decompose


async def test_low_classifier_confidence_routes_to_decision(app, uni):
    llm = FakeLLMClient()
    r = await ask(app, uni, "What is the hostel curfew?", route="direct", llm=llm, probability=0.4)
    assert next(m for m, _ in llm.calls) == "decompose"  # took the decision path
    assert r.route == "decision"


# --- Direct / procedural / gate ------------------------------------------------------------------


async def test_direct_question_is_composed_from_chunks_without_decompose(app, uni):
    llm = FakeLLMClient()
    r = await ask(app, uni, "What time is the hostel curfew?", route="direct", llm=llm)
    assert r.route == "direct" and r.outcome == "answered" and r.verdicts == []
    assert [m for m, _ in llm.calls] == ["compose"]
    assert ("Hostel_Policy.pdf", 1) in {(x.file, x.page) for x in r.references}
    assert "22:00" in r.answer  # fake compose: extractive


async def test_gate_stops_unrelated_question_without_any_llm_call(app, uni):
    llm = FakeLLMClient()
    r = await ask(app, uni, "What's on the canteen menu this week?", route="direct", llm=llm)
    assert r.outcome == "unanswered" and r.route is None and r.references == []
    assert r.answer == f"The documents for {uni.org_name} don't cover this."
    assert llm.calls == [] and r.answer_source == "none"


async def test_isolation_other_orgs_content_is_unanswered(client, app, uni, org_b):
    await upload(client, app, org_b, WFH, "WFH_Policy.pdf")
    r = await ask(
        app,
        org_b,
        "What GPA does the merit scholarship require?",
        route="direct",
        llm=FakeLLMClient(),
    )
    assert r.outcome == "unanswered"


# --- Policy path ---------------------------------------------------------------------------------


async def test_policy_question_uses_pattern_and_nli_without_decompose(app, uni):
    q = "Can I hold the merit scholarship and a sports scholarship together?"
    hyp = "It is permitted to hold the merit scholarship and a sports scholarship together."
    nli = app.state.engine.nli.__class__(overrides={hyp: NliResult(0.02, 0.96, 0.02)})
    llm = FakeLLMClient()
    r = await ask(app, uni, q, route="policy", llm=llm, nli=nli)
    assert r.route == "policy" and r.overall == "FALSE" and r.outcome == "answered"
    (verdict,) = r.verdicts
    assert verdict.kind == "policy" and verdict.confidence == 0.96
    assert [m for m, _ in llm.calls] == ["compose"]


async def test_policy_without_pattern_goes_to_decision_path(app, uni):
    llm = FakeLLMClient()
    await ask(
        app, uni, "Merit scholarship and sports scholarship together, ok?", route="policy", llm=llm
    )
    assert llm.calls[0][0] == "decompose"


# --- Comparison path -----------------------------------------------------------------------------


async def test_comparison_extracts_values_and_code_decides(app, uni):
    q = "Which hostel block is cheaper, A or B?"
    plan = ComparisonPlan(options=["Block A", "Block B"], criterion="hostel fee", better="lower")
    # Each option is retrieved separately; refs are numbered across options (c1…, then on).
    from app.retrieval.search import retrieve

    settings = app.state.engine.settings
    n, fee_ref = 1, {}
    for option in plan.options:
        found = (
            await retrieve(
                app.state.db_pool,
                app.state.embedder,
                app.state.reranker,
                settings,
                org_id=UUID(uni.org_id),
                query=f"{option} {plan.criterion}",
                top_k=settings.comparison_chunks_per_option,
            )
        ).chunks
        fee_ref[option] = next(
            f"c{n + i}"
            for i, c in enumerate(found)
            if c.filename == "Hostel_Policy.pdf" and c.page == 2
        )
        n += len(found)
    llm = FakeLLMClient(
        comparison_plans={q: plan},
        extracted={
            "hostel fee": ExtractedValues(
                values=[
                    ExtractedValue(
                        option="Block A", value=45000, unit="INR", source_chunk=fee_ref["Block A"]
                    ),
                    ExtractedValue(
                        option="Block B", value=32000, unit="INR", source_chunk=fee_ref["Block B"]
                    ),
                ]
            )
        },
    )
    r = await ask(app, uni, q, route="comparison", llm=llm)
    assert r.route == "comparison" and r.overall == "TRUE" and r.outcome == "answered"
    assert [v.value for v in r.verdicts] == ["FALSE", "TRUE"]
    assert [v.kind for v in r.verdicts] == ["choice", "choice"]
    assert r.verdicts[1].detail == "32,000 inr"
    assert llm.calls[-1][1].winner == "Block B"
    assert r.references[0].file == "Hostel_Policy.pdf" and r.references[0].page == 2
    calls = [m for m, _ in llm.calls]
    assert calls[:2] == ["decompose_comparison", "extract_comparison_values"]
    assert calls[-1] == "compose"


async def test_comparison_without_plan_falls_back_to_decision(app, uni):
    llm = FakeLLMClient()  # no scripted comparison plan → LLMOutputError
    await ask(app, uni, "Which block is cheaper?", route="comparison", llm=llm)
    assert [m for m, _ in llm.calls][:2] == ["decompose_comparison", "decompose"]


# --- LLM failures --------------------------------------------------------------------------------


async def test_compose_failure_with_verdicts_returns_template_answer(app, uni):
    refs = await refs_for(app, uni, Q4)
    llm = FakeLLMClient(
        plans={
            Q4: scholarship_plan(
                [
                    {"name": "year_of_study", "type": "number", "value": 2},
                    {"name": "gpa", "type": "number", "value": 3.6},
                    {"name": "attendance_pct", "type": "number", "value": 80},
                    {"name": "has_other_scholarship", "type": "boolean", "value": False},
                ],
                refs,
            )
        },
        fail={"compose"},
    )
    r = await ask(app, uni, Q4, route="decision", llm=llm)
    assert r.answer_source == "template" and r.answer.startswith("Yes, all the conditions")
    assert len(r.verdicts) == 4


async def test_llm_down_on_direct_question_raises_answer_unavailable(app, uni):
    llm = FakeLLMClient(fail={"compose"})
    with pytest.raises(AnswerUnavailableError):
        await ask(app, uni, "What time is the hostel curfew?", route="direct", llm=llm)


async def test_decompose_down_falls_back_to_grounded_review(app, uni):
    llm = FakeLLMClient(fail={"decompose"})
    r = await ask(app, uni, Q4, route="decision", llm=llm)
    assert r.outcome == "review" and r.verdicts == []
