"""Evaluate the whole ask pipeline on sample_data/questions.json with the REAL System 1 models.

    docker compose up -d db
    python scripts/eval_engine.py            # LLM per LLM_PROVIDER in .env

With LLM_PROVIDER=anthropic, Claude decomposes and composes. With LLM_PROVIDER=fake, the decompose
step uses the reference plans below (what a correct decomposition looks like, rules copied from
the sample PDFs) so the System 1 side (classifier, gate, rule grounding, NLI, fact checks,
comparison) can be checked before an API key exists; answers are then extractive.

Like eval_retrieval.py, it registers two throwaway orgs, uploads the sample PDFs, and deletes the
orgs at the end.
"""

import asyncio
import json
import secrets
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.engine.pipeline import AnswerUnavailableError, answer_question  # noqa: E402
from app.engine.spec import (  # noqa: E402
    ComparisonPlan,
    DecisionPlan,
    ExtractedValue,
    ExtractedValues,
)
from app.llm.base import PromptChunk  # noqa: E402
from app.llm.fake import FakeLLMClient  # noqa: E402
from app.main import create_app  # noqa: E402

ORG_NAMES = {"riverside": "Riverside University", "northwind": "Northwind Technologies"}
SR, WFH = "Scholarship_Rules.pdf", "WFH_Policy.pdf"


def _fact(id, fact, op, value, src, rule, label):
    return {
        "id": id,
        "check": "fact",
        "fact": fact,
        "op": op,
        "value": value,
        "source_chunk": src,
        "label": label,
        "rule": rule,
    }


_SCHOLARSHIP_DECISIONS = [
    _fact(
        "d1",
        "year_of_study",
        ">=",
        2,
        f"{SR}:2",
        "The merit scholarship is open to students in year 2 or above.",
        "Year of study 2 or above",
    ),
    _fact(
        "d2",
        "gpa",
        ">=",
        3.5,
        f"{SR}:2",
        "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale.",
        "GPA at least 3.5",
    ),
    _fact(
        "d3",
        "attendance_pct",
        ">=",
        75,
        f"{SR}:2",
        "Applicants must have attendance of at least 75% across all registered courses in the "
        "previous academic year.",
        "Attendance at least 75%",
    ),
    _fact(
        "d4",
        "has_other_scholarship",
        "==",
        False,
        f"{SR}:3",
        "Applicants must not hold another institutional scholarship.",
        "No other institutional scholarship",
    ),
]

# Reference decompositions (source_chunk as "file:page", resolved to the prompt's ref at run time).
REFERENCE_PLANS = {
    4: {
        "user_facts": [
            {"name": "year_of_study", "type": "number", "value": 2},
            {"name": "gpa", "type": "number", "value": 3.6},
            {"name": "attendance_pct", "type": "number", "value": 80},
            {"name": "has_other_scholarship", "type": "boolean", "value": False},
        ],
        "decisions": _SCHOLARSHIP_DECISIONS,
        "combine": "ALL",
    },
    5: {
        "user_facts": [
            {"name": "year_of_study", "type": "number", "value": 3},
            {"name": "attendance_pct", "type": "number", "value": 82},
            {"name": "has_other_scholarship", "type": "boolean", "value": True},
        ],
        "decisions": _SCHOLARSHIP_DECISIONS,
        "combine": "ALL",
    },
    10: {
        "user_facts": [
            {"name": "tenure_months", "type": "number", "value": 8},
            {"name": "wfh_days_per_week", "type": "number", "value": 3},
        ],
        "decisions": [
            _fact(
                "d1",
                "tenure_months",
                ">=",
                6,
                f"{WFH}:1",
                "Employees are eligible to work from home after completing the 6-month "
                "probation period.",
                "Probation of 6 months completed",
            ),
            _fact(
                "d2",
                "wfh_days_per_week",
                "<=",
                2,
                f"{WFH}:1",
                "Employees may work from home for a maximum of 2 days per week.",
                "At most 2 days a week",
            ),
            _fact(
                "d3",
                "has_manager_approval",
                "==",
                True,
                f"{WFH}:2",
                "Each work-from-home day requires prior approval from the reporting manager in "
                "the HR portal, at least 1 working day in advance.",
                "Manager approval",
            ),
        ],
        "combine": "ALL",
    },
}
REFERENCE_COMPARISONS = {
    6: (
        ComparisonPlan(
            options=["Block A", "Block B"], criterion="hostel fee per semester", better="lower"
        ),
        {
            "Block A": (45000, "INR per semester", "Hostel_Policy.pdf:2"),
            "Block B": (32000, "INR per semester", "Hostel_Policy.pdf:2"),
        },
    ),
    12: (
        ComparisonPlan(
            options=["metro cities", "non-metro cities"],
            criterion="hotel cap per night",
            better="higher",
        ),
        {
            "metro cities": (7500, "INR per night", "Travel_Policy.pdf:1"),
            "non-metro cities": (4500, "INR per night", "Travel_Policy.pdf:1"),
        },
    ),
}

# What each question should produce. route: the path actually taken.
EXPECTED = {
    1: {"route": "direct", "outcome": "answered"},
    2: {"route": "procedural", "outcome": "answered"},
    3: {"route": "policy", "overall": "FALSE"},
    4: {"route": "decision", "overall": "TRUE", "values": ["TRUE"] * 4},
    5: {"route": "decision", "overall": "FALSE", "unknown": ["gpa"]},
    6: {"route": "comparison", "winner": "Block B"},
    8: {"route": "direct", "outcome": "answered"},
    9: {"route": "procedural", "outcome": "answered"},
    10: {"route": "decision", "overall": "FALSE", "values": ["TRUE", "FALSE", "UNKNOWN"]},
    11: {"route": "policy", "overall": "FALSE"},
    12: {"route": "comparison", "winner": "metro cities"},
}


def _resolve(src: str, chunks: list[PromptChunk]) -> str:
    file, page = src.rsplit(":", 1)
    for c in chunks:
        if c.file == file and c.page == int(page):
            return c.ref
    return "not-retrieved"


class ReferenceLLM(FakeLLMClient):
    """FakeLLMClient whose decompose step returns the reference plans above."""

    def __init__(self, by_question: dict[str, int]) -> None:
        super().__init__()
        self.by_question = by_question

    async def decompose(self, question, chunks, feedback=None, previous=None):
        self.calls.append(("decompose", question))
        ref = REFERENCE_PLANS.get(self.by_question.get(question, -1))
        if ref is None:
            return DecisionPlan()
        data = json.loads(json.dumps(ref))
        for d in data["decisions"]:
            d["source_chunk"] = _resolve(d["source_chunk"], chunks)
        return DecisionPlan.model_validate(data)

    async def decompose_comparison(self, question, chunks):
        self.calls.append(("decompose_comparison", question))
        ref = REFERENCE_COMPARISONS.get(self.by_question.get(question, -1))
        if ref is None:
            return ComparisonPlan(options=[], criterion="", better="lower")
        return ref[0]

    async def extract_comparison_values(self, plan, chunks_by_option):
        ref = next(r for r in REFERENCE_COMPARISONS.values() if r[0] == plan)
        return ExtractedValues(
            values=[
                ExtractedValue(
                    option=o, value=v, unit=u, source_chunk=_resolve(src, chunks_by_option[o])
                )
                for o, (v, u, src) in ref[1].items()
            ]
        )


def _check(q: dict, r, winner: str | None) -> list[str]:
    exp = EXPECTED.get(q["id"])
    problems = []
    if q["expected_sources"] is None:
        if r.outcome != "unanswered":
            problems.append(f"expected unanswered, got {r.outcome}")
        return problems
    if r.outcome == "unanswered":
        return ["wrongly stopped at the gate"]
    if exp is None:
        return problems
    if r.route != exp["route"]:
        problems.append(f"route {r.route} != {exp['route']}")
    for key in ("outcome", "overall"):
        if key in exp and getattr(r, key) != exp[key]:
            problems.append(f"{key} {getattr(r, key)} != {exp[key]}")
    if "values" in exp and [v.value for v in r.verdicts] != exp["values"]:
        problems.append(f"verdicts {[v.value for v in r.verdicts]} != {exp['values']}")
    if "unknown" in exp:
        missing = sorted(v.missing_fact for v in r.verdicts if v.missing_fact)
        if missing != exp["unknown"]:
            problems.append(f"missing facts {missing} != {exp['unknown']}")
    if "winner" in exp and winner != exp["winner"]:
        problems.append(f"winner {winner} != {exp['winner']}")
    return problems


async def main() -> int:
    settings = get_settings()
    if settings.model_backend != "local":
        sys.exit("Set MODEL_BACKEND=local: this evaluates the real models.")
    data = json.loads((ROOT / "sample_data/questions.json").read_text(encoding="utf-8"))
    questions = data["questions"]
    app = create_app()
    org_ids: dict[str, UUID] = {}
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval") as c:
            try:
                tag = secrets.token_hex(3)
                for key, name in ORG_NAMES.items():
                    r = await c.post(
                        "/auth/register",
                        json={
                            "org_name": name,
                            "email": f"eval-{tag}@{key}.example.com",
                            "password": secrets.token_urlsafe(16),
                        },
                    )
                    r.raise_for_status()
                    org_ids[key] = UUID(r.json()["org"]["id"])
                    headers = {"Authorization": f"Bearer {r.json()['token']}"}
                    for pdf in sorted((ROOT / "sample_data" / key).glob("*.pdf")):
                        up = await c.post(
                            "/api/admin/documents",
                            headers=headers,
                            files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
                        )
                        up.raise_for_status()
                await app.state.ingestion.drain()

                deps = app.state.engine
                if settings.llm_provider == "fake":
                    llm = ReferenceLLM({q["question"]: q["id"] for q in questions})
                    deps = replace(deps, llm=llm)
                    print("LLM: reference plans (no API key); answers are extractive\n")
                else:
                    print(f"LLM: {settings.llm_provider} {settings.llm_model}\n")
                return await _run(deps, questions, org_ids)
            finally:
                async with app.state.db_pool.acquire() as conn:
                    for org_id in org_ids.values():
                        await conn.execute("DELETE FROM organizations WHERE id = $1", org_id)


async def _run(deps, questions, org_ids) -> int:
    failures = 0
    for q in questions:
        cls = deps.classifier.classify(q["question"])
        try:
            r = await answer_question(
                deps, org_id=org_ids[q["org"]], org_name=ORG_NAMES[q["org"]], question=q["question"]
            )
        except AnswerUnavailableError as exc:
            print(f"{q['id']:>2} ERROR {exc}")
            failures += 1
            continue
        winner = next(
            (
                v.label.split(":")[0]
                for v in r.verdicts
                if v.kind in ("choice", "score") and v.value == "TRUE"
            ),
            None,
        )
        problems = _check(q, r, winner)
        failures += bool(problems)
        print(f"{q['id']:>2} [{'PASS' if not problems else 'FAIL'}] {q['question']}")
        print(
            f"     classifier: {cls.label} {cls.probability:.2f} → route {r.route}, "
            f"outcome {r.outcome}, overall {r.overall}"
        )
        for v in r.verdicts:
            extra = f" you={v.user_value}" if v.user_value is not None else ""
            extra += f" missing={v.missing_fact}" if v.missing_fact else ""
            extra += f" {v.detail}" if v.detail else ""
            src = f" ({v.source.file} p{v.source.page})" if v.source else ""
            print(f"       {v.id} {v.value:<7} {v.confidence:.2f} {v.label}{extra}{src}")
        if r.references:
            print("     refs: " + ", ".join(f"{x.file} p{x.page}" for x in r.references))
        print(f"     answer: {r.answer[:160].replace(chr(10), ' / ')}")
        for p in problems:
            print(f"     !! {p}")
    print(f"\n{len(questions) - failures}/{len(questions)} questions as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
