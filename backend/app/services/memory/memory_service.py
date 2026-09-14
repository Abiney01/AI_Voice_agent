import logging
from typing import Any, Dict, List, Optional

from app.repositories.customer_repository import CustomerRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.customer import CustomerPreferencesUpdate
from app.services.openai.conversation_service import ConversationService
from app.services.memory.embedding_service import get_embedding, get_query_embedding

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self):
        self.memory_repo = MemoryRepository()
        self.customer_repo = CustomerRepository()
        self.conversation_svc = ConversationService()

    async def store_conversation_summary(
        self, customer_id: int, conversation_text: str
    ) -> None:
        """
        Summarize a conversation and persist it with a vector embedding.
        Called as a BackgroundTask — errors are logged but never crash the response.
        """
        try:
            logger.info("[MEMORY] Summarizing conversation for customer %s", customer_id)
            summary = await self.conversation_svc.summarize_conversation(conversation_text)
            if not summary:
                logger.warning("[MEMORY] Empty summary returned for customer %s — skipping save", customer_id)
                return

            logger.info("[MEMORY] Summary: %s", summary[:120])

            embedding = await get_embedding(summary)
            if embedding is None:
                logger.warning("[MEMORY] Embedding generation failed for customer %s — saving without vector", customer_id)

            await self.memory_repo.save_summary(customer_id, summary, embedding)
            logger.info("[MEMORY] Memory saved for customer %s", customer_id)

            # Also extract and update structured preferences
            await self._update_preferences_from_summary(customer_id, summary)

        except Exception as e:
            logger.error("[MEMORY] store_conversation_summary failed for customer %s: %s", customer_id, e, exc_info=True)

    async def _update_preferences_from_summary(
        self, customer_id: int, summary: str
    ) -> None:
        """Extract preferences from summary and merge into customer_preferences table."""
        try:
            prefs_data = await self.conversation_svc.extract_preferences(summary)
            if not prefs_data:
                return

            # Filter to only known fields
            valid = {
                k: v for k, v in prefs_data.items()
                if k in CustomerPreferencesUpdate.model_fields and v
            }
            if not valid:
                return

            update = CustomerPreferencesUpdate(**valid)
            await self.customer_repo.update_preferences(customer_id, update)
            logger.info("[MEMORY] Preferences updated for customer %s: %s", customer_id, valid)
        except Exception as e:
            logger.error("[MEMORY] Preference update failed for customer %s: %s", customer_id, e)

    async def get_recent_memories(self, customer_id: int) -> List[str]:
        """Get recent conversation summaries as plain text."""
        summaries = await self.memory_repo.get_recent(customer_id, limit=5)
        return [s.summary for s in summaries]

    async def search_relevant_memories(
        self, customer_id: int, query: str
    ) -> List[str]:
        """Vector search for relevant memories, falling back to recency."""
        embedding = await get_query_embedding(query)
        if embedding is None:
            return await self.get_recent_memories(customer_id)

        results = await self.memory_repo.search_similar(customer_id, embedding, limit=3)
        if not results:
            # Vector search found nothing (no memories yet) — fall back to recent
            return await self.get_recent_memories(customer_id)
        return [r.summary for r in results]

    async def get_similar_customer_ids(
        self, customer_id: int, preference_text: str
    ) -> List[int]:
        """Find customers with similar preferences for collaborative recommendations."""
        embedding = await get_embedding(preference_text)
        if embedding is None:
            return []
        return await self.memory_repo.search_similar_customers(
            customer_id, embedding, limit=10
        )
