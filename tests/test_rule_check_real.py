"""Rule check against the real NLI model: the 21 cases from the task 04 eval review.

Opt-in, because it loads DeBERTa (~600 MB):  RUN_MODEL_TESTS=1 pytest tests/test_rule_check_real.py

Each case states whether the cited chunk should confirm the rule. Measured with the anchor-sentence
method (closest wording, then NLI entailment >= 0.7): 9/10 valid rules accepted (a loose paraphrase
anchors to the wrong sentence; the decompose prompt asks for the rule as written, and a miss gets
one retry), and 11/11 rules that shouldn't pass rejected, including the opposite rule that the
whole-chunk and best-over-all-sentences methods accepted.
"""

import os
from functools import cache
from pathlib import Path

import pytest

from app.config import get_settings
from app.engine.excerpt import anchor_sentence
from app.ingestion.extract import extract_pages

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to load real models"
)

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"


@cache
def nli():
    from app.ml.nli import LocalNli

    return LocalNli(get_settings().nli_model)


@cache
def page(org: str, file: str, number: int) -> str:
    return extract_pages((SAMPLE / org / file).read_bytes())[number - 1].text


SR = ("riverside", "Scholarship_Rules.pdf")
WFH = ("northwind", "WFH_Policy.pdf")
HOSTEL = ("riverside", "Hostel_Policy.pdf")
LEAVE = ("northwind", "Leave_Policy.pdf")

CASES = [
    # (should pass, kind, (org, file), page, rule)
    (True, "valid", SR, 2, "The merit scholarship is open to students in year 2 or above."),
    (True, "valid", SR, 2, "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale."),
    (
        True,
        "valid",
        SR,
        2,
        "Applicants must have attendance of at least 75% across all registered "
        "courses in the previous academic year.",
    ),
    (True, "valid", SR, 3, "Applicants must not hold another institutional scholarship."),
    (
        True,
        "valid",
        WFH,
        1,
        "Employees are eligible to work from home after completing the 6-month probation period.",
    ),
    (True, "valid", WFH, 1, "Employees may work from home for a maximum of 2 days per week."),
    (
        True,
        "valid",
        WFH,
        2,
        "Each work-from-home day requires prior approval from the reporting "
        "manager in the HR portal, at least 1 working day in advance.",
    ),
    (
        False,
        "loose paraphrase (known miss)",
        SR,
        2,
        "Students need a GPA of 3.5 or higher to apply.",
    ),
    (True, "paraphrase", WFH, 1, "Staff can work remotely at most two days each week."),
    (True, "trimmed", SR, 2, "Applicants must hold a cumulative GPA of at least 3.5."),
    (
        False,
        "wrong threshold",
        SR,
        2,
        "Applicants must hold a cumulative GPA of at least 3.0 on a 4.0 scale.",
    ),
    (
        False,
        "wrong threshold",
        WFH,
        1,
        "Employees may work from home for a maximum of 3 days per week.",
    ),
    (
        False,
        "wrong threshold",
        SR,
        2,
        "Applicants must have attendance of at least 60% across all registered courses.",
    ),
    (False, "opposite", SR, 3, "Applicants may hold another institutional scholarship."),
    (False, "opposite", SR, 2, "First-year students are eligible for the merit scholarship."),
    (False, "fabricated", SR, 2, "Applicants must have completed 20 hours of community service."),
    (False, "fabricated", WFH, 1, "Employees must have a home office approved by IT."),
    (
        False,
        "wrong chunk",
        HOSTEL,
        2,
        "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.",
    ),
    (
        False,
        "wrong subject",
        LEAVE,
        2,
        "Unused sick leave can be carried forward to the next year.",
    ),
    (
        False,
        "policy hypothesis (contradicted)",
        LEAVE,
        2,
        "Unused casual leave can be carried forward.",
    ),
    (
        False,
        "policy hypothesis (contradicted)",
        SR,
        3,
        "It is permitted to hold the merit scholarship and a sports scholarship together.",
    ),
]


@pytest.mark.parametrize(
    ("should_pass", "kind", "doc", "number", "rule"),
    CASES,
    ids=[f"{c[1]}:{c[4][:40]}" for c in CASES],
)
def test_rule_check(should_pass, kind, doc, number, rule):
    anchor = anchor_sentence(page(*doc, number), rule)
    assert anchor is not None
    (result,) = nli().predict([(anchor, rule)])
    passed = result.entailment >= get_settings().rule_grounding_threshold
    assert passed is should_pass, (
        f"{kind}: entailment {result.entailment:.3f} against anchor {anchor!r}"
    )
