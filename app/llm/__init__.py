from app.config import Settings
from app.llm.base import LLMClient


def load_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(settings)
    from app.llm.fake import FakeLLMClient

    return FakeLLMClient()
