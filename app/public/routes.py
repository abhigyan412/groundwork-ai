"""Public API for the widget. Accepts only the assistant token (never the admin JWT); org_id comes
from the token lookup, never from the request (CLAUDE.md)."""

import asyncio
import time
from collections import defaultdict, deque
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.assistant import repository as assistants
from app.assistant.repository import TokenOwner
from app.assistant.suggestions import SuggestionCache, suggested_questions
from app.assistant.tokens import hash_token
from app.config import Settings, get_settings
from app.engine.pipeline import AnswerUnavailableError, answer_question
from app.engine.types import AskResult
from app.llm.base import LLMQuotaExhaustedError
from app.llm.usage import UsageMeter, metered
from app.questions import repository as questions

router = APIRouter(tags=["public"])

AppSettings = Annotated[Settings, Depends(get_settings)]

INVALID_LINK_MESSAGE = "This assistant link is invalid or has been reset"
_401 = {"description": INVALID_LINK_MESSAGE}
UNAVAILABLE_MESSAGE = "Couldn't generate an answer, please try again"
QUOTA_MESSAGE = (
    "Today's question limit for this assistant has been reached. Please try again later."
)
SLOW_MESSAGE = "This is taking too long right now. Please try again in a moment."


def _caused_by_quota(exc: BaseException) -> bool:
    """True if a daily LLM quota is behind the failure (anywhere in the cause chain)."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, LLMQuotaExhaustedError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


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


@router.get(
    "/api/public/assistant/{token}",
    name="public_assistant",
    responses={401: _401},
)
async def public_assistant(token: str, request: Request, settings: AppSettings) -> PublicAssistant:
    """Org name and up to 3 suggested questions, built from section headings in the org's
    documents and kept only if they clear the groundedness gate (app/assistant/suggestions.py)."""
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        owner = await _owner(conn, token)
    if not hasattr(request.app.state, "suggestion_cache"):
        request.app.state.suggestion_cache = SuggestionCache()
    suggestions = await suggested_questions(
        request.app.state.engine,
        request.app.state.suggestion_cache,
        owner.org_id,
        settings.suggested_questions_max,
    )
    return PublicAssistant(org_name=owner.org_name, suggested_questions=suggestions)


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
        503: {"description": "No answer: LLM unavailable, daily limit reached, or too slow"},
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
    failure: str | None = None  # visitor-facing message for a 503
    result: AskResult | None = None
    with metered() as meter:
        try:
            # Answer before nginx's 180 s proxy timeout would turn this into a bare 504.
            async with asyncio.timeout(settings.ask_timeout_seconds):
                result = await answer_question(
                    request.app.state.engine,
                    org_id=owner.org_id,
                    org_name=owner.org_name,
                    question=question,
                )
        except TimeoutError:
            failure = SLOW_MESSAGE
        except AnswerUnavailableError as exc:
            failure = QUOTA_MESSAGE if _caused_by_quota(exc) else UNAVAILABLE_MESSAGE
    latency = round((time.perf_counter() - start) * 1000)

    async with pool.acquire() as conn:
        await questions.log_question(
            conn,
            org_id=owner.org_id,
            question=question,
            route=result.route if result else None,
            outcome=result.outcome if result else "review",
            overall=result.overall if result else None,
            answer=result.answer if result else f"(no answer: {failure})",
            verdicts=[v.model_dump(mode="json") for v in result.verdicts] if result else [],
            references=[r.model_dump(mode="json") for r in result.references] if result else [],
            timings_ms=result.timings_ms if result else {},
            llm_usage=_usage_summary(meter),
            latency_ms=latency,
        )
    if failure is not None:
        raise HTTPException(status_code=503, detail=failure)
    assert result is not None
    return result
