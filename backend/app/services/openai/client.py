from openai import AsyncOpenAI
from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _ensure_configured() -> None:
    """Ensure that the OpenAI API key is configured in the settings."""
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Please add it to your .env file."
        )


@lru_cache
def get_openai_client() -> AsyncOpenAI:
    """Return a cached AsyncOpenAI client instance (supports OpenAI, Groq, Ollama, OpenRouter, Gemini)."""
    _ensure_configured()
    kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url and settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return AsyncOpenAI(**kwargs)
