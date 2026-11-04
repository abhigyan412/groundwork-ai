"""Task 04 unit tests: combiner, validator, normalization, policy patterns, comparison, executors.

No database, no LLM, no real models (FakeNli where NLI is needed).
"""

import asyncio
import itertools
import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.engine import comparison as cmp
from app.engine.combine import combine, combined_confidence, outcome_for
from app.engine.excerpt import best_excerpt
from app.engine.executors import compare, execute, nli_verdict
from app.engine.normalize import format_number, numbers_in, value_in_text
from app.engine.policy import check_policy, policy_hypothesis
from app.engine.spec import ComparisonPlan, DecisionPlan, ExtractedValue
from app.engine.template import template_answer
from app.engine.types import Verdict
from app.engine.validate import ground_rules, semantic_check
from app.ml.nli import FakeNli, NliResult
from app.retrieval.search import RetrievedChunk

S = get_settings()

SCHOLARSHIP_P2 = (
    "The merit scholarship is open to students in year 2 or above.\n"
    "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.\n"
    "Applicants must have attendance of at least 75% across all registered courses."
)
SCHOLARSHIP_P3 = "Applicants must not hold another institutional scholarship."


def chunk(text: str, page: int = 1, file: str = "Scholarship_Rules.pdf") -> RetrievedChunk:
    return RetrievedChunk(uuid4(), uuid4(), file, page, text, 5.0, 0.03)


def plan(**kw) -> DecisionPlan:
    return DecisionPlan.model_validate(kw)


def fact(id, fact, op, value, ref="c1", rule=None, label="label"):
    return {
        "id": id,
        "check": "fact",
        "fact": fact,
        "op": op,
        "value": value,
        "source_chunk": ref,
        "label": label,
        "rule": rule or "rule text",
    }


def v(value: str, missing: str | None = None, conf: float = 1.0) -> Verdict:
    return Verdict(
        id="x", kind="fact", label="l", value=value, confidence=conf, missing_fact=missing
    )


# --- Combiner: every ALL/ANY combination of TRUE/FALSE/UNKNOWN -----------------------------------

VALUES = ("TRUE", "FALSE", "UNKNOWN")


@pytest.mark.parametrize("combo", list(itertools.product(VALUES, repeat=3)))
def test_combine_all_matches_kleene_and(combo):
    expected = "FALSE" if "FALSE" in combo else "UNKNOWN" if "UNKNOWN" in combo else "TRUE"
    assert combine(list(combo), "ALL") == expected


@pytest.mark.parametrize("combo", list(itertools.product(VALUES, repeat=3)))
def test_combine_any_matches_kleene_or(combo):
    expected = "TRUE" if "TRUE" in combo else "UNKNOWN" if "UNKNOWN" in combo else "FALSE"
    assert combine(list(combo), "ANY") == expected


@pytest.mark.parametrize("single", VALUES)
def test_combine_single_value_is_itself(single):
    assert combine([single], "ALL") == combine([single], "ANY") == single


def test_combine_empty_is_unknown_and_bad_rule_raises():
    assert combine([], "ALL") == "UNKNOWN"
    with pytest.raises(ValueError):
        combine(["TRUE"], "MOST")


def test_combined_confidence_uses_deciding_verdicts():
    vs = [v("TRUE", conf=0.9), v("FALSE", conf=0.8), v("FALSE", conf=0.75)]
    assert combined_confidence(vs, "FALSE") == 0.75
    assert combined_confidence([v("TRUE", conf=0.9), v("TRUE", conf=0.95)], "TRUE") == 0.9
    assert combined_confidence(vs, "UNKNOWN") == 0.0


def test_outcomes():
    # Overall UNKNOWN only from missing facts → needs_info.
    assert outcome_for("UNKNOWN", [v("TRUE"), v("UNKNOWN", missing="gpa")]) == "needs_info"
    # Decided despite a missing fact (test question 5) → answered.
    assert outcome_for("FALSE", [v("FALSE"), v("UNKNOWN", missing="gpa")]) == "answered"
    # UNKNOWN from a model failure/unclear document → review.
    assert outcome_for("UNKNOWN", [v("UNKNOWN", missing="gpa"), v("UNKNOWN")]) == "review"
    assert outcome_for("TRUE", [v("TRUE")]) == "answered"


# --- Normalization -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("at least 75% attendance", [75]),
        ("Block A fee is INR 45,000 per semester", [45000]),
        ("Fee: ₹45,000", [45000]),
        ("a bursary of 1,50,000", [150000]),
        ("GPA of 3.5/4.0", [3.5, 4.0]),
        ("after the 6-month probation", [6]),
        ("curfew at 22:00", [22, 0]),
        ("version v2 and section 2.1", [2.1]),
        ("six months", []),
    ],
)
def test_numbers_in(text, numbers):
    assert numbers_in(text) == numbers


def test_value_in_text_and_format():
    assert value_in_text(75, "attendance of at least 75%")
    assert value_in_text(45000.0, "INR 45,000")
    assert not value_in_text(3.6, "GPA of at least 3.5")
    assert format_number(45000.0) == "45,000" and format_number(3.5) == "3.5"


# --- Decision plan schema ----------------------------------------------------------------------


def test_plan_schema_parses_types_and_rejects_bad_ops():
    p = plan(
        user_facts=[
            {"name": "gpa", "type": "number", "value": 3.6},
            {"name": "has_other_scholarship", "type": "boolean", "value": False},
        ],
        decisions=[
            fact("d1", "gpa", ">=", 3.5),
            {
                "id": "d2",
                "check": "nli",
                "hypothesis": "h",
                "source_chunk": "c1",
                "label": "l",
                "rule": "r",
            },
        ],
    )
    assert p.facts()["has_other_scholarship"].value is False
    assert p.decisions[1].check == "nli"
    with pytest.raises(ValidationError):
        plan(decisions=[fact("d1", "gpa", "=>", 3.5)])
    with pytest.raises(ValidationError):
        plan(decisions=[{"id": "d1", "check": "regex", "source_chunk": "c1"}])


# --- Validator ---------------------------------------------------------------------------------

REFS = {"c1": chunk(SCHOLARSHIP_P2, 2), "c2": chunk(SCHOLARSHIP_P3, 3)}


def test_validator_accepts_q4_plan():
    p = plan(
        user_facts=[
            {"name": "year_of_study", "type": "number", "value": 2},
            {"name": "gpa", "type": "number", "value": 3.6},
            {"name": "attendance_pct", "type": "number", "value": 80},
            {"name": "has_other_scholarship", "type": "boolean", "value": False},
        ],
        decisions=[
            fact("d1", "gpa", ">=", 3.5),
            fact("d2", "year_of_study", ">=", 2),
            fact("d3", "attendance_pct", ">=", 75),
            fact("d4", "has_other_scholarship", "==", False, ref="c2"),
        ],
    )
    report = semantic_check(p, REFS)
    assert report.errors == []
    assert [s.spec.id for s in report.valid] == ["d1", "d2", "d3", "d4"]


@pytest.mark.parametrize(
    ("decision", "facts", "message"),
    [
        (fact("d1", "gpa", ">=", 3.5, ref="c9"), [], "was not among the retrieved chunks"),
        (fact("d1", "gpa", ">=", 3.7), [], "does not appear in the text of c1"),
        (fact("d1", "has_other_scholarship", ">=", False), [], "not allowed for a boolean"),
        (
            fact("d1", "gpa", ">=", 3.5),
            [{"name": "gpa", "type": "string", "value": "high"}],
            "is a string but the check compares it with a number",
        ),
        (fact("d1", "block", "==", "Block C"), [], "does not appear in the text"),
        (fact("d1", "gpa", ">=", 3.5, rule=" "), [], "rule is empty"),
    ],
)
def test_validator_rejects(decision, facts, message):
    report = semantic_check(plan(user_facts=facts, decisions=[decision]), REFS)
    assert report.valid == []
    assert any(message in e for e in report.errors), report.errors


def test_validator_flags_mistyped_user_fact_and_duplicate_ids():
    p = plan(
        user_facts=[{"name": "gpa", "type": "number", "value": "3.6"}],
        decisions=[fact("d1", "attendance_pct", ">=", 75), fact("d1", "year", ">=", 2)],
    )
    report = semantic_check(p, REFS)
    assert any("declared type number" in e for e in report.errors)
    assert any("duplicate id" in e for e in report.errors)


async def test_rule_grounding_drops_unsupported_rules():
    p = plan(
        decisions=[
            fact(
                "d1", "gpa", ">=", 3.5, rule="Applicants must hold a cumulative GPA of at least 3.5"
            ),
            fact("d2", "attendance_pct", ">=", 75, rule="Students must live on campus for 75 days"),
        ]
    )
    report = await ground_rules(semantic_check(p, REFS), FakeNli(), S.rule_grounding_threshold)
    assert [s.spec.id for s in report.valid] == ["d1"]
    assert report.valid[0].grounding and report.valid[0].grounding >= 0.7
    assert any(e.startswith("d2: rule not supported") for e in report.errors)


# --- Executors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "left", "right", "expected"),
    [
        (">=", 3.6, 3.5, True),
        (">=", 3.5, 3.5, True),
        (">", 3.5, 3.5, False),
        ("<=", 3, 2, False),
        ("<", 1, 2, True),
        ("==", False, False, True),
        ("!=", True, False, True),
        ("==", "Block A ", "block a", True),
    ],
)
def test_compare(op, left, right, expected):
    assert compare(op, left, right) is expected


def test_nli_verdict_thresholds():
    assert nli_verdict(0.8, 0.1, 0.7) == "TRUE"
    assert nli_verdict(0.1, 0.8, 0.7) == "FALSE"
    assert nli_verdict(0.6, 0.3, 0.7) == "UNKNOWN"


async def test_execute_fact_checks_including_missing_fact():
    p = plan(
        user_facts=[
            {"name": "year_of_study", "type": "number", "value": 3},
            {"name": "has_other_scholarship", "type": "boolean", "value": True},
        ],
        decisions=[
            fact("d1", "gpa", ">=", 3.5, label="GPA at least 3.5"),
            fact("d2", "year_of_study", ">=", 2),
            fact("d3", "has_other_scholarship", "==", False, ref="c2"),
        ],
    )
    report = semantic_check(p, REFS)
    verdicts, timings = await execute(report.valid, p.facts(), FakeNli(), S)
    by_id = {x.id: x for x in verdicts}
    assert by_id["d1"].value == "UNKNOWN" and by_id["d1"].missing_fact == "gpa"
    assert by_id["d2"].value == "TRUE" and by_id["d2"].user_value == 3
    assert by_id["d3"].value == "FALSE" and by_id["d3"].user_value is True
    assert by_id["d3"].source.page == 3 and by_id["d3"].source.excerpt == SCHOLARSHIP_P3
    assert set(timings) == {"d1", "d2", "d3"}
    assert combine([x.value for x in verdicts], "ALL") == "FALSE"  # test question 5


async def test_execute_timeout_and_failure_become_unknown(monkeypatch):
    class SlowNli:
        def predict(self, pairs):
            time.sleep(0.5)
            return [NliResult(0.9, 0.05, 0.05)]

    class BrokenNli:
        def predict(self, pairs):
            raise RuntimeError("model crashed")

    p = plan(
        decisions=[
            {
                "id": "d1",
                "check": "nli",
                "hypothesis": "h",
                "source_chunk": "c1",
                "label": "l",
                "rule": "r",
            }
        ]
    )
    specs = semantic_check(p, REFS).valid
    fast = S.model_copy(update={"decision_timeout_seconds": 0.05})
    (slow,), _ = await execute(specs, {}, SlowNli(), fast)
    assert slow.value == "UNKNOWN" and slow.reason == "The check timed out."
    assert slow.missing_fact is None  # → outcome review, not needs_info
    (broken,), _ = await execute(specs, {}, BrokenNli(), S)
    assert broken.value == "UNKNOWN" and broken.reason == "The check failed to run."


async def test_execute_runs_checks_in_parallel():
    class SleepyNli:
        def predict(self, pairs):
            time.sleep(0.3)
            return [NliResult(0.9, 0.05, 0.05)]

    p = plan(
        decisions=[
            {
                "id": f"d{i}",
                "check": "nli",
                "hypothesis": "h",
                "source_chunk": "c1",
                "label": "l",
                "rule": "r",
            }
            for i in range(3)
        ]
    )
    start = time.perf_counter()
    verdicts, _ = await execute(semantic_check(p, REFS).valid, {}, SleepyNli(), S)
    assert len(verdicts) == 3 and time.perf_counter() - start < 0.8  # not 0.9 s sequential


# --- Policy patterns (docs/ai-design.md §5) ----------------------------------------------------


@pytest.mark.parametrize(
    ("question", "hypothesis"),
    [
        (
            "Can I hold the merit scholarship and a sports scholarship together?",
            "It is permitted to hold the merit scholarship and a sports scholarship together.",
        ),
        ("May we bring guests to our rooms?", "It is permitted to bring guests to the rooms."),
        (
            "Can unused casual leave be carried forward?",
            "Unused casual leave can be carried forward.",
        ),
        ("Is remote work allowed on Fridays?", "Remote work is allowed on Fridays."),
        ("Are overnight guests permitted?", "Overnight guests are permitted."),
        ("Do I need to attach receipts?", "It is required to attach receipts."),
        ("Do I need a medical certificate?", "A medical certificate is required."),
        ("Am I required to declare external awards?", "It is required to declare external awards."),
        ("Do we have to get approval first?", "It is required to get approval first."),
        ("Must I sign the late-entry register?", "It is required to sign the late-entry register."),
        ("Am I allowed to work from home?", "It is permitted to work from home."),
        (
            "  can i   keep my room over the summer ?? ",
            "It is permitted to keep the room over the summer.",
        ),
    ],
)
def test_policy_hypothesis(question, hypothesis):
    assert policy_hypothesis(question) == hypothesis


@pytest.mark.parametrize(
    "question",
    ["What is the curfew?", "How many sick leaves do I get?", "Why is the fee so high?"],
)
def test_policy_hypothesis_no_match_goes_to_decision_path(question):
    assert policy_hypothesis(question) is None


async def test_check_policy_takes_strongest_decisive_chunk():
    hyp = "It is permitted to hold the merit scholarship and a sports scholarship together."
    chunks = [chunk("unrelated", 1), chunk("may not be held together", 3), chunk("other", 4)]
    nli = FakeNli()
    nli._one = lambda p, h: (  # type: ignore[method-assign]
        NliResult(0.02, 0.95, 0.03) if "may not" in p else NliResult(0.1, 0.1, 0.8)
    )
    verdict, used = await check_policy(hyp, chunks, nli, S)
    assert verdict.value == "FALSE" and verdict.confidence == 0.95
    assert used is chunks[1] and verdict.source.page == 3


async def test_check_policy_without_decisive_chunk_is_unknown():
    verdict, used = await check_policy("It is permitted to fly.", [chunk("text")], FakeNli(), S)
    assert verdict.value == "UNKNOWN" and used is None and verdict.source is None


# --- Comparison (ADR 0009) ---------------------------------------------------------------------

HOSTEL = chunk(
    "Block A fee is INR 45,000 per semester. Block B fee is INR 32,000 per semester.",
    2,
    "Hostel_Policy.pdf",
)
CMP = ComparisonPlan(options=["Block A", "Block B"], criterion="hostel fee", better="lower")
BY_OPTION = {"Block A": {"c1": HOSTEL}, "Block B": {"c2": HOSTEL}}


def ev(option, value, ref, unit="INR per semester"):
    return ExtractedValue(option=option, value=value, unit=unit, source_chunk=ref)


def test_comparison_picks_lower_and_higher():
    values, errors = cmp.validate_values(
        CMP, [ev("Block A", 45000, "c1"), ev("Block B", 32000, "c2")], BY_OPTION
    )
    assert errors == []
    result = cmp.decide_numeric(CMP, values, S)
    assert result.winner == "Block B"
    assert [x.value for x in result.verdicts] == ["FALSE", "TRUE"]
    assert result.verdicts[1].detail == "32,000 inr per semester"
    higher = cmp.decide_numeric(CMP.model_copy(update={"better": "higher"}), values, S)
    assert higher.winner == "Block A"


def test_comparison_rejects_values_not_in_chunk_or_from_wrong_option():
    values, errors = cmp.validate_values(
        CMP, [ev("Block A", 46000, "c1"), ev("Block B", 32000, "c1")], BY_OPTION
    )
    assert values == {}
    assert any("does not appear" in e for e in errors)
    assert any("not retrieved for this option" in e for e in errors)


@pytest.mark.parametrize(
    ("extracted", "why"),
    [
        ([ev("Block A", 45000, "c1"), ev("Block B", None, None, None)], "missing"),
        ([ev("Block A", 32000, "c1"), ev("Block B", 32000, "c2")], "tie"),
        ([ev("Block A", 45000, "c1", "INR per year"), ev("Block B", 32000, "c2")], "units"),
    ],
)
def test_comparison_unclear_cases(extracted, why):
    chunk_a = chunk("Block A fee is INR 45,000 or 32,000 by scheme.", 2, "Hostel_Policy.pdf")
    by_option = {"Block A": {"c1": chunk_a}, "Block B": {"c2": HOSTEL}}
    values, _ = cmp.validate_values(CMP, extracted, by_option)
    result = cmp.decide_numeric(CMP, values, S)
    assert result.winner is None, why
    assert all(x.value == "UNKNOWN" for x in result.verdicts)


async def test_comparison_nli_fallback_and_tie_margin():
    a, b = chunk("Plan A gives generous travel cover."), chunk("Plan B gives basic cover.")
    plan_ = ComparisonPlan(options=["Plan A", "Plan B"], criterion="travel cover", better="higher")

    def scorer(margin):
        nli = FakeNli()
        nli._one = lambda p, h: (  # type: ignore[method-assign]
            NliResult(0.8, 0.1, 0.1) if "Plan A" in h else NliResult(0.8 - margin, 0.1, 0.1)
        )
        return nli

    result = await cmp.decide_by_nli(plan_, {"Plan A": [a], "Plan B": [b]}, scorer(0.3), S)
    assert result.winner == "Plan A" and result.method == "nli"
    assert [x.kind for x in result.verdicts] == ["score", "score"]
    tie = await cmp.decide_by_nli(plan_, {"Plan A": [a], "Plan B": [b]}, scorer(0.05), S)
    assert tie.winner is None


# --- Excerpts and templates --------------------------------------------------------------------


def test_best_excerpt_picks_the_matching_sentence_and_truncates():
    text = "Intro line. Applicants must hold a GPA of at least 3.5. Another rule here."
    assert (
        best_excerpt(text, "GPA at least 3.5", 240) == "Applicants must hold a GPA of at least 3.5."
    )
    assert best_excerpt("word " * 100, "word", 30).endswith("…")


def test_template_answers():
    vs = [
        Verdict(
            id="d1",
            kind="fact",
            label="GPA at least 3.5",
            value="UNKNOWN",
            confidence=0,
            missing_fact="gpa",
        ),
        Verdict(id="d2", kind="fact", label="Year 2 or above", value="TRUE", confidence=1),
    ]
    text = template_answer("decision", "UNKNOWN", vs, combine="ALL")
    assert "GPA at least 3.5: not checked" in text and "Please share: GPA at least 3.5." in text
    assert template_answer("policy", "FALSE", []).startswith("No.")


async def test_fake_nli_heuristic():
    nli = FakeNli()
    (e, c, n) = await asyncio.to_thread(
        nli.predict,
        [
            ("Applicants must hold a GPA of 3.5", "Applicants must hold a GPA of 3.5"),
            ("Casual leave cannot be carried forward", "Casual leave can be carried forward"),
            ("Hostel curfew", "Gym hours"),
        ],
    )
    assert e.entailment > 0.9 and c.contradiction > 0.9 and n.neutral > 0.8
