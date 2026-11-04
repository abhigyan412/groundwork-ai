"""Public API for the widget. Accepts only the assistant token (never the admin JWT); org_id comes
from the token lookup, never from the request (CLAUDE.md)."""

import time
from collections import defaultdict, deque
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.assistant import repository as assistants
from app.assistant.repository import TokenOwner
from app.assistant.tokens import hash_token
from app.config import Settings, get_settings
from app.db.pool import get_db
from app.engine.pipeline import AnswerUnavailableError, answer_question
from app.engine.types import AskResult
from app.llm.usage import UsageMeter, metered
from app.questions import repository as questions

router = APIRouter(tags=["public"])

AppSettings = Annotated[Settings, Depends(get_settings)]

INVALID_LINK_MESSAGE = "This assistant link is invalid or has been reset"
_401 = {"description": INVALID_LINK_MESSAGE}
MAX_TOKEN_CHARS = 200  # real tokens are 43 characters (token_urlsafe(32))


class PublicAssistant(BaseModel):
    org_name: str
    suggested_questions: list[str]


class AskRequest(BaseModel):
    token: str = Field(description="Assistant token from the widget URL")
    question: str = Field(max_length=10_000)


async def _owner(conn: asyncpg.Connection, token: str) -> TokenOwner:
    # Anything that can't be a token (empty, oversized, e.g. an admin JWT) is just an invalid
    # link: 401, never a form error, and no DB lookup.
    plausible = 0 < len(token) <= MAX_TOKEN_CHARS
    owner = await assistants.owner_of(conn, hash_token(token)) if plausible else None
    if owner is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_LINK_MESSAGE)
    return owner


def suggested_from_filenames(filenames: list[str], limit: int) -> list[str]:
    """'Scholarship_Rules.pdf' → 'What does the Scholarship Rules document cover?' (no LLM)."""
    out: list[str] = []
    for name in filenames:
        stem = name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
        title = " ".join(stem.split())
        if title:
            out.append(f"What does the {title} document cover?")
        if len(out) == limit:
            break
    return out


@router.get(
    "/api/public/assistant/{token}",
    name="public_assistant",
    responses={401: _401},
)
async def public_assistant(
    token: str, conn: Annotated[asyncpg.Connection, Depends(get_db)], settings: AppSettings
) -> PublicAssistant:
    owner = await _owner(conn, token)
    files = await questions.ready_filenames(conn, owner.org_id)
    return PublicAssistant(
        org_name=owner.org_name,
        suggested_questions=suggested_from_filenames(files, settings.suggested_questions_max),
    )


class _RateLimiter:
    """Sliding one-minute window per assistant, in this process's memory. A shared store
    (e.g. Redis) would be needed with several API processes."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, per_minute: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= 60:
            hits.popleft()
        if len(hits) >= per_minute:
            return False
        hits.append(now)
        return True


def _limiter(request: Request) -> _RateLimiter:
    if not hasattr(request.app.state, "ask_limiter"):
        request.app.state.ask_limiter = _RateLimiter()
    return request.app.state.ask_limiter


def _usage_summary(meter: UsageMeter) -> dict:
    return {
        "calls": len(meter.calls),
        "input_tokens": meter.input_tokens,
        "output_tokens": meter.output_tokens,
        "cache_read_input_tokens": meter.cache_read_input_tokens,
        "models": sorted({c.model for c in meter.calls}),
    }


@router.post(
    "/api/ask",
    name="ask",
    responses={
        400: {"description": "Please enter a question"},
        401: _401,
        429: {"description": "Too many questions for this assistant right now"},
        503: {"description": "Couldn't generate an answer, please try again"},
    },
)
async def ask(body: AskRequest, request: Request, settings: AppSettings) -> AskResult:
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as conn:  # released before the (slow) pipeline runs
        owner = await _owner(conn, body.token)

    question = " ".join(body.question.split())
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a question")
    if len(question) > settings.ask_max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Questions can be up to {settings.ask_max_question_chars} characters.",
        )
    if not _limiter(request).allow(str(owner.assistant_id), settings.ask_rate_limit_per_minute):
        raise HTTPException(
            status_code=429, detail="Too many questions right now. Please wait a minute."
        )

    start = time.perf_counter()
    unavailable: AnswerUnavailableError | None = None
    result: AskResult | None = None
    with metered() as meter:
        try:
            result = await answer_question(
                request.app.state.engine,
                org_id=owner.org_id,
                org_name=owner.org_name,
                question=question,
            )
        except AnswerUnavailableError as exc:
            unavailable = exc
    latency = round((time.perf_counter() - start) * 1000)

    async with pool.acquire() as conn:
        await questions.log_question(
            conn,
            org_id=owner.org_id,
            question=question,
            route=result.route if result else None,
            outcome=result.outcome if result else "review",
            answer=result.answer if result else "(no answer: the language model was unavailable)",
            verdicts=[v.model_dump(mode="json") for v in result.verdicts] if result else [],
            references=[r.model_dump(mode="json") for r in result.references] if result else [],
            timings_ms=result.timings_ms if result else {},
            llm_usage=_usage_summary(meter),
            latency_ms=latency,
        )
    if unavailable is not None:
        raise HTTPException(
            status_code=503, detail="Couldn't generate an answer, please try again"
        ) from unavailable
    assert result is not None
    return result
