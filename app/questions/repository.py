"""The questions log: one row per /api/ask, scoped by org_id (docs/data-model.md)."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

OUTCOMES = ("answered", "unanswered", "needs_info", "review")


@dataclass(frozen=True)
class QuestionRow:
    id: UUID
    question: str
    route: str | None
    outcome: str
    overall: str | None
    answer: str
    verdicts: list[dict[str, Any]]
    references: list[dict[str, Any]]
    timings_ms: dict[str, Any]
    created_at: datetime


async def log_question(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    question: str,
    route: str | None,
    outcome: str,
    overall: str | None,
    answer: str,
    verdicts: list[dict[str, Any]],
    references: list[dict[str, Any]],
    timings_ms: dict[str, Any],
    llm_usage: dict[str, Any],
    latency_ms: int,
) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO questions (org_id, question, route, outcome, overall, answer, verdicts,
                               "references", timings_ms, llm_usage, latency_ms)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11)
        RETURNING id
        """,
        org_id,
        question,
        route,
        outcome,
        overall,
        answer,
        json.dumps(verdicts),
        json.dumps(references),
        json.dumps(timings_ms),
        json.dumps(llm_usage),
        latency_ms,
    )


async def usage_counts(conn: asyncpg.Connection, org_id: UUID) -> dict[str, int]:
    rows = await conn.fetch(
        "SELECT outcome, count(*) AS n FROM questions WHERE org_id = $1 GROUP BY outcome", org_id
    )
    counts = dict.fromkeys(OUTCOMES, 0) | {r["outcome"]: r["n"] for r in rows}
    return {"asked": sum(counts.values()), **counts}


async def recent(conn: asyncpg.Connection, org_id: UUID, limit: int) -> list[QuestionRow]:
    rows = await conn.fetch(
        """
        SELECT id, question, route, outcome, overall, answer, verdicts, "references", timings_ms,
               created_at
        FROM questions WHERE org_id = $1
        ORDER BY created_at DESC, id
        LIMIT $2
        """,
        org_id,
        limit,
    )
    return [
        QuestionRow(
            id=r["id"],
            question=r["question"],
            route=r["route"],
            outcome=r["outcome"],
            overall=r["overall"],
            answer=r["answer"],
            verdicts=json.loads(r["verdicts"]),
            references=json.loads(r["references"]),
            timings_ms=json.loads(r["timings_ms"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
