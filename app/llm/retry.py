"""Retry with exponential backoff for rate limits (429) and transient server errors.

Free tiers allow only a few requests per minute, so a 429 is expected under load, not a failure.
Each retry waits base * 2^attempt (plus a little jitter), or the provider's own retry hint when it
sends one, and the total wait for one call is capped so a visitor isn't kept waiting for minutes.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

# (should retry, provider's suggested delay in seconds or None)
Classifier = Callable[[BaseException], tuple[bool, float | None]]


async def with_backoff(
    call: Callable[[], Awaitable[T]],
    *,
    classify: Classifier,
    retries: int,
    base_seconds: float,
    max_total_wait: float,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    sleep = sleep or asyncio.sleep  # resolved per call, so tests can patch asyncio.sleep
    waited = 0.0
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            retryable, hint = classify(exc)
            if not retryable or attempt >= retries:
                raise
            delay = hint if hint is not None else base_seconds * 2**attempt
            delay += random.uniform(0, base_seconds / 2)  # noqa: S311 - jitter, not crypto
            if waited + delay > max_total_wait:
                raise
            log.info("LLM call retry %d after %.1fs (%s)", attempt + 1, delay, type(exc).__name__)
            await sleep(delay)
            waited += delay
            attempt += 1
