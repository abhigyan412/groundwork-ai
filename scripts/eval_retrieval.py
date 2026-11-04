"""Evaluate retrieval and the groundedness gate on sample_data/questions.json with the REAL models.

    docker compose up -d db
    python scripts/eval_retrieval.py                       # configured thresholds
    python scripts/eval_retrieval.py --threshold 0.5 --decision-threshold -4

Runs the app in-process (one copy of the models) against DATABASE_URL: registers two throwaway
orgs, uploads sample_data/{riverside,northwind}/*.pdf, asks every question, prints the top
sources and reranker scores, then deletes the throwaway orgs (cascade removes their data).

The gate is per route (docs/ai-design.md §2). Here the route is the question's labelled type; the
classifier's predicted route replaces it once task 04 exists. Not-in-KB questions have no true
route, so they're checked against the strict gate, and the "if decision" column shows whether
they would leak through if the classifier sent them down the decision path.
"""

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.search import gate_threshold, passes_gate, retrieve  # noqa: E402

ORG_NAMES = {"riverside": "Riverside University", "northwind": "Northwind Technologies"}
TOP_N = 3  # an expected source must appear in the top N reranked chunks


async def main(overrides: dict[str, float]) -> int:
    settings = get_settings().model_copy(update=overrides)
    if settings.model_backend != "local":
        sys.exit("Set MODEL_BACKEND=local: this evaluates the real models.")
    questions = json.loads((ROOT / "sample_data/questions.json").read_text(encoding="utf-8"))
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
                            "org_name": f"{name} (eval {tag})",
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
                return await _evaluate(app, settings, questions["questions"], org_ids)
            finally:
                async with app.state.db_pool.acquire() as conn:
                    for org_id in org_ids.values():
                        await conn.execute("DELETE FROM organizations WHERE id = $1", org_id)


async def _evaluate(app, settings: Settings, questions, org_ids) -> int:
    in_kb: dict[str, list[float]] = {"decision": [], "other": []}
    out_kb: list[float] = []
    failures = leaks_if_decision = 0
    print(f"{'#':>2}  {'route':<10} {'gate':<6} {'score':>6}  {'if decision':<11}  top sources")
    for q in questions:
        result = await retrieve(
            app.state.db_pool,
            app.state.embedder,
            app.state.reranker,
            settings,
            org_id=org_ids[q["org"]],
            query=q["question"],
        )
        score = result.top_score if result.top_score is not None else float("-inf")
        top = [(ch.filename, ch.page) for ch in result.chunks[:TOP_N]]
        expected = q["expected_sources"]
        if expected is None:
            route = "-"
            gate_open = passes_gate(result, settings, None)
            ok = not gate_open
            out_kb.append(score)
            leak = passes_gate(result, settings, "decision")
            leaks_if_decision += leak
            if_decision = "LEAKS" if leak else "held"
        else:
            route = q["type"]
            gate_open = passes_gate(result, settings, route)
            ok = gate_open and all((e["file"], e["page"]) in top for e in expected)
            in_kb["decision" if route == "decision" else "other"].append(score)
            if_decision = ""
        failures += not ok
        shown = ", ".join(
            f"{ch.filename} p{ch.page} ({ch.rerank_score:+.1f})" for ch in result.chunks[:TOP_N]
        )
        print(
            f"{q['id']:>2}  {route:<10} {'open' if gate_open else 'closed':<6} {score:>+6.2f}  "
            f"{if_decision:<11}  {shown or '-'}  [{'PASS' if ok else 'FAIL'}]"
        )

    strict, loose = gate_threshold(settings, None), gate_threshold(settings, "decision")
    hi = max(out_kb)
    print(
        f"\nthresholds: strict {strict:+.2f} (direct/procedural/policy/comparison), "
        f"decision {loose:+.2f}"
    )
    print(f"highest not-in-KB top score: {hi:+.2f}")
    for group, threshold in (("other", strict), ("decision", loose)):
        lo = min(in_kb[group])
        print(
            f"lowest in-KB top score ({group}): {lo:+.2f}  margin to its threshold: "
            f"{lo - threshold:+.2f}"
        )
    print(f"margin, strict threshold to highest not-in-KB: {strict - hi:+.2f}")
    print(
        f"not-in-KB questions that would pass the decision gate if misrouted: "
        f"{leaks_if_decision}/{len(out_kb)}"
    )
    print(f"{len(questions) - failures}/{len(questions)} questions passed")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--threshold", type=float, help="strict gate (non-decision routes)")
    parser.add_argument("--decision-threshold", type=float, help="gate for decision questions")
    args = parser.parse_args()
    overrides = {
        k: v
        for k, v in {
            "groundedness_threshold": args.threshold,
            "groundedness_threshold_decision": args.decision_threshold,
        }.items()
        if v is not None
    }
    sys.exit(asyncio.run(main(overrides)))
