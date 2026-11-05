"""Retry with exponential backoff for rate limits (429) and transient server errors.

Free tiers allow only a few requests per minute, so a 429 is expected under load, not a failure.
Each retry waits base * 2^attempt (plus a little jitter), or the provider's own retry hint when it
sends one.

Two limits keep a visitor from waiting for minutes:
- `deadline`: wall-clock time for the whole call, *attempts included*. Each attempt only gets the
  time that's left, and no retry is started that couldn't finish in time. (Capping only the waits
  between attempts isn't enough: a provider that times out at 60 s per attempt would then hang a
  question for minutes, as gemini-3.8-flash did on 2026-11-05.)
- `max_total_wait`: total time spent sleeping between attempts.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

# (should retry, provider's suggested delay in seconds or None)
Classifier = Callable[[BaseException], tuple[bool, float | None]]


class DeadlineExceededError(TimeoutError):
    """The call (all attempts and waits together) didn't finish within its deadline."""


async def with_backoff(
    call: Callable[[], Awaitable[T]],
    *,
    classify: Classifier,
    retries: int,
    base_seconds: float,
    max_total_wait: float,
    deadline: float | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    sleep = sleep or asyncio.sleep  # resolved per call, so tests can patch asyncio.sleep
    started = time.monotonic()
    waited = 0.0
    attempt = 0

    def remaining() -> float:
        return float("inf") if deadline is None else deadline - (time.monotonic() - started)

    while True:
        left = remaining()
        if left <= 0:
            raise DeadlineExceededError(f"no time left after {attempt} attempt(s)")
        try:
            if deadline is None:
                return await call()
            async with asyncio.timeout(left):
                return await call()
        except TimeoutError as exc:
            if remaining() <= 0:
                raise DeadlineExceededError(f"deadline of {deadline:.0f} s reached") from exc
            raise
        except Exception as exc:
            retryable, hint = classify(exc)
            if not retryable or attempt >= retries:
                raise
            delay = hint if hint is not None else base_seconds * 2**attempt
            delay += random.uniform(0, base_seconds / 2)  # noqa: S311 - jitter, not crypto
            # Don't start a wait that would overrun either limit: fail now, with the real error.
            if waited + delay > max_total_wait or delay >= remaining():
                raise
            log.info("LLM call retry %d after %.1fs (%s)", attempt + 1, delay, type(exc).__name__)
            await sleep(delay)
            waited += delay
            attempt += 1
