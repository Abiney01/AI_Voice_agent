import logging
from typing import List, Optional

from app.core.prisma import prisma
from app.prisma_client.models import ConversationSummary

logger = logging.getLogger(__name__)


def _vec_str(embedding: List[float]) -> str:
    """
    Convert a float list to the pgvector literal format.
    str([0.1, 0.2]) → '[0.1, 0.2]'  (works with pgvector)
    We join without spaces to be safe: '[0.1,0.2]'
    """
    return "[" + ",".join(str(v) for v in embedding) + "]"


class MemoryRepository:
    async def save_summary(
        self,
        customer_id: int,
        summary: str,
        embedding: Optional[List[float]] = None,
    ) -> ConversationSummary:
        try:
            if embedding:
                embedding_str = _vec_str(embedding)
                res = await prisma.query_raw(
                    "INSERT INTO conversation_summaries (customer_id, summary, embedding) "
                    "VALUES ($1, $2, CAST($3 AS vector)) RETURNING id",
                    customer_id,
                    summary,
                    embedding_str,
                )
            else:
                res = await prisma.query_raw(
                    "INSERT INTO conversation_summaries (customer_id, summary) "
                    "VALUES ($1, $2) RETURNING id",
                    customer_id,
                    summary,
                )

            new_id = res[0]["id"]
            record = await prisma.conversationsummary.find_unique(where={"id": new_id})
            if not record:
                raise RuntimeError("Failed to retrieve saved summary")
            logger.info("Saved conversation summary id=%s for customer %s", new_id, customer_id)
            return record
        except Exception as e:
            logger.error("Failed to save conversation summary for customer %s: %s", customer_id, e, exc_info=True)
            raise

    async def get_recent(self, customer_id: int, limit: int = 5) -> List[ConversationSummary]:
        return await prisma.conversationsummary.find_many(
            where={"customer_id": customer_id},
            order={"created_at": "desc"},
            take=limit,
        )

    async def search_similar(
        self,
        customer_id: int,
        query_embedding: List[float],
        limit: int = 3,
    ) -> List[ConversationSummary]:
        """Vector similarity search using pgvector cosine distance."""
        embedding_str = _vec_str(query_embedding)
        try:
            rows = await prisma.query_raw(
                """
                SELECT id, customer_id, summary, created_at
                FROM conversation_summaries
                WHERE customer_id = $1 AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST($2 AS vector)
                LIMIT $3
                """,
                customer_id,
                embedding_str,
                limit,
            )
            return [ConversationSummary(**row) for row in rows]
        except Exception as e:
            logger.error("Vector search failed for customer %s: %s", customer_id, e)
            return []

    async def search_similar_customers(
        self,
        customer_id: int,
        preference_embedding: List[float],
        limit: int = 10,
    ) -> List[int]:
        """Find customers with similar preferences using vector similarity."""
        embedding_str = _vec_str(preference_embedding)
        try:
            rows = await prisma.query_raw(
                """
                SELECT cs.customer_id
                FROM conversation_summaries cs
                WHERE cs.customer_id != $1
                  AND cs.embedding IS NOT NULL
                ORDER BY cs.embedding <=> CAST($2 AS vector)
                LIMIT $3
                """,
                customer_id,
                embedding_str,
                limit,
            )
            return [row.get("customer_id") for row in rows if row.get("customer_id") is not None]
        except Exception as e:
            logger.error("Similar customer search failed: %s", e)
            return []
