"""Per-request LLM usage accounting.

A UsageMeter is opened around one question (`with metered() as meter:`); every LLM call made while
it's open adds its token counts. Context variables keep concurrent requests separate.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class LLMCall:
    method: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    stop_reason: str | None = None


@dataclass
class UsageMeter:
    calls: list[LLMCall] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def cache_read_input_tokens(self) -> int:
        return sum(c.cache_read_input_tokens for c in self.calls)

    @property
    def cache_creation_input_tokens(self) -> int:
        return sum(c.cache_creation_input_tokens for c in self.calls)


_current: ContextVar[UsageMeter | None] = ContextVar("llm_usage_meter", default=None)


@contextmanager
def metered() -> Iterator[UsageMeter]:
    meter = UsageMeter()
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


def record(call: LLMCall) -> None:
    meter = _current.get()
    if meter is not None:
        meter.calls.append(call)
