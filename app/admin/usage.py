"""Usage and recent questions for the dashboard (JWT only, scoped to the JWT's org)."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.deps import CurrentOrg
from app.db.pool import get_db
from app.engine.types import Outcome, Reference, Route, Verdict
from app.questions import repository as repo

router = APIRouter(prefix="/api/admin", tags=["usage"])

DB = Annotated[asyncpg.Connection, Depends(get_db)]
_401 = {401: {"description": "Missing or invalid admin token"}}


class Usage(BaseModel):
    asked: int
    answered: int
    unanswered: int
    needs_info: int
    review: int


class QuestionOut(BaseModel):
    id: UUID
    question: str
    route: Route | None
    outcome: Outcome
    answer: str
    verdicts: list[Verdict]
    references: list[Reference]
    timings_ms: dict[str, Any]
    created_at: datetime


class QuestionList(BaseModel):
    questions: list[QuestionOut]


@router.get("/usage", name="get_usage", responses=_401)
async def get_usage(account: CurrentOrg, conn: DB) -> Usage:
    return Usage(**await repo.usage_counts(conn, account.org_id))


@router.get("/questions", name="list_questions", responses=_401)
async def list_questions(
    account: CurrentOrg,
    conn: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> QuestionList:
    """Recent questions with their stored evidence trail, newest first."""
    rows = await repo.recent(conn, account.org_id, limit)
    return QuestionList(questions=[QuestionOut(**r.__dict__) for r in rows])
