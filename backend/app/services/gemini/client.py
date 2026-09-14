import google.generativeai as genai
from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _ensure_configured() -> None:
    """Configure the Gemini SDK exactly once (lru_cache guarantees single execution)."""
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Please add it to your .env file."
        )
    genai.configure(api_key=settings.gemini_api_key)


def get_gemini_api() -> genai:
    """Return the configured genai module (for embeddings / semantic memory)."""
    _ensure_configured()
    return genai
