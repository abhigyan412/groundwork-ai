from app.config import Settings
from app.llm.base import LLMClient


def load_llm(settings: Settings) -> LLMClient:
    """Supported providers: gemini (demo default), anthropic, fake (tests and offline)."""
    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(settings)
    if settings.llm_provider == "gemini":
        from app.llm.gemini_client import GeminiLLM

        return GeminiLLM(settings)
    from app.llm.fake import FakeLLMClient

    return FakeLLMClient()
