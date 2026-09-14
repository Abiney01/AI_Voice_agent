import asyncio
import logging
from typing import List, Optional

from app.core.config import get_settings
from app.services.gemini.client import get_gemini_api  # Ensures genai is configured once

logger = logging.getLogger(__name__)
settings = get_settings()

EMBEDDING_MODEL = settings.gemini_embedding_model
EMBEDDING_DIM = 768


async def get_embedding(text: str) -> Optional[List[float]]:
    """Generate a text embedding using Gemini embedding model (non-blocking, 5s timeout)."""
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY not set — skipping embedding generation")
        return None
    try:
        _genai = get_gemini_api()
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=text,
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBEDDING_DIM,
                ),
            ),
            timeout=5.0,
        )
        return result["embedding"]
    except asyncio.TimeoutError:
        logger.warning("Embedding generation timed out after 5s")
        return None
    except Exception as e:
        logger.error(f"Embedding generation error: {e}")
        return None


async def get_query_embedding(text: str) -> Optional[List[float]]:
    """Generate a query embedding for similarity search (non-blocking, 5s timeout)."""
    if not settings.gemini_api_key:
        return None
    try:
        _genai = get_gemini_api()
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=text,
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=EMBEDDING_DIM,
                ),
            ),
            timeout=5.0,
        )
        return result["embedding"]
    except asyncio.TimeoutError:
        logger.warning("Query embedding timed out after 5s")
        return None
    except Exception as e:
        logger.error(f"Query embedding error: {e}")
        return None
