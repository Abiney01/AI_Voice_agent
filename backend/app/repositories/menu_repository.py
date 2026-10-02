from typing import List, Optional
from app.core.prisma import prisma
from app.prisma_client.models import MenuItem
from app.schemas.menu import MenuItemCreate


class MenuRepository:
    async def get_all(self, available_only: bool = True) -> List[MenuItem]:
        where = {"is_available": True} if available_only else {}
        return await prisma.menuitem.find_many(
            where=where,
            order=[
                {"cuisine": "asc"},
                {"category": "asc"},
                {"name": "asc"}
            ]
        )

    async def get_by_id(self, item_id: int) -> Optional[MenuItem]:
        return await prisma.menuitem.find_unique(where={"id": item_id})

    async def search(self, query: str) -> List[MenuItem]:
        return await prisma.menuitem.find_many(
            where={
                "is_available": True,
                "OR": [
                    {"name": {"contains": query, "mode": "insensitive"}},
                    {"category": {"contains": query, "mode": "insensitive"}},
                    {"cuisine": {"contains": query, "mode": "insensitive"}},
                    {"description": {"contains": query, "mode": "insensitive"}},
                ]
            },
            order={"name": "asc"}
        )

    async def find_by_name(self, name: str) -> Optional[MenuItem]:
        """Robust fuzzy name lookup for order extraction."""
        import re

        if not name or not name.strip():
            return None

        def _clean(s: str) -> str:
            # Remove (V), [spice], (2 pcs), (6 pcs), (12"), etc.
            s = re.sub(r'\s*\([vV]\)\s*', ' ', s)
            s = re.sub(r'\s*\[[^\]]+\]\s*', ' ', s)
            s = re.sub(r'\s*\([^)]*\)\s*', ' ', s)
            s = re.sub(r'["\']', '', s)
            return re.sub(r'\s+', ' ', s).strip()

        def _tokenize(s: str) -> set:
            cleaned = _clean(s).lower()
            tokens = set(re.findall(r'[a-z0-9]+', cleaned))
            # Include singular versions for basic plurals
            singulars = set()
            for t in tokens:
                if len(t) > 3 and t.endswith('s') and not t.endswith('ss'):
                    singulars.add(t[:-1])
                elif t == "coke":
                    singulars.add("coca")
                    singulars.add("cola")
            return tokens | singulars

        cleaned_name = _clean(name)

        # 1. Exact match (case-insensitive)
        item = await prisma.menuitem.find_first(
            where={
                "name": {"equals": cleaned_name, "mode": "insensitive"},
                "is_available": True
            }
        )
        if item:
            return item

        # 2. Substring match
        item = await prisma.menuitem.find_first(
            where={
                "name": {"contains": cleaned_name, "mode": "insensitive"},
                "is_available": True
            }
        )
        if item:
            return item

        # 3. Token-based fuzzy matching over all available items
        all_items = await prisma.menuitem.find_many(where={"is_available": True})
        query_tokens = _tokenize(name)
        if not query_tokens:
            return None

        best_item = None
        best_score = 0.0

        for it in all_items:
            it_clean = _clean(it.name).lower()
            # If cleaned query is an exact match for cleaned item name
            if it_clean == cleaned_name.lower():
                return it

            it_tokens = _tokenize(it.name)
            intersection = query_tokens & it_tokens
            if not intersection:
                continue

            # Prioritize matching all query tokens
            # E.g. "chicken biryani" query has 2 tokens; if both match "Chicken Biryani", score is high
            query_coverage = len(intersection) / len(query_tokens)
            it_coverage = len(intersection) / len(it_tokens)
            score = (query_coverage * 0.7) + (it_coverage * 0.3)

            # Bonus if original item name contains query substring
            if cleaned_name.lower() in it.name.lower():
                score += 0.2

            if score > best_score:
                best_score = score
                best_item = it

        # Require a reasonable matching threshold (at least 50% match)
        if best_item and best_score >= 0.4:
            return best_item

        return None



    async def create(self, data: MenuItemCreate) -> MenuItem:
        return await prisma.menuitem.create(data=data.model_dump())

    async def count(self) -> int:
        return await prisma.menuitem.count()
