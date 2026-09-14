from groq import AsyncGroq
from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _ensure_configured() -> None:
    """Ensure that the Groq API key is configured in the settings."""
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Please add it to your .env file."
        )


@lru_cache
def get_groq_client() -> AsyncGroq:
    """Return a cached AsyncGroq client instance."""
    _ensure_configured()
    return AsyncGroq(api_key=settings.groq_api_key)
