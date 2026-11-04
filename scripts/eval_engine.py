"""Evaluate the whole ask pipeline on sample_data/questions.json with the REAL System 1 models.

    docker compose up -d db
    python scripts/eval_engine.py                    # LLM per LLM_PROVIDER in .env
    python scripts/eval_engine.py --runs 2 --json out.json

With LLM_PROVIDER=anthropic, Claude decomposes and composes. With LLM_PROVIDER=fake, the decompose
step uses the reference plans below (what a correct decomposition looks like, rules copied from
the sample PDFs) so the System 1 side (classifier, gate, rule grounding, NLI, fact checks,
comparison) can be checked before an API key exists; answers are then extractive.

Like eval_retrieval.py, it registers two throwaway orgs, uploads the sample PDFs, and deletes the
orgs at the end.
"""

import argparse
import asyncio
import json
import re
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
from app.llm.usage import metered  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ml.nli import NliResult  # noqa: E402

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


# What each question should produce. route: the path actually taken. Verdict expectations for
# decision questions are per *reference* decision (matched to Claude's by meaning, not by order).
EXPECTED = {
    1: {"route": "direct", "outcome": "answered"},
    2: {"route": "procedural", "outcome": "answered"},
    3: {"route": "policy", "overall": "FALSE"},
    4: {"route": "decision", "overall": "TRUE", "outcome": "answered"},
    5: {"route": "decision", "overall": "FALSE", "outcome": "answered"},
    6: {"route": "comparison", "winner": "Block B"},
    8: {"route": "direct", "outcome": "answered"},
    9: {"route": "procedural", "outcome": "answered"},
    10: {"route": "decision", "overall": "FALSE", "outcome": "answered"},
    11: {"route": "policy", "overall": "FALSE"},
    12: {"route": "comparison", "winner": "metro cities"},
}
REF_VERDICTS = {
    4: {"d1": "TRUE", "d2": "TRUE", "d3": "TRUE", "d4": "TRUE"},
    5: {"d1": "TRUE", "d2": "UNKNOWN", "d3": "TRUE", "d4": "FALSE"},
    10: {"d1": "TRUE", "d2": "FALSE", "d3": "UNKNOWN"},
}

# Claude Sonnet 5.5, USD per million tokens (cache writes: 5-minute TTL, 1.25x input).
PRICE = {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50}


class Recorder:
    """Captures NLI calls and every LLM output (all decompose attempts, comparison plans)."""

    def __init__(self) -> None:
        self.nli: list[tuple[str, str, NliResult]] = []
        self.plans: list[DecisionPlan] = []
        self.feedback: list[list[str]] = []
        self.comparison: list[object] = []

    def reset(self) -> None:
        self.__init__()


class RecordingNli:
    def __init__(self, inner, rec: Recorder) -> None:
        self.inner, self.rec = inner, rec

    def predict(self, pairs):
        results = self.inner.predict(pairs)
        self.rec.nli.extend((p, h, r) for (p, h), r in zip(pairs, results, strict=True))
        return results


class RecordingLLM:
    def __init__(self, inner, rec: Recorder) -> None:
        self.inner, self.rec = inner, rec

    async def decompose(self, question, chunks, feedback=None, previous=None):
        if feedback:
            self.rec.feedback.append(list(feedback))
        plan = await self.inner.decompose(question, chunks, feedback=feedback, previous=previous)
        self.rec.plans.append(plan)
        return plan

    async def decompose_comparison(self, question, chunks):
        plan = await self.inner.decompose_comparison(question, chunks)
        self.rec.comparison.append(plan)
        return plan

    async def extract_comparison_values(self, plan, chunks_by_option):
        values = await self.inner.extract_comparison_values(plan, chunks_by_option)
        self.rec.comparison.append(values)
        return values

    async def compose(self, data):
        return await self.inner.compose(data)


# --- Plan comparison: Claude vs reference ------------------------------------------------------


def _canonical(op: str, value):
    """(op, value) in a comparable form: booleans as 'must be X'; numbers unchanged."""
    if isinstance(value, bool):
        if op == "==":
            return ("is", value)
        if op == "!=":
            return ("is", not value)
    return (op, float(value) if isinstance(value, int | float) else value)


def _page_of(ref: str, plan_chunks: dict[str, str]) -> str:
    return plan_chunks.get(ref, "?")


def compare_plans(qid: int, plan: DecisionPlan, refs_to_pages: dict[str, str]):
    """Match each reference decision to Claude's by cited page + value; check fact and direction."""
    reference = REFERENCE_PLANS.get(qid)
    if reference is None:
        return [], []
    rows, used = [], set()
    for r in reference["decisions"]:
        r_page = r["source_chunk"].replace(".pdf:", ".pdf p")
        r_canon = _canonical(r["op"], r["value"])
        best = None
        for c in plan.decisions:
            if c.id in used or c.check != "fact":
                continue
            same_value = (
                isinstance(c.value, bool) == isinstance(r["value"], bool)
                and (
                    c.value == r["value"]
                    if isinstance(c.value, bool) or isinstance(r["value"], bool)
                    else float(c.value) == float(r["value"])
                )
            ) or (isinstance(c.value, bool) and isinstance(r["value"], bool))
            if not same_value:
                continue
            page_ok = _page_of(c.source_chunk, refs_to_pages) == r_page
            score = (page_ok, _canonical(c.op, c.value) == r_canon, c.fact == r["fact"])
            if best is None or score > best[0]:
                best = (score, c)
        if best is None:
            rows.append({"ref": r, "claude": None, "status": "MISSING"})
            continue
        (page_ok, direction_ok, _), c = best
        used.add(c.id)
        rows.append(
            {
                "ref": r,
                "claude": c,
                "status": "OK"
                if page_ok and direction_ok
                else "WRONG DIRECTION"
                if not direction_ok
                else "WRONG PAGE",
            }
        )
    extras = [c for c in plan.decisions if c.id not in used]
    return rows, extras


# --- One run -------------------------------------------------------------------------------------

_PAGE_MENTION = re.compile(r"\b([\w-]+\.pdf)\b|\bpages?\s+(\d+)", re.I)


def _answer_checks(r) -> list[str]:
    notes = []
    first = r.answer.strip().split()[0].lower().strip(",.!") if r.answer.strip() else ""
    if r.overall == "TRUE" and r.route in ("decision", "policy") and first == "no":
        notes.append("answer starts 'No' but overall is TRUE")
    if r.overall == "FALSE" and r.route in ("decision", "policy") and first == "yes":
        notes.append("answer starts 'Yes' but overall is FALSE")
    ref_files = {x.file for x in r.references}
    ref_pages = {x.page for x in r.references}
    for m in _PAGE_MENTION.finditer(r.answer):
        if m.group(1) and m.group(1) not in ref_files:
            notes.append(f"answer mentions {m.group(1)}, not among the references")
        if m.group(2) and int(m.group(2)) not in ref_pages:
            notes.append(f"answer mentions page {m.group(2)}, not among the references")
    return notes


def _check(q: dict, r, winner: str | None, matched: list[dict]) -> list[str]:
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
    if "winner" in exp and winner != exp["winner"]:
        problems.append(f"winner {winner} != {exp['winner']}")
    expected_verdicts = REF_VERDICTS.get(q["id"], {})
    verdicts = {v.id: v for v in r.verdicts}
    for row in matched:
        want = expected_verdicts.get(row["ref"]["id"])
        c = row["claude"]
        got = verdicts[c.id].value if c is not None and c.id in verdicts else None
        if want and got != want:
            problems.append(f"{row['ref']['label']}: verdict {got} != {want}")
    return problems


def _fmt_ms(t: dict, key: str) -> str:
    v = t.get(key)
    if isinstance(v, dict):
        return f"{max(v.values())}" if v else "-"
    return "-" if v is None else str(v)


async def run_once(deps, questions, org_ids, rec, chunk_pages, threshold, n: int) -> list[dict]:
    records = []
    print(f"\n{'#' * 100}\nRUN {n}\n{'#' * 100}")
    for q in questions:
        rec.reset()
        cls = deps.classifier.classify(q["question"])
        print(f"\n== Q{q['id']} {q['question']}")
        with metered() as meter:
            try:
                r = await answer_question(
                    deps,
                    org_id=org_ids[q["org"]],
                    org_name=ORG_NAMES[q["org"]],
                    question=q["question"],
                )
            except AnswerUnavailableError as exc:
                print(f"   ERROR {exc}")
                records.append({"id": q["id"], "error": str(exc), "pass": False})
                continue
        winner = next(
            (
                v.label.split(":")[0]
                for v in r.verdicts
                if v.kind in ("choice", "score") and v.value == "TRUE"
            ),
            None,
        )

        # Which page each prompt ref pointed to (decision path refs are c1.. over the top chunks).
        refs_to_pages: dict[str, str] = {}
        by_hyp = {h: (p, res) for p, h, res in rec.nli}
        plan = rec.plans[-1] if rec.plans else None
        if plan is not None:
            for d in plan.decisions:
                premise = by_hyp.get(d.rule, (None,))[0]
                if premise is not None:
                    page = next((pg for txt, pg in chunk_pages.items() if premise in txt), "?")
                    refs_to_pages.setdefault(d.source_chunk, page)
        matched, extras = compare_plans(q["id"], plan, refs_to_pages) if plan else ([], [])
        problems = _check(q, r, winner, matched)
        answer_notes = _answer_checks(r)

        actual = [f"route {r.route}", f"outcome {r.outcome}"]
        if r.overall:
            actual.append(f"overall {r.overall}")
        if winner:
            actual.append(f"winner {winner}")
        exp = EXPECTED.get(q["id"], {})
        expected = (
            "outcome unanswered"
            if q["expected_sources"] is None
            else " · ".join(f"{k} {v}" for k, v in exp.items())
        )
        print(f"   classifier: {cls.label} ({cls.probability:.2f})")
        print(f"   expected:   {expected}")
        print(f"   actual:     {' · '.join(actual)}")
        print(f"   result:     {'PASS' if not problems else 'FAIL: ' + '; '.join(problems)}")

        verdicts = {v.id: v for v in r.verdicts}
        if plan is not None and plan.decisions:
            print(
                f"   Claude's plan ({plan.combine}; {len(rec.plans)} decompose call(s)"
                f"{'; RETRIED' if rec.feedback else ''}):"
            )
            facts = ", ".join(f"{f.name}={f.value!r}" for f in plan.user_facts) or "none"
            print(f"     user facts: {facts}")
            for d in plan.decisions:
                v = verdicts.get(d.id)
                spec = (
                    f"{d.fact} {d.op} {d.value!r}" if d.check == "fact" else f'nli "{d.hypothesis}"'
                )
                print(f"     {d.id} {spec}  [{d.label}]  cites {d.source_chunk}")
                print(f"        rule: {d.rule}")
                check = by_hyp.get(d.rule if d.check == "fact" else d.hypothesis)
                if check is not None:
                    premise, res = check
                    print(
                        f"        rule check: entailment {res.entailment:.3f} "
                        f'(contradiction {res.contradiction:.3f}) vs anchor "{premise[:90]}"'
                    )
                elif d.check == "fact":
                    print("        rule check: not run (rejected by the code checks)")
                if v is None:
                    print("        verdict: dropped")
                else:
                    extra = f", you: {v.user_value!r}" if v.user_value is not None else ""
                    extra += f", missing: {v.missing_fact}" if v.missing_fact else ""
                    print(f"        verdict: {v.value} (conf {v.confidence:.2f}){extra}")
            for fb in rec.feedback:
                print("     retry feedback sent to Claude:")
                for e in fb:
                    print(f"       - {e}")
            if matched:
                print("   vs reference plan:")
                for row in matched:
                    ref, c = row["ref"], row["claude"]
                    ref_s = f"{ref['fact']} {ref['op']} {ref['value']!r}"
                    c_s = f"{c.fact} {c.op} {c.value!r}" if c else "-"
                    print(f"     {row['status']:<15} ref: {ref_s:<34} claude: {c_s}")
                for c in extras:
                    spec = f"{c.fact} {c.op} {c.value!r}" if c.check == "fact" else c.hypothesis
                    print(f"     EXTRA           claude: {spec}  [{c.label}]")
        elif r.route == "policy" and r.verdicts:
            (v,) = r.verdicts
            print(f'   policy hypothesis: "{v.label}."')
            for premise, _h, res in rec.nli:
                print(
                    f'     anchor "{premise[:80]}": entailment {res.entailment:.3f}, '
                    f"contradiction {res.contradiction:.3f}"
                )
            print(f"     verdict: {v.value} (confidence {v.confidence:.2f})")
        elif r.verdicts:
            for item in rec.comparison:
                print(f"   Claude: {item!r}"[:300])
            for v in r.verdicts:
                src = f" ({v.source.file} p{v.source.page})" if v.source else ""
                print(f"     {v.id} {v.value:<7} {v.label} {v.detail or ''}{src}")
        if r.references:
            print("   refs:   " + ", ".join(f"{x.file} p{x.page}" for x in r.references))
        print(f"   answer ({r.answer_source}): {r.answer.replace(chr(10), ' / ')}")
        for note in answer_notes:
            print(f"   !! answer check: {note}")
        t = r.timings_ms
        stages = ["classify", "retrieve", "decompose", "grounding", "decisions", "compose", "total"]
        print("   latency ms: " + "  ".join(f"{k} {_fmt_ms(t, k)}" for k in stages))
        print(
            f"   tokens: in {meter.input_tokens} (+{meter.cache_read_input_tokens} cache read, "
            f"+{meter.cache_creation_input_tokens} cache write)  out {meter.output_tokens}  "
            f"over {len(meter.calls)} call(s): "
            + ", ".join(f"{c.method}:{c.input_tokens}/{c.output_tokens}" for c in meter.calls)
        )
        records.append(
            {
                "id": q["id"],
                "pass": not problems,
                "problems": problems,
                "route": r.route,
                "outcome": r.outcome,
                "overall": r.overall,
                "winner": winner,
                "verdicts": [(v.label, v.value) for v in r.verdicts],
                "plan_rows": [(row["ref"]["label"], row["status"]) for row in matched],
                "extras": [c.label for c in extras],
                "retried": bool(rec.feedback),
                "answer_notes": answer_notes,
                "answer": r.answer,
                "timings": {
                    k: (max(v.values()) if isinstance(v, dict) and v else v) for k, v in t.items()
                },
                "tokens": {
                    "input": meter.input_tokens,
                    "output": meter.output_tokens,
                    "cache_read": meter.cache_read_input_tokens,
                    "cache_write": meter.cache_creation_input_tokens,
                },
            }
        )
    passed = sum(r["pass"] for r in records)
    print(f"\nRUN {n}: {passed}/{len(questions)} questions as expected")
    return records


def summarize(runs: list[list[dict]]) -> None:
    print(f"\n{'#' * 100}\nSUMMARY\n{'#' * 100}")
    for i, recs in enumerate(runs, 1):
        print(f"run {i}: {sum(r['pass'] for r in recs)}/{len(recs)} pass")
    if len(runs) > 1:
        print("\ndifferences between runs (outcome, overall, verdicts, plan match, pass):")
        diffs = 0
        for recs in zip(*runs, strict=True):
            keys = [
                (
                    r.get("outcome"),
                    r.get("overall"),
                    r.get("winner"),
                    tuple(r.get("verdicts", [])),
                    tuple(r.get("plan_rows", [])),
                    r.get("pass"),
                )
                for r in recs
            ]
            if len(set(keys)) > 1:
                diffs += 1
                print(f"  Q{recs[0]['id']}:")
                for i, r in enumerate(recs, 1):
                    print(
                        f"    run {i}: pass={r.get('pass')} outcome={r.get('outcome')} "
                        f"overall={r.get('overall')} verdicts={r.get('verdicts')} "
                        f"plan={r.get('plan_rows')} problems={r.get('problems')}"
                    )
        if not diffs:
            print("  none")
    every = [r for recs in runs for r in recs if "timings" in r]
    print("\nlatency (ms) over all questions and runs:")
    for stage in (
        "classify",
        "retrieve",
        "decompose",
        "grounding",
        "decisions",
        "compose",
        "total",
    ):
        vals = [r["timings"][stage] for r in every if r["timings"].get(stage) is not None]
        if vals:
            worst = max(every, key=lambda r: r["timings"].get(stage) or -1)
            print(
                f"  {stage:<10} avg {sum(vals) / len(vals):>7.0f}   worst {max(vals):>6}  "
                f"(Q{worst['id']})   n={len(vals)}"
            )
    answered = [r for r in every if r["tokens"]["input"] or r["tokens"]["output"]]
    cost = [
        (
            r["tokens"]["input"] * PRICE["input"]
            + r["tokens"]["output"] * PRICE["output"]
            + r["tokens"]["cache_read"] * PRICE["cache_read"]
            + r["tokens"]["cache_write"] * PRICE["cache_write"]
        )
        / 1e6
        for r in every
    ]
    tok_in = sum(r["tokens"]["input"] for r in every) / len(every)
    tok_out = sum(r["tokens"]["output"] for r in every) / len(every)
    print(
        f"\ntokens per question (avg over all {len(every)}): input {tok_in:.0f}, "
        f"output {tok_out:.0f}; {len(answered)} of {len(every)} used the LLM"
    )
    print(f"cost per question: avg ${sum(cost) / len(cost):.4f}, worst ${max(cost):.4f}")
    print(f"estimated cost per 100 questions (this mix): ${100 * sum(cost) / len(cost):.2f}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--json", type=Path, help="write per-question records here")
    args = parser.parse_args()
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
                    deps = replace(
                        deps, llm=ReferenceLLM({q["question"]: q["id"] for q in questions})
                    )
                    print("LLM: reference plans (no API key); answers are extractive")
                else:
                    print(
                        f"LLM: {settings.llm_provider} {settings.llm_model} "
                        f"(effort: decompose {settings.llm_effort_decompose}, "
                        f"compose {settings.llm_effort_compose})"
                    )
                rec = Recorder()
                deps = replace(
                    deps, nli=RecordingNli(deps.nli, rec), llm=RecordingLLM(deps.llm, rec)
                )
                chunk_pages: dict[str, str] = {}
                async with app.state.db_pool.acquire() as conn:
                    for org_id in org_ids.values():
                        rows = await conn.fetch(
                            "SELECT c.text, d.filename, c.page FROM chunks c JOIN documents d"
                            " ON d.id = c.document_id AND d.org_id = c.org_id WHERE c.org_id = $1",
                            org_id,
                        )
                        for row in rows:
                            chunk_pages[row["text"]] = f"{row['filename']} p{row['page']}"
                runs = []
                for n in range(1, args.runs + 1):
                    runs.append(
                        await run_once(
                            deps,
                            questions,
                            org_ids,
                            rec,
                            chunk_pages,
                            settings.rule_grounding_threshold,
                            n,
                        )
                    )
                summarize(runs)
                if args.json:
                    args.json.write_text(json.dumps(runs, indent=1, default=str), encoding="utf-8")
                return 0 if all(r["pass"] for recs in runs for r in recs) else 1
            finally:
                async with app.state.db_pool.acquire() as conn:
                    for org_id in org_ids.values():
                        await conn.execute("DELETE FROM organizations WHERE id = $1", org_id)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
